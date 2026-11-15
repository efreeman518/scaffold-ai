# Test Templates - Integration / Component (Phase 5a, on-demand)

| | |
|---|---|
| **Generates** | `tests/Test.Support/Hosting/TestDatabaseContainer.cs` (shared with other container tiers); under `tests/Test.Integration/`: `Infrastructure/DbContainerFixture.cs` + one fixture per other selected store, `Infrastructure/IntegrationTestSetup.cs`, `{Entity}RepositoryIntegrationTests.cs`. The audit, transport and projection tests of this tier are in [test-templates-integration-pipeline.md](test-templates-integration-pipeline.md) |
| **Requires** | [repository-template](repository-template.md), [updater-template](updater-template.md), EF.IntegrationTesting (`ContainerFixture<T>`), EF.IntegrationTesting.PostgreSql / EF.IntegrationTesting.SqlServer (database fixtures), EF.Testing (`DockerRuntimePreflight`), Testcontainers packages for each other store the app uses |
| **Phase** | Fixtures generated in Phase 4 (component shells); `*RepositoryIntegrationTests` filled in during Phase 5a; the Phase 5b tests are in [test-templates-integration-pipeline.md](test-templates-integration-pipeline.md) |
| **Protocol** | Tests-after for this tier - TDD lives in `Test.Unit` and `Test.Endpoints`. Integration verifies wiring against real infrastructure, so write the tests once the unit + endpoint tests pin behavior. |

> **Token vs interpolation:** in the migration test's `$"Expected >= {ExpectedTableCount} tables in {app} schema, found {tableCount}"`, `{ExpectedTableCount}` and `{app}` are scaffold tokens and `{tableCount}` is a local that stays verbatim ([../ai/placeholder-tokens.md](../ai/placeholder-tokens.md) section Disambiguating Tokens From Logging And Interpolation).

## Why this tier exists

`Test.Endpoints` runs against in-memory EF, which silently masks tenant query filters, owned-type flattening, paging plans, raw SQL projections, M:N bridge tables, polymorphic indexes, and audit interceptor wiring. `Test.Integration` is the **component** tier: it instantiates **one class against one real store** in a **standalone Testcontainer** - no HTTP, no Aspire graph. Use it for:

- EF migration apply against the lane's real database (catches FK ordering / shadow-property / schema drift bugs).
- Tenant query filters, M:N junction navigation (`.ThenInclude`), polymorphic-index existence checks.
- Audit repository round trip against the lane's sink (tenant-first key, sentinel tenant, metadata).
- Outbox row -> RabbitMQ transport -> bound queues (wire shape, topology routing, malformed-body rejection).
- Domain-event projection (`database -> projection service -> view document`) with an in-memory view store.

> **Component vs mesh:** mesh tests live in `Test.Aspire` ([test-templates-aspire.md](test-templates-aspire.md)); placement rule in [../skills/testing.md](../skills/testing.md) section Component vs Mesh split. `Test.Integration` must **not** reference `AppHost` or `Aspire.Hosting.Testing`.

**Naming:** both canonical forms appear in this tier - `Given_{Entity}Created_When_ProjectionRuns_Then_{Entity}ViewProduced` for a behavioral scenario, `Migrations_ApplyCleanlyTwice_WithHistoryInOwnedSchema` for a structural fact (owner: [../skills/testing.md](../skills/testing.md) section Test Naming Convention). The coverage matrix and gate checks reference method names exactly.

## Lane switch

One assembly serves every declared lane: tests resolve the lane with the hosts' `HostingLaneResolver` (`NonAzure` unless `{APP}_LANE=Azure`), start only that lane's stores, and CI runs the assembly once per declared lane. Generate the `Azure` arm (SQL Server, Azurite, Service Bus) only when `hostingLanes` includes `Azure`; it differs only where an **Azure arm** note says. A single-lane test calls `IntegrationTestSetup.RequireLane(lane)` (`Inconclusive` on the other lane). `Test.E2E` and `Test.Aspire` read the same `TestHostingLane`.

## Fixture model

