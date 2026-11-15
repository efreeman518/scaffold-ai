# Test Templates - Integration / Component: audit, transport and projection (Phase 5b, on-demand)

| | |
|---|---|
| **Generates** | under `tests/Test.Integration/`: `RelationalAuditLogRepositoryTests.cs`, `RabbitMqTransportTests.cs`, `DomainEventPipelineTests.cs` |
| **Requires** | [test-templates-integration.md](test-templates-integration.md): the tier's rules (sections Why this tier exists and Lane switch) and the fixtures, `IntegrationTestSetup` and project file these tests run on, generated in Phase 4 and Phase 5a |
| **Phase** | Phase 5b |
| **Protocol** | Tests-after, as the rest of the tier |

The component tier's Phase 5b tests: one class against one real store in a standalone Testcontainer, on the fixtures the base template generates. An **Azure arm** note marks where the `Azure` lane differs.

---

## Audit Repository Test

Generate for `auditProvider: Relational`.

### File: `tests/Test.Integration/RelationalAuditLogRepositoryTests.cs`

```csharp
using EF.Audit.Contracts;
using EF.Audit.Data;
using EF.Common.Contracts;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using {Project}.Hosting;
using {Project}.Infrastructure.Data;
using Test.Integration.Infrastructure;

namespace Test.Integration;

/// <summary>
/// Validates the EF.Audit.Data RelationalAuditLogRepository over the app's own context and migrated AuditLog table:
/// tenant-first key, sentinel tenant for a null tenant, field round trip. Component tier; each test migrates its own
/// empty database so audit rows never mix with another class's.
/// </summary>
[TestClass]
[TestCategory("Integration")]
public class RelationalAuditLogRepositoryTests
{
    private const string SystemTenantId = "_system";

    public TestContext TestContext { get; set; } = null!;

    [TestInitialize]
    public void TestSetup()
    {
        IntegrationTestSetup.RequireLane(HostingLane.NonAzure);
        IntegrationTestSetup.AssertAvailable("Database", DbContainerFixture.StartupError);
    }

    [TestMethod]
    [Timeout(300000, CooperativeCancellation = true)]
    public async Task Append_PersistsEveryAuditField_WithTenantFirstKeyAndSentinelTenant()
    {
        var ct = TestContext.CancellationToken;
        var connString = await DbContainerFixture.CreateEmptyDatabaseConnectionStringAsync("auditrel");
        await using (var migrate = DbContainerFixture.CreateTrxnContext(connString))
            await migrate.Database.MigrateAsync(ct);

        var tenantId = Guid.NewGuid();
        var entry = new AuditEntry<string, Guid>
        {
            Id = Guid.CreateVersion7(), AuditId = "integration-user", TenantId = tenantId,
            EntityType = "{Entity}", EntityKey = Guid.NewGuid().ToString(), StartedAtUtc = DateTimeOffset.UtcNow,
            Status = AuditStatus.Success, Action = "Create", Metadata = "{\"source\":\"relational-test\"}"
        };
        var systemEntry = new AuditEntry<string, Guid?>
        {
            Id = Guid.CreateVersion7(), AuditId = "system", TenantId = null,
            EntityType = "Retention", EntityKey = "sweep", Status = AuditStatus.Success, Action = "Purge"
        };

        await using (var db = DbContainerFixture.CreateTrxnContext(connString))
        {
            var repository = new RelationalAuditLogRepository<{App}DbContextTrxn>(db,
                Options.Create(new RelationalAuditLogSettings { Audit = new AuditSettings { SystemTenantId = SystemTenantId } }));
            await repository.AppendAsync(entry, ct);
            await repository.AppendAsync(systemEntry, ct);
        }

        await using var verify = DbContainerFixture.CreateQueryContext(connString);
        var persisted = await verify.AuditLog.AsNoTracking().SingleAsync(e => e.Id == entry.Id, ct);
        Assert.AreEqual(tenantId.ToString(), persisted.TenantId, "tenant-first key: one tenant's trail is a range scan");
        Assert.AreEqual(entry.AuditId, persisted.AuditId);
        Assert.AreEqual(entry.Status.ToString(), persisted.Status);
        Assert.AreEqual(entry.StartedAtUtc, persisted.StartedAtUtc);
        Assert.AreEqual(entry.Metadata, persisted.Metadata);  // assert every mapped field the sink stores

        var system = await verify.AuditLog.AsNoTracking().SingleAsync(e => e.Id == systemEntry.Id, ct);
        Assert.AreEqual(SystemTenantId, system.TenantId, "a null tenant is stored under the sentinel");
    }
}
```

