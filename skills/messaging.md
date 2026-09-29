# Messaging

Base types come from EF.Messaging.Contracts (envelope, inbox, consumer base, outbox port), EF.Data.Outbox (outbox, dispatcher, inbox store), `EF.Messaging.RabbitMq` (`IRabbitMqPublisher`, `IRabbitMqMessageHandler`), EF.Messaging.Functions, and `EF.Messaging` (`IServiceBusSender`, `IEventGridPublisher`, `IEventHubProducer`) - see [package-dependencies.md](package-dependencies.md) and the [EF.Packages repo](https://github.com/efreeman518/EF.Packages) for full API details.

## Prerequisites

- [package-dependencies.md](package-dependencies.md)
- [bootstrapper.md](bootstrapper.md)
- [configuration-secrets.md](configuration-secrets.md)
- [background-services.md](background-services.md)

Rule: use `IInternalMessageBus` for in-process events; use this skill for cross-service messaging.

### Event Boundary Rule

Cross-process bus payloads are application/integration contracts, not domain artifacts.

- Aggregates raise domain events (`IDomainEvent`, buffered by `DomainEventContainer` behind `IHasDomainEvents`); the app's `IOutboxEventMapper` turns each into an `IntegrationEventEnvelope` at the application boundary. The envelope frame is the package's; the app owns the payload records, their versions, and the headers (tenant) it adds.
- Keep the envelope helpers (`{Project}IntegrationEvents`: destination, per-type versions, `Envelope(...)`, `Entry(...)`, `ConfigureReader(...)`) in `Application.Contracts.Messaging`; domain, application and consumer projects reference EF.Messaging.Contracts, never EF.Messaging.
- Payload types and the envelope are registered on the app's source-generated messaging `JsonSerializerContext`, and its options are passed everywhere an envelope is serialized or read.

> **Shared infrastructure pattern:** Messaging follows the same **Settings -> Named client -> DI -> Resilience** integration chain as external APIs. See [external-api.md](external-api.md) for the general pattern with Refit/resilience pipeline. This file covers messaging-specific adapters.

## Service Selection

| Need | Service |
|---|---|
| Reliable queue/topic workflows, retries, DLQ - default `NonAzure` lane | RabbitMQ |
| Reliable queue/topic workflows, retries, DLQ - `Azure` lane | Service Bus |
| Event notifications and pub/sub routing | Event Grid |
| High-throughput telemetry/event streams | Event Hub |

## Core Pattern

The outbox, dispatcher, inbox and consumer base are package code (EF.Data.Outbox, EF.Messaging.Contracts; API in [../support/ef-packages-optional.md](../support/ef-packages-optional.md)); the app generates only its mapper, its consumers, its topology, and the registration branch per provider:

- the provider-neutral `IOutboxTransport` port, packaged per broker (`AddRabbitMqOutboxTransport`, `AddServiceBusOutboxTransport`)
- named Azure SDK clients via `IAzureClientFactory<T>` when Azure is selected
- correlation IDs + metadata propagation
- scoped DI in background handlers

### Delivery Semantics Contract

For each channel/event family, define and implement:

- delivery mode assumption (`at-least-once` by default)
- idempotency key source (`MessageId`, business key, or composite)
- outbox requirement for transactional producers
- deduplication window and duplicate-handling behavior

Keep these aligned with `messagingSemantics` in [resource-implementation-schema.md](../ai/resource-implementation-schema.md).

Declaring `outboxEnabled: true` is not implementation. The producer, dispatcher, consumer, retention, and replay tests below are one contract.

### Transactional Producer: Outbox

When a committed database mutation must publish an integration event:

```csharp
// Bootstrapper (every host with the write context)
services.AddSingleton<IOutboxEventMapper, {Project}OutboxEventMapper>();   // envelope + TenantId header
services.AddOutbox<{Project}DbContextTrxn>(o =>
{
    o.DefaultDestination = {Project}IntegrationEvents.Destination;
    o.SerializerOptions = {Project}MessagingJsonContext.Default.Options;
});
// The write context adds the singleton interceptor: options.AddInterceptors(sp.GetRequiredService<OutboxStagingInterceptor>())
// OnModelCreating: modelBuilder.ApplyOutboxModel(SchemaName);

// Dispatcher host only (every replica that should send)
services.AddOptions<OutboxDispatcherOptions>().Bind(config.GetSection("OutboxDispatcher"));
services.AddOutboxDispatcher();
services.AddHealthChecks().AddLeasedWorkBacklogCheck<OutboxMessage>("outbox", tags: ["ready"]);
```

1. `OutboxStagingInterceptor` drains every tracked aggregate's raised events into `OutboxMessage` rows in the same `SaveChanges` as the mutation, with the W3C trace context of the request. Events no aggregate raises (a scheduler job) are staged through `IOutboxStaging.Stage(...)` before that unit's `SaveChanges`, with a deterministic envelope id so a rerun is a duplicate.
2. The dispatcher claims a bounded batch under a lease token, sends each destination group through `IOutboxTransport` under `SendTimeout`, completes accepted rows, retries or dead-letters failures per message, and settles on a token host shutdown does not cancel. `MaxAttempts` defaults to 5; set it in the `OutboxDispatcher` section when the envelope says otherwise. The host fails to start unless `LeaseDuration > SendTimeout + SettlementTimeout`.
3. Retain exhausted rows (parked with last error) and give operators a replay (`RetryDeadLetteredAsync`) and a bounded retention job (`PurgeDeadLetteredAsync`).

The test contract is two or more concurrent claimers with no overlapping ownership plus lease-expiry recovery, against every provider; the app proves its mapper and wiring, the package its claim.

### At-Least-Once Consumer: Inbox

Every side-effecting at-least-once consumer derives from `IntegrationEventConsumerBase` over the package inbox (`AddInbox<{Project}DbContextTrxn>()`, `ApplyInboxModel(SchemaName)`; it needs the pooled `IDbContextFactory` because lease renewal runs beside the handler). The claim is a row keyed `(Consumer, MessageId)` with two states: in progress under a lease that the owning delivery renews, then completed after the effect. A delivery that finds it completed settles as `Duplicate` without repeating the effect; a live claim held by another delivery means retry later (`InProgress` after the bounded wait), never success and never a second run; an expired lease is taken over. Failure releases the claim and rethrows so broker retry can run. Broker duplicate detection is an additional optimization, not a substitute.

```csharp
public sealed class {Entity}ProjectionConsumer(
    IInboxStore inbox, I{Entity}ProjectionService projection, MessagingMetrics metrics,
    ILogger<{Entity}ProjectionConsumer> logger, IOptions<InboxClaimOptions>? claimOptions = null)
    : IntegrationEventConsumerBase(inbox, metrics, logger, claimOptions)
{
    public const string Name = "projection";
    public override string ConsumerName => Name;
    public override bool Handles(string eventType) => eventType is nameof({Entity}CreatedEvent);
    protected override Task ConsumeAsync(IntegrationEventEnvelope envelope, CancellationToken ct) =>
        projection.Project{Entity}Async(PayloadGuid(envelope, nameof({Entity}CreatedEvent.{Entity}Id)), ct);
}
```

Claim timings bind from `Messaging:Inbox` (`ClaimLease` 60 s, `RenewalInterval` 20 s, `WaitPollInterval`, `WaitMargin`). Known limits: a handler that never returns renews its claim indefinitely, so bound the handler's own I/O with timeouts; the effect and the completion are atomic only when the effect writes to the inbox database inside a transaction opened before `HandleAsync`, so make any other effect idempotent. A retention job purges completed claims past a window longer than the broker's redelivery horizon.

Replay the same envelope in an integration test and assert exactly one business effect. Scheduler/event jobs that mint messages use deterministic IDs from stable business inputs so a rerun does not create a new logical event.

### Provider Switch and Transport Boundary

When more than one broker is declared, the outbox, envelope, consumers and inbox stay unchanged and only the `IOutboxTransport` registration and the consumer host differ. The resolver follows `environment > config > lane default > hard default`, and an unknown explicit value fails startup. A third-party bus framework is optional: adopt it only when it replaces owned retry/outbox/consumer infrastructure rather than duplicating a proven path.

RabbitMQ consumers normally run in a worker/scheduler host; Service Bus may use a worker or Functions trigger. Selecting one transport disables the competing consumer host so one event is not processed by both.

At the transport boundary, `IntegrationEnvelopeReader.TryRead(body, readerOptions, out envelope, out reason)` parses and validates the envelope before any consumer runs; `readerOptions` carries the app's serializer options and its known-type predicate. Unknown or malformed envelopes are dead-lettered with the reason (`MalformedEnvelope`, `UnsupportedEventType`); they are never acknowledged as successful dispatch. The packaged adapters (`RabbitMqIntegrationEventHandler<TConsumer>`, `ServiceBusIntegrationEventDispatcher`) do this and settle by the consumer's verdict.

Broker confirmation is bounded. The RabbitMQ transport publishes with confirms and fails only unconfirmed indices; the Service Bus transport fails an oversize item alone as permanent. Mark an outbox row complete only after a positive confirmation - the package dispatcher does.

### Broker Trace Context

The envelope carries correlation identifiers, while W3C trace context travels in transport headers. The package transports start the producer span (`send {destination}`) parented on the `traceparent`/`tracestate` persisted with the outbox row, not the dispatcher's own activity, and the consumer adapters start `process {destination}` from the extracted context. Missing or malformed trace context starts a new trace without failing message processing. Export `MessagingActivitySource.Name` and `OutboxActivitySource.Name` ([observability.md](observability.md)) and prove parent continuity for each transport.

### RabbitMQ (default lane: queue/topic workflows)

`EF.Messaging.RabbitMq` owns confirmed publishing, topology declaration, consumer hosting, the outbox transport and the consumer adapter; API list in [../support/ef-packages-optional.md](../support/ef-packages-optional.md) section RabbitMQ (EF.Messaging.RabbitMq). Only the consumer host registers consumers.

```csharp
// Every host that dispatches outbox rows
services.AddRabbitMqMessaging(config, "Messaging:RabbitMq");
services.AddRabbitMqOutboxTransport(o => o.DefaultExchange = {Project}RabbitMqTopology.Exchange);

// Consumer host only (worker/scheduler; Functions has no RabbitMQ trigger)
services.AddRabbitMqTopology({Project}RabbitMqTopology.Build());
services.AddRabbitMqConsumer<RabbitMqIntegrationEventHandler<{Entity}ProjectionConsumer>>({Project}RabbitMqTopology.ProjectionQueue);
services.AddHealthChecks().AddRabbitMqHealthCheck(tags: "ready");
```

The adapter dead-letters an unreadable body, acks consumed and duplicate deliveries, and retries `InProgress` and failures after `RabbitMqConsumerOptions.RetryDelay` (`Messaging:RabbitMq:Consumers:<queue>:RetryBaseDelay` / `RetryMaxDelay`), up to the delivery bound, then dead-letters.

### Service Bus (`Azure` lane: queue/topic workflows)

```csharp
// Every host that dispatches outbox rows
services.AddServiceBusOutboxTransport(o =>
{
    o.ClientName = "{Project}SBClient";
    o.Entities[{Project}IntegrationEvents.Destination] = config["DomainEventsTopic"] ?? "{project}-events";
});
```

Consumers run as Functions Service Bus triggers, one per subscription, each a one-line `ServiceBusIntegrationEventDispatcher.DispatchAsync(message, actions, consumer, readerOptions.Value, logger, ct)` with auto-complete off ([function-app.md](function-app.md)). A non-Functions processor derives from `ServiceBusProcessorBase` and calls the same consumer.

```csharp
public interface IServiceBusSender
{
    Task SendMessageAsync(string queueOrTopicName, string message,
        string? correlationId = null,
        IDictionary<string, object>? metadata = null,
        CancellationToken cancellationToken = default);
}

public class {Project}ServiceBusSender : ServiceBusSenderBase, I{Project}ServiceBusSender { }
public class {Project}ServiceBusProcessor : ServiceBusProcessorBase, I{Project}ServiceBusProcessor { }
```

```csharp
services.AddAzureClients(builder =>
    builder.AddServiceBusClient(config.GetConnectionString("ServiceBus1")!)
        .WithName("{Project}SBClient"));
```

### Event Grid (pub/sub notifications)

```csharp
public interface IEventGridPublisher
{
    Task<int> SendAsync(EventGridEvent egEvent, CancellationToken cancellationToken = default);
}

public class {Project}EventGridPublisher : EventGridPublisherBase, I{Project}EventGridPublisher { }
```

```csharp
services.AddAzureClients(builder =>
    builder.AddEventGridPublisherClient(
        new Uri(config["EventGrid:TopicEndpoint"]!),
        new AzureKeyCredential(config["EventGrid:TopicKey"]!))
    .WithName("{Project}EGClient"));
```

### Event Hub (high-throughput streams)

```csharp
public interface IEventHubProducer
{
    Task SendAsync(string message, string? partitionId = null, string? partitionKey = null,
        string? correlationId = null, IDictionary<string, object>? metadata = null,
        CancellationToken cancellationToken = default);
}

public interface IEventHubProcessor
{
    Task RegisterAndStartEventProcessor(
        Func<ProcessEventArgs, Task> funcProcess,
        Func<ProcessErrorEventArgs, Task> funcError,
        CancellationToken cancellationToken);
}
```

High-ingest guidance:

- document expected throughput profile (`standard|high|burst`)
- choose partitioning based on dominant ordering/read patterns
- define replay window and checkpoint cadence before production rollout

```csharp
services.AddAzureClients(builder =>
{
    builder.AddEventHubProducerClient(config.GetConnectionString("EventHub1")!, "hub-name")
        .WithName("{Project}EHProducer");

    builder.AddEventProcessorClient(
            config.GetConnectionString("EventHub1")!,
            "$Default",
            config.GetConnectionString("BlobStorage1")!,
            "event-hub-checkpoints")
        .WithName("{Project}EHProcessor");
});
```

## Aspire Integration

```csharp
var lane = HostingLaneResolver.Resolve(builder.Configuration);
var api = builder.AddProject<Projects.{Project}_Api>("{project}-api");

if (lane.Messaging == "RabbitMq") // NonAzure lane (default)
{
    var rabbitMq = builder.AddRabbitMQ("rabbitmq").WithManagementPlugin();
    api.WithReference(rabbitMq, connectionName: "RabbitMq1")
       .WithEnvironment("Messaging__RabbitMq__ConnectionString", rabbitMq.Resource.ConnectionStringExpression);
}
else // Azure lane: exactly one broker is declared
{
    var serviceBus = builder.AddAzureServiceBus("ServiceBus1");
    serviceBus.AddQueue("todoitem-processing");
    var eventHub = builder.AddAzureEventHubs("EventHub1").AddHub("telemetry");
    api.WithReference(serviceBus).WithReference(eventHub);
}
```

### Local Inspection

RabbitMQ: `WithManagementPlugin()` serves the management UI from the broker container; no extra tool is needed.

For Service Bus emulator inspection, pin the AMQP port (`5672`) and expose a management endpoint (`5300`) on non-test runs. **Messentra** is the recommended UI (it is an inspector, not an emulator - Aspire still owns the emulator container). Health probe: `http://localhost:5300/health`. SDK clients use `Endpoint=sb://localhost;...;UseDevelopmentEmulator=true;`; administration-client tools use `Endpoint=sb://localhost:5300;...;UseDevelopmentEmulator=true;`.

See [aspire.md](aspire.md) -> *Local Explorer Tooling* for the canonical port matrix and the `RunAsEmulator(...)` pattern.

## Rules

1. One settings class per concrete sender/processor (`*SettingsBase` inheritance).
2. Named Azure clients via `IAzureClientFactory<T>` on Azure arms; RabbitMQ binds one `Messaging:RabbitMq` options section.
3. Background processors create DI scopes for scoped dependencies.
4. Preserve correlation IDs in message metadata.
5. Event Hub processors checkpoint regularly (not every event unless required).
6. Configure retries + dead-letter handling for every broker consumer (RabbitMQ dead-letter exchange, Service Bus DLQ).
7. Keep message contracts versioned and backward-compatible.
8. For webhook/callback-originated events, verify signature/timestamp and deduplicate before publishing domain events.
9. For support/dispute-critical workflows, maintain an immutable timeline projection (append-only event log + query read model).
10. Never acknowledge a failed or malformed message as success. Use the transport retry and dead-letter contract with a reason.
11. Carry W3C trace context across broker hops; correlation IDs alone do not join distributed traces.

## Verification

- [ ] Sender/processor inherit correct base classes
- [ ] Named clients and settings sections are aligned
- [ ] Background processors are registered and startable
- [ ] Batch sending handles message-size constraints
- [ ] Aspire references match connection names used by services
- [ ] Delivery semantics (idempotency/outbox/dedup window) are explicitly configured per channel
- [ ] `outboxEnabled: true` registers `AddOutbox` with the staging interceptor on the write context, `AddOutboxDispatcher` on the dispatcher host, the backlog health check, a retention job, and a replay proof
- [ ] Side-effecting consumers derive from `IntegrationEventConsumerBase` over `AddInbox` and have a duplicate-delivery test
- [ ] Every transport proves the app's topology routing, malformed-message dead-letter, and trace-parent propagation; confirm, nack and timeout handling are the package's tests
- [ ] No app code defines an outbox/inbox store, a transport, an envelope reader, or a consumer base
- [ ] Mixed-store slices include a reconciliation path (drift detection + replay-safe correction)
- [ ] Timeline projection exists for workflows requiring support/dispute traceability