Each store the app uses gets a **standalone Testcontainer fixture** under `tests/Test.Integration/Infrastructure/`. A single `IntegrationTestSetup` runs `DockerRuntimePreflight.GetUnavailableReasonAsync` (EF.Testing), starts the lane's fixtures in parallel from `[AssemblyInitialize]`, and disposes them in `[AssemblyCleanup]`. Every fixture is a package `ContainerFixture<TContainer>` (or the PostgreSQL / SQL Server fixture built on it): one gated start that records a failure in `StartupError` instead of throwing, so discovery continues and each dependent test fails with the full exception. Only the preflight-confirmed unavailable runtime is `Inconclusive`. Generate only the fixtures the app needs, each named for its store and independent of the Aspire host: `DbContainerFixture` always; `RedisContainerFixture` when a distributed cache, limiter, or Redis Data Protection is in scope; `RabbitMqBrokerFixture` when `messagingProvider: RabbitMq`; `SeaweedFsContainerFixture` when `storageProvider: S3`.

> **Cleanup is owned by `DisposeAsync` + the Testcontainers reaper - never hand-sweep Docker.** Each fixture's `DisposeAsync` removes its own container; the Resource Reaper (Ryuk) removes only containers with this run's `org.testcontainers.session-id` label after a crash. A `docker rm`/`docker container prune` sweep also deletes other projects', sessions', and intentional persistent containers.

---

### File: `tests/Test.Support/Hosting/TestDatabaseContainer.cs`

Shared by `DbContainerFixture` and the `Test.E2E` `DbApiFactory`. It adapts the package fixtures to the app's provider switch and options; container lifecycle and empty-database creation are the package's. `ContainerImages` is the one image catalog in the shared hosting project (reviewed tag plus manifest digest per image); AppHost and every fixture read it.

```csharp
using EF.IntegrationTesting.PostgreSql;
using EF.IntegrationTesting.SqlServer;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Configuration;
using {Project}.Hosting;
using {Project}.Infrastructure.Data.Provider;

namespace Test.Support.Hosting;

/// <summary>The lane container-backed tests run on, resolved exactly as the hosts resolve it.</summary>
public static class TestHostingLane
{
    public static HostingLaneSettings Current =>
        HostingLaneResolver.Resolve(new ConfigurationBuilder().AddEnvironmentVariables().Build());

    public static {App}DbProvider DatabaseProvider =>
        Current.Lane == HostingLane.Azure ? {App}DbProvider.SqlServer : {App}DbProvider.PostgreSql;
}

/// <summary>One container for the lane's provider, isolated empty databases, and runtime-matching options.</summary>
public sealed class TestDatabaseContainer({App}DbProvider provider) : IAsyncDisposable
{
    private readonly MsSqlContainerFixture? _sql = provider == {App}DbProvider.SqlServer ? new(ContainerImages.SqlServer) : null;
    private readonly PostgreSqlContainerFixture? _postgres = provider == {App}DbProvider.PostgreSql ? new(ContainerImages.PostgreSql) : null;

    public {App}DbProvider Provider { get; } = provider;
    public string ConnectionString => _sql?.ConnectionString ?? _postgres!.ConnectionString;

    /// <summary>Why the one start attempt failed, or null; recorded by the package fixture, never thrown.</summary>
    public Exception? StartupError => _sql is not null ? _sql.StartupError : _postgres!.StartupError;
    public bool IsStarted => _sql?.IsStarted ?? _postgres!.IsStarted;

    public Task StartAsync(CancellationToken ct = default) => _sql?.StartAsync(ct) ?? _postgres!.StartAsync(ct);
    public ValueTask DisposeAsync() => _sql?.DisposeAsync() ?? _postgres!.DisposeAsync();

    /// <summary>Empty database <c>{prefix}_{guid}</c>; the package validates the prefix (1-30 characters).</summary>
    public Task<string> CreateEmptyDatabaseAsync(string prefix, CancellationToken ct = default) =>
        _sql?.CreateDatabaseAsync(prefix, ct) ?? _postgres!.CreateDatabaseAsync(prefix, ct);

    /// <summary>Interceptors can only be added at options-build time, so observers pass them here.</summary>
    public DbContextOptions<TContext> BuildOptions<TContext>(string? connectionString, params IInterceptor[] extra)
        where TContext : DbContext =>
        new DbContextOptionsBuilder<TContext>()
            .Use{App}Provider(Provider, connectionString ?? ConnectionString) // owns schema + history table
            .AddInterceptors(TestOutbox.Interceptor() /*, the other non-audit interceptors the hosts register */)
            .AddInterceptors(extra)
            .Options;
}
```

`Use{App}Provider` is the central provider-options helper ([../patterns/data-layer-wiring.md](../patterns/data-layer-wiring.md) section Registration), exposed from `Infrastructure.Data` so hosts, migrator, design-time factory, and tests share one schema/history-table rule. `TestOutbox.Interceptor()` (in `Test.Support`) builds the EF.Data.Outbox `OutboxStagingInterceptor` over the app's `IOutboxEventMapper` and `OutboxOptions` exactly as the hosts register them, so container tests exercise the real staging path. Generate provider fixture fields only for the lanes in `hostingLanes`.