When the app runs a retention sweep, assert `PurgeOlderThanAsync` with a cutoff before the rows (nothing removed) and after them (every row removed); the package owns the batching test. `RecordedUtc` derives from the UUIDv7 entry id, so seed ids from the clock the assertion uses.

> **Azure arm:** the Azure Table backend is `AzureTableAuditLogRepository` (EF.Audit.AzureTable), whose own tests cover its key shape; the app proves its wiring in the mesh (`ApiAuditPipelineTests`).

The **API audit pipeline over HTTP** is a mesh test - see [test-templates-aspire.md](test-templates-aspire.md).

---

## RabbitMQ Transport Test

Generate when `messagingProvider: RabbitMq`. Proves the app's half of the provider - its topology and its `AddRabbitMqOutboxTransport` registration; the package's tests cover confirms, prefetch, and dead-lettering. Duplicate-delivery proof is the inbox test owned by [../skills/messaging.md](../skills/messaging.md) section At-Least-Once Consumer: Inbox. Staging and topology member names follow the reference app - read the generated members before binding (GR-18).

### File: `tests/Test.Integration/RabbitMqTransportTests.cs`

```csharp
using EF.Messaging;
using EF.Messaging.Outbox;
using EF.Messaging.RabbitMq;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using RabbitMQ.Client;
using {Project}.Application.Contracts.Messaging;
using {Project}.Hosting;
using {Project}.Infrastructure.Messaging.RabbitMq;
using Test.Integration.Infrastructure;
using Test.Support;

namespace Test.Integration;

/// <summary>
/// Validates the app's RabbitMQ registration and {Project}RabbitMqTopology against a real broker: an outbox item
/// sent through the package transport reaches every bound queue in the shape consumers read back.
/// Component tier: one RabbitMQ Testcontainer.
/// </summary>
[TestClass]
[TestCategory("Integration")]
[DoNotParallelize]
public sealed class RabbitMqTransportTests
{
    public TestContext TestContext { get; set; } = null!;

    [TestInitialize]
    public void TestSetup()
    {
        IntegrationTestSetup.RequireLane(HostingLane.NonAzure);
        IntegrationTestSetup.AssertAvailable("RabbitMQ", RabbitMqBrokerFixture.StartupError);
    }

    [TestMethod]
    [Timeout(300000, CooperativeCancellation = true)]
    public async Task PublishedOutboxRow_ArrivesOnEveryBoundQueue_AndReadsBackAsItsEnvelope()
    {
        var ct = TestContext.CancellationToken;
        await using var provider = await BuildProviderAsync($"transport-{Guid.NewGuid():N}", ct);

        var envelope = {Project}IntegrationEvents.Envelope(
            new {Entity}CreatedEvent(Guid.CreateVersion7(), TestConstants.TenantId, "over rabbit"),
            DateTimeOffset.UtcNow, correlationId: "corr-1");
        // The app mapper's entry, so the test sends exactly what SaveChanges stages.
        var entry = {Project}IntegrationEvents.Entry(envelope, TestConstants.TenantId);

        var sent = await provider.GetRequiredService<IOutboxTransport>().SendAsync(entry.Destination, [Item(entry)], ct);
        Assert.IsEmpty(sent.Failures, "a confirmed publish reports no failed message");

        foreach (var queue in new[] { {Project}RabbitMqTopology.ProjectionQueue /*, every queue bound to this event */ })
        {
            var delivered = await GetAsync(queue, ct);
            Assert.IsNotNull(delivered, $"nothing arrived on {queue}");
            Assert.AreEqual(envelope.Id.ToString(), delivered.BasicProperties.MessageId);
            Assert.AreEqual("corr-1", delivered.BasicProperties.CorrelationId);
            Assert.AreEqual(nameof({Entity}CreatedEvent), delivered.RoutingKey);
            Assert.IsTrue(IntegrationEnvelopeReader.TryRead(delivered.Body.Span, ReaderOptions(), out var read, out _));
            Assert.AreEqual(envelope.Id, read!.Id);
        }
    }

    /// <summary>The broker-neutral item the dispatcher hands the transport for a staged entry.</summary>
    private static OutboxItem Item(OutboxEntry entry) => new(
        entry.Envelope.Id, entry.Envelope.Type, entry.Envelope.Version,
        EnvelopeSerializer.Serialize(entry.Envelope, {Project}MessagingJsonContext.Default.Options),
        entry.Envelope.CorrelationId, TraceParent: null, TraceState: null, entry.Headers);

    private static IntegrationEnvelopeReaderOptions ReaderOptions()
    {
        var options = new IntegrationEnvelopeReaderOptions();
        {Project}IntegrationEvents.ConfigureReader(options);
        return options;
    }

    /// <summary>The host registration (messaging.md section RabbitMQ) against the broker, with topology declared.</summary>
    private static async Task<ServiceProvider> BuildProviderAsync(string clientName, CancellationToken ct)
    {
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["Messaging:RabbitMq:ConnectionString"] = RabbitMqBrokerFixture.ConnectionString,
            ["Messaging:RabbitMq:ClientProvidedName"] = clientName
        }).Build();

        var services = new ServiceCollection().AddLogging();
        services.Add{Project}RabbitMqMessaging(config);   // AddRabbitMqMessaging + AddRabbitMqOutboxTransport
        var provider = services.BuildServiceProvider();
        await provider.GetRequiredService<IRabbitMqTopologyDeclarer>().DeclareAsync({Project}RabbitMqTopology.Build(), ct);
        return provider;
    }

    /// <summary>Polls briefly. After a confirmed publish an absence check needs one read (attempts: 1): the broker confirms a routable message only after every queue it routes to has accepted it.</summary>
    private static async Task<BasicGetResult?> GetAsync(string queue, CancellationToken ct, int attempts = 40)
    {
        var factory = new ConnectionFactory { Uri = new Uri(RabbitMqBrokerFixture.ConnectionString) };
        await using var connection = await factory.CreateConnectionAsync(ct);
        await using var channel = await connection.CreateChannelAsync(cancellationToken: ct);
        for (var attempt = 0; attempt < attempts; attempt++)
        {
            if (await channel.BasicGetAsync(queue, autoAck: true, ct) is { } result) return result;
            if (attempt + 1 < attempts) await Task.Delay(100, ct);
        }
        return null;
    }
}
```

