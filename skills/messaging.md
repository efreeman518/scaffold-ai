# Messaging

Base types (`IServiceBusSender`, `IEventGridPublisher`, `IEventHubProducer`) come from the `EF.Messaging` package - see [package-dependencies.md](package-dependencies.md) and the [EF.Packages repo](https://github.com/efreeman518/EF.Packages) for full API details.

## Prerequisites

- [package-dependencies.md](package-dependencies.md)
- [bootstrapper.md](bootstrapper.md)
- [configuration-secrets.md](configuration-secrets.md)
- [background-services.md](background-services.md)

Rule: use `IInternalMessageBus` for in-process events; use this skill for cross-service messaging.

### Event Boundary Rule

Cross-process bus payloads are application/integration contracts, not domain artifacts.

- Place externally published event records in `Application.Contracts.Events`.
- Use `IIntegrationEventPublisher` for Service Bus / Event Grid.
- Keep domain events in `Domain` only when raised from aggregate invariants and handled in-process before integration mapping.
- Do not publish `Domain` namespace events directly over transport - map to an `Application.Contracts.Events` record at the boundary.

> **Shared infrastructure pattern:** Messaging follows the same **Settings -> Named client -> DI -> Resilience** integration chain as external APIs. See [external-api.md](external-api.md) for the general pattern with Refit/resilience pipeline. This file covers messaging-specific adapters.

## Service Selection

| Need | Service |
|---|---|
| Reliable queue/topic workflows, retries, DLQ | Service Bus |
| Portable queue/topic workflows and self-managed broker | RabbitMQ |
| Event notifications and pub/sub routing | Event Grid |
| High-throughput telemetry/event streams | Event Hub |

## Core Pattern

Implement messaging as provider-specific adapters with shared conventions:

- settings class per concrete sender/processor
- one provider-neutral transport port plus one registration branch per provider
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

1. Map domain events to a versioned integration envelope at the application boundary.
2. Insert the envelope into an outbox table in the same `SaveChanges` transaction as the aggregate mutation. A `SaveChangesInterceptor` is the normal common path; non-tracked bulk operations stage explicitly in the same transaction.
3. Claim a bounded batch with a unique lease token, owner, expiry, availability time, and attempt count. Read back only rows carrying that token. Never use a claim timestamp as identity because provider precision differs.
4. Publish through a provider-neutral transport. Mark complete only after broker confirmation. A failure remains retryable and visible; never catch and discard it.
5. Retain exhausted rows with last error and dead-letter time. Provide an observable replay operation and a bounded retention job.

Provider-specific atomic claim SQL such as SQL Server `READPAST` or PostgreSQL `SKIP LOCKED` is an optimization after the provider-neutral conditional-lease path has contention evidence. The test contract is two or more concurrent claimers with no overlapping ownership plus lease-expiry recovery.

### At-Least-Once Consumer: Inbox

Every side-effecting at-least-once consumer needs an idempotency boundary. Use an inbox key such as `(Consumer, MessageId)` and claim it inside the consumer's unit of work. The business mutation and inbox completion commit together; failure releases or rolls back the claim so broker retry can run. Broker duplicate detection is an additional optimization, not a substitute, because not every transport provides it.

Replay the same envelope in an integration test and assert exactly one business effect. Scheduler/event jobs that mint messages use deterministic IDs from stable business inputs so a rerun does not create a new logical event.

### Provider Switch and Transport Boundary

When more than one broker is declared, keep the outbox, envelope, consumer, and inbox unchanged behind a small transport port such as `SendBatchAsync(destination, messages, ct)`. The resolver follows `environment > config > lane default > hard default`, and an unknown explicit value fails startup. A third-party bus framework is optional: adopt it only when it replaces owned retry/outbox/consumer infrastructure rather than duplicating a proven path.

RabbitMQ consumers normally run in a worker/scheduler host; Service Bus may use a worker or Functions trigger. Selecting one transport disables the competing consumer host so one event is not processed by both.

At the transport boundary, parse and validate envelope type, version, message identity, and required routing metadata before resolving a handler. Unknown or malformed envelopes follow the explicit retry/dead-letter policy with a diagnostic reason; they are never acknowledged as successful dispatch.

Broker confirmation is bounded. For RabbitMQ, enable publisher confirms, publish with mandatory routing when unroutable messages are failures, and wait under a configured timeout linked to caller cancellation. Distinguish caller cancellation, confirm timeout, broker nack/channel failure, and unroutable delivery in logs and retry state. Mark an outbox row complete only after a positive confirmation.

### Broker Trace Context

The envelope carries correlation identifiers, while W3C trace context travels in transport headers. On publish, start a Producer activity and inject `traceparent`/`tracestate`. On consume, extract them and start a Consumer activity with the extracted parent. Missing or malformed trace context starts a new trace without failing message processing. Prove parent continuity for each transport adapter.

### Service Bus (queue/topic workflows)

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

services.Configure<{Project}ServiceBusSenderSettings>(config.GetSection("{Project}ServiceBusSenderSettings"));
services.Configure<{Project}ServiceBusProcessorSettings>(config.GetSection("{Project}ServiceBusProcessorSettings"));
```

```csharp
sbProcessor.RegisterProcessor("todoitem-processing", null,
    async args =>
    {
        using var scope = serviceProvider.CreateScope();
        var svc = scope.ServiceProvider.GetRequiredService<ITodoItemService>();
        var payload = JsonSerializer.Deserialize<TodoItemCompletedMessage>(args.Message.Body.ToString());
        await svc.ProcessCompletionAsync(payload!.TodoItemId, stoppingToken);
    },
    args => { logger.LogError(args.Exception, "Service Bus error on {EntityPath}", args.EntityPath); return Task.CompletedTask; });
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
var serviceBus = builder.AddAzureServiceBus("ServiceBus1");
serviceBus.AddQueue("todoitem-processing");

var eventHub = builder.AddAzureEventHubs("EventHub1").AddHub("telemetry");

builder.AddProject<Projects.{Project}_Api>("{project}-api")
    .WithReference(serviceBus)
    .WithReference(eventHub);
```

### Local Inspection

For Service Bus emulator inspection, pin the AMQP port (`5672`) and expose a management endpoint (`5300`) on non-test runs. **Messentra** is the recommended UI (it is an inspector, not an emulator - Aspire still owns the emulator container). Health probe: `http://localhost:5300/health`. SDK clients use `Endpoint=sb://localhost;...;UseDevelopmentEmulator=true;`; administration-client tools use `Endpoint=sb://localhost:5300;...;UseDevelopmentEmulator=true;`.

See [aspire.md](aspire.md) -> *Local Explorer Tooling* for the canonical port matrix and the `RunAsEmulator(...)` pattern.

## Rules

1. One settings class per concrete sender/processor (`*SettingsBase` inheritance).
2. Named Azure clients via `IAzureClientFactory<T>`.
3. Background processors create DI scopes for scoped dependencies.
4. Preserve correlation IDs in message metadata.
5. Event Hub processors checkpoint regularly (not every event unless required).
6. Configure retries + dead-letter handling for Service Bus consumers.
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
- [ ] `outboxEnabled: true` has a same-transaction outbox row, bounded lease dispatcher, retained failure state, and replay proof
- [ ] Side-effecting consumers have an inbox or equivalent atomic idempotency claim and duplicate-delivery test
- [ ] Every transport proves confirm/ack, retry, malformed-message dead-letter, and trace-parent propagation
- [ ] RabbitMQ proves bounded positive confirm, nack/unroutable failure, confirm timeout, and caller cancellation independently
- [ ] Mixed-store slices include a reconciliation path (drift detection + replay-safe correction)
- [ ] Timeline projection exists for workflows requiring support/dispute traceability