### File: `tests/Test.Integration/Infrastructure/DbContainerFixture.cs`

```csharp
using {Project}.Infrastructure.Data;
using Test.Support.Hosting;

namespace Test.Integration.Infrastructure;

/// <summary>
/// Standalone database Testcontainer on the lane's provider, started by <see cref="IntegrationTestSetup"/>;
/// the package fixture records <see cref="StartupError"/> so dependent tests fail with it without aborting discovery.
/// </summary>
internal static class DbContainerFixture
{
    private static readonly TestDatabaseContainer Container = new(TestHostingLane.DatabaseProvider);

    internal static Exception? StartupError => Container.StartupError;
    internal static string ConnectionString => Container.ConnectionString;

    internal static Task StartAsync(CancellationToken ct = default) => Container.StartAsync(ct);
    internal static Task StopAsync() => Container.DisposeAsync().AsTask();

    internal static Task<string> CreateEmptyDatabaseConnectionStringAsync(string prefix) =>
        Container.CreateEmptyDatabaseAsync(prefix);

    // The fail-closed tenant filter reads nothing for a tenant-less context, so component contexts are all-tenants;
    // a test that pins a tenant sets TenantId and clears AllTenants.
    internal static {App}DbContextTrxn CreateTrxnContext(string? connString = null) =>
        new(Container.BuildOptions<{App}DbContextTrxn>(connString)) { AuditId = "integration-test", AllTenants = true };

    internal static {App}DbContextQuery CreateQueryContext(string? connString = null) =>
        new(Container.BuildOptions<{App}DbContextQuery>(connString)) { AuditId = "integration-test", AllTenants = true };
}
```

> **`AuditId` bypass:** `DbContextBase<string, Guid?>` declares `required string AuditId`. When constructing contexts outside DI, set it directly via object-initializer syntax - the design-time factory uses the same pattern. A context that takes an `IRequestContext` instead gets the system context here.

The other store fixtures wrap `ContainerFixture<TContainer>` (EF.IntegrationTesting.Testcontainers) and expose `StartupError`, `StartAsync(ct)`, `StopAsync()` and their connection values:

- **RabbitMQ:** `new ContainerFixture<RabbitMqContainer>(() => new RabbitMqBuilder(ContainerImages.RabbitMq).WithUsername("{app}").WithPassword("{app}-password").Build())` - current images refuse a remote `guest` login, so the container gets its own credentials and clients read them back from `Container.GetConnectionString()` (exposed as `ConnectionString`).
- **Redis:** `RedisContainerFixture` over `new ContainerFixture<RedisContainer>(() => new RedisBuilder(ContainerImages.Redis).Build())`; `Test.E2E` `DbApiFactory` holds its own instance of the same fixture.
- **SeaweedFS (S3):** a `ContainerFixture<IContainer>` over `new ContainerBuilder(ContainerImages.SeaweedFs).WithCommand("mini", "-dir=/data")` with `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` values the fixture also exposes, `WithPortBinding(8333, true)`, and `Wait.ForUnixContainer().UntilInternalTcpPortIsAvailable(8333)`; `ServiceUrl` is `http://{Hostname}:{GetMappedPublicPort(8333)}`.
- **Azure arm:** `AzuriteContainerFixture` over `new AzuriteBuilder(ContainerImages.Azurite).Build()` (the parameterless builder is obsolete), exposing `GetConnectionString()`.

### File: `tests/Test.Integration/Infrastructure/IntegrationTestSetup.cs`