Add, in the same class: `MalformedBody_FailsEnvelopeParsing_BeforeAnyConsumerRuns` (purge the queue, publish a non-envelope body through `IRabbitMqPublisher` with a bound routing key, assert the delivery fails `IntegrationEnvelopeReader.TryRead(body, readerOptions, out _, out var failure)` with its malformed reason); one routing assertion per consumer filter (an event bound to one queue reaches no other: after `Assert.IsEmpty(sent.Failures, ...)`, assert `GetAsync(otherQueue, ct, attempts: 1)` is null); one test per optional binding published through the same exchange.

> **Azure arm:** Service Bus has no component-tier broker test; its transport is proven in the mesh (`OutboxMeshTests`, [test-templates-aspire.md](test-templates-aspire.md)).

---

## Domain Event Projection Pipeline

### File: `tests/Test.Integration/DomainEventPipelineTests.cs`

```csharp
using System.Text.Json;
using EF.Data.Contracts;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using {Project}.Application.Contracts.Repositories;
using {Project}.Application.Contracts.Storage;
using {Project}.Application.Services;
using {Project}.Domain.Model;
using {Project}.Infrastructure.Data;
using {Project}.Infrastructure.Repositories;
using Test.Integration.Infrastructure;

namespace Test.Integration;

/// <summary>
/// Validates the domain-event projection pipeline: an entity persisted to the database is read by the
/// projection service through the query-side repositories and emitted as a view document.
/// Component tier: only the database via <c>DbContainerFixture</c>; the broker -> consumer -> projection hop
/// is the mesh tier's. The view store is in-memory - the lane's read-model store has its own component test.
/// </summary>
[TestClass]
public class DomainEventPipelineTests
{
    private static readonly Guid TenantId = Guid.Parse("11111111-1111-1111-1111-111111111111");

    // Coexists with the static ClassInitialize parameter - see ../skills/testing.md Cancellation-Token discipline.
    public TestContext TestContext { get; set; } = null!;

    [ClassInitialize]
    public static async Task ClassInit(TestContext context)
    {
        if (IntegrationTestSetup.IsUnavailable(DbContainerFixture.StartupError))
            return;
        await using var db = DbContainerFixture.CreateTrxnContext();
        await db.Database.MigrateAsync(context.CancellationToken);
    }

    /// <summary>Classifies Docker unavailability separately from a database startup failure.</summary>
    [TestInitialize]
    public void TestSetup()
    {
        IntegrationTestSetup.AssertAvailable("Database", DbContainerFixture.StartupError);
    }

    [TestMethod]
    [TestCategory("Integration")]
    [Timeout(120000)]
    public async Task Given_{Entity}Created_When_ProjectionRuns_Then_{Entity}ViewProduced()
    {
        var connStr = DbContainerFixture.ConnectionString;
        await using var ctx = DbContainerFixture.CreateTrxnContext(connStr);

        var entityResult = {Entity}.Create(TenantId, "Integration Test {Entity}");
        Assert.IsTrue(entityResult.IsSuccess);
        var entity = entityResult.Value!;
        ctx.{Entities}.Add(entity);
        await ctx.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins);

        await using var queryCtx = DbContainerFixture.CreateQueryContext(connStr);
        var viewRepo = new InMemory{Entity}ViewRepository();
        var projectionService = new {Entity}ViewProjectionService(
            new {Entity}RepositoryQuery(queryCtx),
            viewRepo,
            NullLogger<{Entity}ViewProjectionService>.Instance);

        await projectionService.Project{Entity}Async(entity.Id);

        var view = await viewRepo.GetAsync(entity.Id.ToString(), TenantId.ToString());
        Assert.IsNotNull(view, "View should be created by projection");
        Assert.AreEqual("Integration Test {Entity}", view.Name);
    }
}
```