```csharp
namespace Test.Integration.Infrastructure;

using EF.Testing.Processes;
using {Project}.Hosting;
using Test.Support.Hosting;

/// <summary>
/// Assembly-scoped lifecycle for the component tier: starts only the lane's store Testcontainers in parallel.
/// A bounded Docker preflight is the only inconclusive path; captured startup failures remain red.
/// </summary>
[TestClass]
public static class IntegrationTestSetup
{
    private static HostingLane _lane;

    internal static string? DockerUnavailableReason { get; private set; }

    [AssemblyInitialize]
    public static async Task AssemblyInit(TestContext context)
    {
        _lane = TestHostingLane.Current.Lane;
        DockerUnavailableReason = await DockerRuntimePreflight.GetUnavailableReasonAsync(
            TimeSpan.FromSeconds(10),
            context.CancellationToken);
        if (DockerUnavailableReason is not null)
            return;

        // One entry per generated fixture; only the selected lane's branch runs.
        var ct = context.CancellationToken;
        Task[] starts = _lane == HostingLane.Azure
            ? [DbContainerFixture.StartAsync(ct), RedisContainerFixture.StartAsync(ct), AzuriteContainerFixture.StartAsync(ct)]
            : [DbContainerFixture.StartAsync(ct), RedisContainerFixture.StartAsync(ct),
               RabbitMqBrokerFixture.StartAsync(ct), SeaweedFsContainerFixture.StartAsync(ct)];
        await Task.WhenAll(starts);
    }

    [AssemblyCleanup]
    public static async Task AssemblyCleanup(TestContext _)
    {
        if (DockerUnavailableReason is not null)
            return;

        Task[] stops = _lane == HostingLane.Azure
            ? [DbContainerFixture.StopAsync(), RedisContainerFixture.StopAsync(), AzuriteContainerFixture.StopAsync()]
            : [DbContainerFixture.StopAsync(), RedisContainerFixture.StopAsync(),
               RabbitMqBrokerFixture.StopAsync(), SeaweedFsContainerFixture.StopAsync()];
        await Task.WhenAll(stops);
    }

    internal static bool IsUnavailable(Exception? startupError) =>
        DockerUnavailableReason is not null || startupError is not null;

    internal static void AssertAvailable(string resourceName, Exception? startupError)
    {
        if (DockerUnavailableReason is not null)
            Assert.Inconclusive(DockerUnavailableReason);

        if (startupError is not null)
            Assert.Fail($"{resourceName} container startup failed after Docker preflight succeeded:{Environment.NewLine}{startupError}");
    }

    internal static void RequireLane(HostingLane lane)
    {
        if (DockerUnavailableReason is not null)
            Assert.Inconclusive(DockerUnavailableReason);

        if (_lane != lane)
            Assert.Inconclusive($"Test requires {APP}_LANE={lane}; current lane is {_lane}.");
    }
}
```

> Only one `[AssemblyInitialize]`/`[AssemblyCleanup]` per assembly. Add each generated store fixture's `StartAsync`/`StopAsync` to its lane's arrays.

---

## Repository Integration Tests

Cover **migration apply** + **CRUD against the real database** + **child includes** + **updater navigation-add round-trip** (for entities with an `{Entity}Updater`) + **M:N junction navigation** + **tenant query filter** + **polymorphic indexes** when applicable + **paged search projection per searchable aggregate**. Build contexts via `DbContainerFixture` and gate on `StartupError` in `[TestInitialize]`. Every SQL statement stays standard (`INFORMATION_SCHEMA`, quoted identifiers) and every scalar goes through `Convert.ToInt32` - PostgreSQL returns `bigint` for `COUNT(*)` - so one test body runs on both providers.

> **Paged search projection is required at `balanced`+ for every searchable aggregate.** Call the repo's search method (which wraps `QueryPageProjectionAsync`) for a normal `PageIndex=1, PageSize=n` request and assert **both** the page contents **and** `Total`. Only this tier catches swapped `pageSize`/`pageIndex` (near-empty page) or `includeTotal:false` (`Total = -1`); fast-tier fakes return correct-looking results. See the "Call it with named arguments" note in [repository-template.md](repository-template.md).

> **Typed IDs:** entity `Id` is a typed value struct (`{Entity}Id`), so compare it with a raw `Guid` through `.Value` (`Assert.AreEqual(categoryId, result.CategoryId.Value)`, `result.CategoryId?.Value` when nullable) - a direct comparison does not compile. Construct the generic repository pair with the typed ID parameter (`new {App}RepositoryTrxn<Tag, TagId>(db)`); bespoke `{Entity}RepositoryTrxn` repos take none.

> **Seeding a full FK chain:** repository tests seed a bare parent in their own unit of work. A test that
> needs the owner/tenant chain (anything on the write-identity path) uses the shared `DbAggregateSeeder`
> ([test-templates-endpoint.md](test-templates-endpoint.md) section DbAggregateSeeder), never inline
> tenant+user inserts.

### File: `tests/Test.Integration/{Entity}RepositoryIntegrationTests.cs`

```csharp
using EF.Data.Contracts;
using Microsoft.EntityFrameworkCore;
using {Project}.Application.Models;        // {Entity}Dto / {ChildEntity}Dto for the updater round-trip test
using {Project}.Domain.Model;
using {Project}.Infrastructure.Data;
using {Project}.Infrastructure.Repositories;  // {Entity}RepositoryTrxn for the updater round-trip test
using Test.Integration.Infrastructure;
using Test.Support;
using Test.Support.Builders;

namespace Test.Integration;

/// <summary>
/// Validates EF migrations apply cleanly against the lane's real database and that core repository operations
/// (CRUD, includes, many-to-many bridges, the tenant query filter, polymorphic-attachment indexing where
/// applicable) work against the migrated schema.
/// Component tier: instantiates contexts directly against a standalone database Testcontainer via
/// <c>DbContainerFixture</c> (started by <c>IntegrationTestSetup</c>) - no Aspire graph, no HTTP.
/// </summary>
[TestClass]
[TestCategory("Integration")]
public class {Entity}RepositoryIntegrationTests
{
    private static readonly Guid TenantA = TestConstants.TenantId;
    private static readonly Guid TenantB = Guid.Parse("00000000-0000-0000-0000-000000000099");

    // Flow TestContext.CancellationToken everywhere - see ../skills/testing.md Cancellation-Token discipline.
    public TestContext TestContext { get; set; } = null!;

    /// <summary>Classifies Docker unavailability separately from a database startup failure.</summary>
    [TestInitialize]
    public void TestSetup()
    {
        IntegrationTestSetup.AssertAvailable("Database", DbContainerFixture.StartupError);
    }

    [TestMethod]
    [Timeout(120000)]
    public async Task Migrations_ApplyCleanlyTwice_WithHistoryInOwnedSchema()
    {
        var ct = TestContext.CancellationToken;
        await using (var firstRun = DbContainerFixture.CreateTrxnContext())
        {
            await firstRun.Database.MigrateAsync(ct);
        }

        // Fresh context catches unqualified history-table lookup and accidental InitialCreate replay.
        await using var db = DbContainerFixture.CreateTrxnContext();
        await db.Database.MigrateAsync(ct);

        Assert.IsTrue(await db.Database.CanConnectAsync(ct));

        var conn = db.Database.GetDbConnection();
        await conn.OpenAsync(ct);
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = '{app}'";
        var tableCount = Convert.ToInt32(await cmd.ExecuteScalarAsync(ct));
        Assert.IsGreaterThanOrEqualTo(tableCount, {ExpectedTableCount},
            $"Expected >= {ExpectedTableCount} tables in {app} schema, found {tableCount}");

        cmd.CommandText = "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = '{app}' AND TABLE_NAME = '__EFMigrationsHistory'";
        var historyTableCount = Convert.ToInt32(await cmd.ExecuteScalarAsync(ct));
        Assert.AreEqual(1, historyTableCount, "Migration history table must be pinned to the owned schema");
    }

    [TestMethod]
    [Timeout(120000)]
    public async Task {Entity}_CrudOperations_WorkAgainstRealSql()
    {
        var ct = TestContext.CancellationToken;
        await using var db = DbContainerFixture.CreateTrxnContext();
        await db.Database.MigrateAsync(ct);

        // Create
        var entity = new {Entity}Builder().WithName("Integration {Entity}").Build();
        db.{Entities}.Add(entity);
        await db.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins, cancellationToken: ct);
        var id = entity.Id;
        Assert.AreNotEqual(Guid.Empty, id.Value);  // unwrap typed ID for Guid comparison

        // Read - FindAsync takes the tenant-first key array-wrapped, THEN the token (the named-arg form is a compile break).
        var fetched = await db.{Entities}.FindAsync([entity.TenantId, id], ct);
        Assert.IsNotNull(fetched);
        Assert.AreEqual("Integration {Entity}", fetched.Name);

        // Update via domain method
        fetched.Update(name: "Updated {Entity}");
        await db.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins, cancellationToken: ct);
        var updated = await db.{Entities}.FindAsync([entity.TenantId, id], ct);
        Assert.AreEqual("Updated {Entity}", updated!.Name);

        // Delete
        db.{Entities}.Remove(updated);
        await db.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins, cancellationToken: ct);
        var deleted = await db.{Entities}.FindAsync([entity.TenantId, id], ct);
        Assert.IsNull(deleted);
    }

    [TestMethod]
    [Timeout(120000)]
    public async Task Search_WithDuplicateSortKeys_HasStablePageMembership()
    {
        var ct = TestContext.CancellationToken;
        await using var db = DbContainerFixture.CreateTrxnContext();
        await db.Database.MigrateAsync(ct);

        // Seed at least three pages with the same business sort key. Keep the returned IDs.
        var expectedIds = await SeedSearchRowsAsync(db, name: "Same sort key", count: 13, ct);
        await using var queryDb = DbContainerFixture.CreateQueryContext();
        var repo = new {Entity}RepositoryQuery(queryDb);

        var actualIds = new List<Guid>();
        for (var pageIndex = 1; pageIndex <= 3; pageIndex++)
        {
            var page = await repo.Search{Entity}Async(new SearchRequest<{Entity}SearchFilter>
            {
                PageIndex = pageIndex,
                PageSize = 5,
                Sorts = [new Sort(nameof({Entity}.Name), SortOrder.Ascending)],
                Filter = new {Entity}SearchFilter { Name = "Same sort key" }
            }, ct);

            Assert.AreEqual(expectedIds.Count, page.Total);
            actualIds.AddRange(page.Data.Select(item => item.Id!.Value));
        }

        CollectionAssert.AreEquivalent(expectedIds, actualIds);
        Assert.AreEqual(actualIds.Count, actualIds.Distinct().Count());

        var repeatedFirstPage = await repo.Search{Entity}Async(new SearchRequest<{Entity}SearchFilter>
        {
            PageIndex = 1,
            PageSize = 5,
            Sorts = [new Sort(nameof({Entity}.Name), SortOrder.Ascending)],
            Filter = new {Entity}SearchFilter { Name = "Same sort key" }
        }, ct);
        CollectionAssert.AreEqual(
            actualIds.Take(5).ToList(),
            repeatedFirstPage.Data.Select(item => item.Id!.Value).ToList());
    }

    private static async Task<List<Guid>> SeedSearchRowsAsync(
        {Project}DbContextTrxn db,
        string name,
        int count,
        CancellationToken ct)
    {
        var rows = Enumerable.Range(0, count)
            .Select(_ => new {Entity}Builder().WithName(name).Build())
            .ToList();
        db.{Entities}.AddRange(rows);
        await db.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins, cancellationToken: ct);
        return rows.Select(row => row.Id.Value).ToList();
    }

    // The remaining methods in this class follow the same discipline: `var ct = TestContext.CancellationToken;`
    // then flow `ct` into every MigrateAsync / SaveChangesAsync / FindAsync / EF async call and any private helper.

    [TestMethod]
    [Timeout(120000)]
    public async Task {Entity}_WithChildren_PersistsCorrectly()
    {
        await using var db = DbContainerFixture.CreateTrxnContext();
        await db.Database.MigrateAsync();

        var entity = new {Entity}Builder().WithName("Parent {Entity}").Build();
        db.{Entities}.Add(entity);
        await db.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins);

        var childResult = {ChildEntity}.Create(TenantA, entity.Id.Value, "Child body");  // unwrap typed IDs for cross-boundary factory
        db.{ChildEntities}.Add(childResult.Value!);
        await db.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins);

        var loaded = await db.{Entities}
            .Include(e => e.{ChildEntities})
            .FirstOrDefaultAsync(e => e.Id == entity.Id);

        Assert.IsNotNull(loaded);
        Assert.HasCount(1, loaded.{ChildEntities});
    }

    /// <summary>
    /// Regression guard for the <c>ValueGeneratedNever</c> key baseline (GR-16): a real
    /// <c>repo.UpdateFromDto(reloadedParent, dto)</c> round-trip that adds a NEW child to a freshly loaded,
    /// tracked parent - the aggregate-edit path the API uses and the only path that exercises EF's
    /// add-vs-update inference for navigation-added children. Without the baseline the save throws
    /// <c>DbUpdateConcurrencyException</c> (UPDATE against a non-existent row).
    /// </summary>
    [TestMethod]
    [Timeout(120000)]
    public async Task {Entity}_UpdateFromDto_AddsChildToReloadedParent_AgainstRealSql()
    {
        {Entity}Id parentId;  // typed ID - not Guid

        // Seed a bare parent in its own unit of work.
        await using (var seed = DbContainerFixture.CreateTrxnContext())
        {
            await seed.Database.MigrateAsync();
            var seeded = new {Entity}Builder().WithName("Updater Parent").Build();
            seed.{Entities}.Add(seeded);
            await seed.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins);
            parentId = seeded.Id;
        }

        // Reload the persisted parent (tracked, children included) in a fresh context - the handler/service path.
        await using var db = DbContainerFixture.CreateTrxnContext();
        var loaded = await db.{Entities}
            .Include(e => e.{ChildEntities})
            .FirstAsync(e => e.Id == parentId);

        // Desired-state DTO with a NEW child (no Id -> create path); DTOs carry Guid, so unwrap with .Value.
        var dto = new {Entity}Dto
        {
            Id = parentId.Value,
            Name = "Updater Parent",
            {ChildEntities} = [new {ChildEntity}Dto { /* required fields */ {Entity}Id = parentId.Value }]
        };

        var repo = new {Entity}RepositoryTrxn(db);
        var sync = repo.UpdateFromDto(loaded, dto, RelatedDeleteBehavior.RelationshipAndEntity);
        Assert.IsTrue(sync.IsSuccess, $"UpdateFromDto failed: {sync.ErrorMessage}");

        // Inserts the navigation-added child. Throws here if the ValueGeneratedNever baseline is missing.
        await db.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins);

        // Confirm the child persisted via a clean reload.
        await using var verify = DbContainerFixture.CreateTrxnContext();
        var reloaded = await verify.{Entities}
            .Include(e => e.{ChildEntities})
            .FirstAsync(e => e.Id == parentId);
        Assert.HasCount(1, reloaded.{ChildEntities});
    }

    [TestMethod]
    [Timeout(120000)]
    public async Task {Entity}Tag_ManyToMany_WorksCorrectly()
    {
        // Only generate when entity participates in an M:N relationship via a junction entity.
        await using var db = DbContainerFixture.CreateTrxnContext();
        await db.Database.MigrateAsync();

        var entity = new {Entity}Builder().WithName("Tagged").Build();
        db.{Entities}.Add(entity);
        var tag = new TagBuilder().WithName("M2MTag").Build();
        db.Tags.Add(tag);
        await db.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins);

        var bridge = {Entity}Tag.Create(TenantA, entity.Id.Value, tag.Id.Value);  // unwrap typed IDs for cross-boundary factory
        db.{Entity}Tags.Add(bridge.Value!);
        await db.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins);

        var loaded = await db.{Entities}
            .Include(e => e.{Entity}Tags).ThenInclude(et => et.Tag)
            .FirstOrDefaultAsync(e => e.Id == entity.Id);

        Assert.IsNotNull(loaded);
        Assert.HasCount(1, loaded.{Entity}Tags);
        Assert.AreEqual("M2MTag", loaded.{Entity}Tags.First().Tag!.Name);
    }

    [TestMethod]
    [Timeout(120000)]
    public async Task TenantQueryFilter_PinsTheTenant_AndFailsClosedWithoutOne()
    {
        // Only generate when enableMultiTenant is true.
        var ct = TestContext.CancellationToken;
        var marker = $"tenant-filter-{Guid.NewGuid():N}";
        await using (var seed = DbContainerFixture.CreateTrxnContext())
        {
            await seed.Database.MigrateAsync(ct);
            seed.{Entities}.Add(new {Entity}Builder().WithTenantId(TenantA).WithName(marker).Build());
            seed.{Entities}.Add(new {Entity}Builder().WithTenantId(TenantB).WithName(marker).Build());
            await seed.SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct);
        }

        await using var pinned = DbContainerFixture.CreateQueryContext();
        pinned.AllTenants = false;
        pinned.TenantId = TenantA;
        Assert.AreEqual(1, await pinned.{Entities}.CountAsync(e => e.Name == marker, ct), "a pinned tenant reads only its rows");

        await using var tenantless = DbContainerFixture.CreateQueryContext();
        tenantless.AllTenants = false;
        Assert.AreEqual(0, await tenantless.{Entities}.CountAsync(e => e.Name == marker, ct),
            "a context with no tenant and no all-tenants decision reads nothing");
    }
}
```