`InMemory{Entity}ViewRepository` (same file, `internal`) implements `I{Entity}ViewRepository` over a `Dictionary<string, {Entity}ViewDto>` keyed `$"{tenantId}:{id}"`; members the test never calls complete without effect.

Skip this template when the project does not have a projection service / read-model store. Generate only when `.scaffold/resource-implementation.yaml` declares a projection/read-model boundary.

---

## Verification

- [ ] Every check in the Verification list of [test-templates-integration.md](test-templates-integration.md) holds for these classes too: fixture connection strings only, `StartupError` gated, a class-level `<summary>` declaring tier (component) + store.
- [ ] `RelationalAuditLogRepositoryTests` exists when `auditProvider: Relational`; `RabbitMqTransportTests` when `messagingProvider: RabbitMq`; `DomainEventPipelineTests` only when `.scaffold/resource-implementation.yaml` declares a projection/read-model boundary.

---

**TaskFlow proof (local):**
- `../scaffold-proof/tests/Test.Integration/RelationalAuditLogRepositoryTests.cs`
- `../scaffold-proof/tests/Test.Integration/RabbitMqTransportTests.cs`
- `../scaffold-proof/tests/Test.Integration/DomainEventPipelineTests.cs`

**TaskFlow proof (remote fallback):**
<https://github.com/efreeman518/scaffold-proof/tree/main/tests/Test.Integration>