### Repository test coverage matrix

| Scenario | Generate when |
|---|---|
| `Migrations_ApplyCleanlyTwice_WithHistoryInOwnedSchema` | Always - once per schema, not per entity. |
| `Search_WithDuplicateSortKeys_HasStablePageMembership` | Every repository with paging. Seed more than one page with the same business sort key and assert exact IDs, no omissions, and no duplicates. |
| `{Entity}_CrudOperations_WorkAgainstRealSql` | Every entity with mutations. |
| `{Entity}_WithChildren_PersistsCorrectly` | Entity has owned/dependent child collections (1:N). Persistence + includes only - seeds children via `db.{ChildEntities}.Add(...)`, so it does NOT exercise the updater/navigation-add path (see next row). |
| `{Entity}_UpdateFromDto_AddsChildToReloadedParent_AgainstRealSql` | Entity has owned/dependent child collections (1:N) **and** an `{Entity}Updater`. Required regression guard for the `ValueGeneratedNever` key baseline (GR-16) - the only test that adds a NEW child through `repo.UpdateFromDto` against the real database. `{Entity}_WithChildren_PersistsCorrectly` does not substitute. |
| `{Entity}Tag_ManyToMany_WorksCorrectly` | Entity participates in M:N via a junction. |
| `TenantQueryFilter_PinsTheTenant_AndFailsClosedWithoutOne` | `enableMultiTenant: true`. |
| `Polymorphic_Index_Exists` | Entity uses a polymorphic ownership pattern (e.g., `Attachment.OwnerType` + `OwnerId`). |

---

## Project file

### File: `tests/Test.Integration/Test.Integration.csproj`

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <IsTestProject>true</IsTestProject>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="MSTest" />
    <PackageReference Include="EF.IntegrationTesting" />
    <PackageReference Include="Testcontainers" />
    <PackageReference Include="Testcontainers.RabbitMq" />
    <PackageReference Include="RabbitMQ.Client" />
  </ItemGroup>
  <ItemGroup>
    <Using Include="Microsoft.VisualStudio.TestTools.UnitTesting" />
  </ItemGroup>
  <ItemGroup>
    <ProjectReference Include="..\Test.Support\Test.Support.csproj" />
    <ProjectReference Include="..\..\src\Shared\{Project}.Hosting\{Project}.Hosting.csproj" />
    <ProjectReference Include="..\..\src\Application\{Project}.Application.Contracts\{Project}.Application.Contracts.csproj" />
    <ProjectReference Include="..\..\src\Application\{Project}.Application.Services\{Project}.Application.Services.csproj" />
    <ProjectReference Include="..\..\src\Infrastructure\{Project}.Infrastructure.Data\{Project}.Infrastructure.Data.csproj" />
    <ProjectReference Include="..\..\src\Infrastructure\{Project}.Infrastructure.Repositories\{Project}.Infrastructure.Repositories.csproj" />
    <ProjectReference Include="..\..\src\Infrastructure\{Project}.Infrastructure.Messaging.RabbitMq\{Project}.Infrastructure.Messaging.RabbitMq.csproj" />
  </ItemGroup>
</Project>
```

> `Test.Support` carries EF.IntegrationTesting.PostgreSql / EF.IntegrationTesting.SqlServer (the database fixtures) and `Testcontainers.Redis`. Add `AWSSDK.S3` for an object-storage test. **Azure arm:** add `Testcontainers.Azurite`, `Azure.Data.Tables`, and the `Infrastructure.Storage` reference.

---

## Verification

- [ ] `Test.Integration` references **no** `AppHost` and **no** `Aspire.Hosting.Testing`; tests instantiate the class under test against a fixture connection string.
- [ ] One `IntegrationTestSetup` owns the package Docker preflight plus the sole `[AssemblyInitialize]`/`[AssemblyCleanup]` and starts only the resolved lane's fixtures; every fixture is a package `ContainerFixture` and reports `StartupError`.
- [ ] Failed Docker preflight is `Inconclusive`; a post-preflight startup failure fails with the full exception; a single-lane test calls `RequireLane`.
- [ ] Contexts come from `TestDatabaseContainer.BuildOptions` (central provider helper), never a hand-written `UseNpgsql`/`UseSqlServer` call.
- [ ] `Migrations_ApplyCleanlyTwice_WithHistoryInOwnedSchema` exists exactly once per assembly (not per entity).
- [ ] Tenant query filter test exists when `enableMultiTenant: true`; M:N test exists when entity uses a junction.
- [ ] Every test class has a class-level `<summary>` declaring tier (component) + store.
- [ ] No fixture or test performs a manual `docker rm`/`docker container prune` sweep.

---

**TaskFlow proof (local):**
- `../scaffold-proof/tests/Test.Support/Hosting/TestDatabaseContainer.cs`
- `../scaffold-proof/tests/Test.Integration/Infrastructure/DbContainerFixture.cs`
- `../scaffold-proof/tests/Test.Integration/Infrastructure/RabbitMqBrokerFixture.cs`
- `../scaffold-proof/tests/Test.Integration/Infrastructure/IntegrationTestSetup.cs`
- `../scaffold-proof/tests/Test.Integration/MigrationAndRepositoryTests.cs`

**TaskFlow proof (remote fallback):**
<https://github.com/efreeman518/scaffold-proof/tree/main/tests/Test.Integration>
