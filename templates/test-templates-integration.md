# Test Templates - Integration / Component (Phase 5a/5b, on-demand)

| | |
|---|---|
| **Generates** | `tests/Test.Support/Hosting/DockerRuntimePreflight.cs` + `TestDatabaseContainer.cs` (shared with other container tiers); under `tests/Test.Integration/`: `Infrastructure/DbContainerFixture.cs` + one fixture per other selected store, `Infrastructure/IntegrationTestSetup.cs`, `{Entity}RepositoryIntegrationTests.cs`, `RelationalAuditLogRepositoryTests.cs`, `RabbitMqTransportTests.cs`, `DomainEventPipelineTests.cs` |
| **Requires** | [repository-template](repository-template.md), [updater-template](updater-template.md), `EF.IntegrationTesting` (database container fixtures), Testcontainers packages for each other store the app uses |
| **Phase** | Fixtures generated in Phase 4 (component shells); tests filled in during Phase 5a (`*RepositoryIntegrationTests`) and Phase 5b (audit, transport, and projection tests) |
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

**Naming:** both canonical forms appear here - `Given_{Entity}Created_When_ProjectionRuns_Then_{Entity}ViewProduced` for a behavioral scenario, `Migrations_ApplyCleanlyTwice_WithHistoryInOwnedSchema` for a structural fact (owner: [../skills/testing.md](../skills/testing.md) section Test Naming Convention). The coverage matrix and gate checks reference method names exactly, so a rename is deliberate.

## Lane switch

One assembly serves every declared lane: tests resolve the lane with the hosts' `HostingLaneResolver` (`NonAzure` unless `{APP}_LANE=Azure`), start only that lane's stores, and CI runs the assembly once per declared lane. Generate the `Azure` arm (SQL Server, Azurite, Service Bus) only when `hostingLanes` includes `Azure`; it differs only where an **Azure arm** note says. A single-lane test calls `IntegrationTestSetup.RequireLane(lane)`, `Inconclusive` on the other lane. `Test.E2E` and `Test.Aspire` read the same `TestHostingLane`.

## Fixture model

Each store the app uses gets a **standalone Testcontainer fixture** under `tests/Test.Integration/Infrastructure/`. A single `IntegrationTestSetup` runs the shared bounded Docker preflight, starts the lane's fixtures in parallel from `[AssemblyInitialize]`, and disposes them in `[AssemblyCleanup]`. Each fixture captures its `StartupError` rather than throwing so discovery continues, but each dependent test then fails with the full exception. Only the preflight-confirmed unavailable runtime is `Inconclusive`. Generate only the fixtures the app needs, each named for its store and independent of the Aspire host: `DbContainerFixture` always; `RedisContainerFixture` when a distributed cache, limiter, or Redis Data Protection is in scope; `RabbitMqBrokerFixture` when `messagingProvider: RabbitMq`; `SeaweedFsContainerFixture` when `storageProvider: S3`.

> **Cleanup is owned by `DisposeAsync` + the Testcontainers reaper - never hand-sweep Docker.** Each fixture's `StopAsync` -> `DisposeAsync` removes its own container; the Resource Reaper (Ryuk) removes only containers carrying this run's `org.testcontainers.session-id` label when a crashed process exits. A `docker rm`/`docker container prune` sweep by image name or generic label also deletes other projects', other sessions', and intentional persistent containers.

---

### File: `tests/Test.Support/Hosting/TestDatabaseContainer.cs`

Shared by `DbContainerFixture` and the `Test.E2E` `DbApiFactory`. `ContainerImages` is the one image catalog in the shared hosting project (reviewed tag plus manifest digest per image); AppHost and every fixture read it.

```csharp
using EF.IntegrationTesting.Testcontainers;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Configuration;
using Npgsql;
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
    private readonly PostgreSqlContainerFixture _postgres = new(ContainerImages.PostgreSql);

    public {App}DbProvider Provider { get; } = provider;
    public string ConnectionString => _postgres.ConnectionString;
    public Task StartAsync() => _postgres.StartAsync();
    public ValueTask DisposeAsync() => _postgres.DisposeAsync();

    /// <summary>Empty database for a test whose rows or counts must not be shared with other classes.</summary>
    public async Task<string> CreateEmptyDatabaseAsync(string prefix)
    {
        // PostgreSQL truncates identifiers at 63 bytes; the suffix adds 33 characters, so keep prefix <= 30.
        var name = $"{prefix}_{Guid.NewGuid():N}";
        var admin = new NpgsqlConnectionStringBuilder(ConnectionString) { Database = "postgres" };
        await using var connection = new NpgsqlConnection(admin.ConnectionString);
        await connection.OpenAsync();
        await using var command = connection.CreateCommand();
        command.CommandText = $"CREATE DATABASE \"{name}\"";
        await command.ExecuteNonQueryAsync();
        return new NpgsqlConnectionStringBuilder(ConnectionString) { Database = name }.ConnectionString;
    }

    /// <summary>Interceptors can only be added at options-build time, so observers pass them here.</summary>
    public DbContextOptions<TContext> BuildOptions<TContext>(string? connectionString, params IInterceptor[] extra)
        where TContext : DbContext =>
        new DbContextOptionsBuilder<TContext>()
            .Use{App}Provider(Provider, connectionString ?? ConnectionString) // owns schema + history table
            .AddInterceptors(/* the non-audit interceptors the hosts register (version stamp, outbox staging) */)
            .AddInterceptors(extra)
            .Options;
}
```

`Use{App}Provider` is the central provider-options helper ([../patterns/data-layer-wiring.md](../patterns/data-layer-wiring.md) section Registration), exposed from `Infrastructure.Data` so hosts, migrator, design-time factory, and tests share one schema/history-table rule.

> **Azure arm:** hold an `MsSqlContainerFixture(ContainerImages.SqlServer)` instead of the PostgreSQL fixture when `Provider` is `SqlServer`, and branch `CreateEmptyDatabaseAsync` to `SqlConnectionStringBuilder` with admin catalog `master` and `CREATE DATABASE [{name}]`. `BuildOptions` needs no branch.

### File: `tests/Test.Integration/Infrastructure/DbContainerFixture.cs`

```csharp
using {Project}.Infrastructure.Data;
using Test.Support.Hosting;

namespace Test.Integration.Infrastructure;

/// <summary>
/// Standalone database Testcontainer on the lane's provider, started by <see cref="IntegrationTestSetup"/>;
/// <see cref="StartupError"/> is captured so dependent tests fail with it without aborting discovery.
/// </summary>
internal static class DbContainerFixture
{
    private static readonly TestDatabaseContainer Container = new(TestHostingLane.DatabaseProvider);

    internal static Exception? StartupError { get; private set; }
    internal static string ConnectionString => Container.ConnectionString;

    internal static async Task StartAsync()
    {
        try { await Container.StartAsync(); }
        catch (Exception ex) { StartupError = ex; }
    }

    internal static async Task StopAsync() => await Container.DisposeAsync();

    internal static Task<string> CreateEmptyDatabaseConnectionStringAsync(string prefix) =>
        Container.CreateEmptyDatabaseAsync(prefix);

    internal static {App}DbContextTrxn CreateTrxnContext(string? connString = null) =>
        new(Container.BuildOptions<{App}DbContextTrxn>(connString)) { AuditId = "integration-test" };

    internal static {App}DbContextQuery CreateQueryContext(string? connString = null) =>
        new(Container.BuildOptions<{App}DbContextQuery>(connString)) { AuditId = "integration-test" };
}
```

> **`AuditId` bypass:** `DbContextBase<string, Guid?>` declares `required string AuditId`. When constructing contexts outside DI, set it directly via object-initializer syntax - the design-time factory uses the same pattern. A context that takes an `IRequestContext` instead gets an admin context here.

The other store fixtures follow the same `StartupError` / `StartAsync` / `StopAsync` shape:

- **RabbitMQ:** `new RabbitMqBuilder(ContainerImages.RabbitMq).WithUsername("{app}").WithPassword("{app}-password").Build()` - current images refuse a remote `guest` login, so the container gets its own credentials and clients read them back from `GetConnectionString()` (exposed as `ConnectionString`).
- **Redis:** `RedisTestContainer` in `tests/Test.Support/Hosting` (shared with `DbApiFactory`) wraps `new RedisBuilder(ContainerImages.Redis).Build()` and exposes `ConnectionString` and `IsStarted`; `RedisContainerFixture` wraps it.
- **SeaweedFS (S3):** `new ContainerBuilder(ContainerImages.SeaweedFs).WithCommand("mini", "-dir=/data")` with `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` values the fixture also exposes, `WithPortBinding(8333, true)`, and `Wait.ForUnixContainer().UntilInternalTcpPortIsAvailable(8333)`; `ServiceUrl` is `http://{Hostname}:{GetMappedPublicPort(8333)}`.
- **Azure arm:** `AzuriteContainerFixture` wraps `new AzuriteBuilder(ContainerImages.Azurite).Build()` (the parameterless builder is obsolete) and exposes `GetConnectionString()`.

### File: `tests/Test.Integration/Infrastructure/IntegrationTestSetup.cs`

```csharp
namespace Test.Integration.Infrastructure;

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
        Task[] starts = _lane == HostingLane.Azure
            ? [DbContainerFixture.StartAsync(), RedisContainerFixture.StartAsync(), AzuriteContainerFixture.StartAsync()]
            : [DbContainerFixture.StartAsync(), RedisContainerFixture.StartAsync(),
               RabbitMqBrokerFixture.StartAsync(), SeaweedFsContainerFixture.StartAsync()];
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

> **Paged search projection is required at `balanced`+ for every searchable aggregate.** Call the repo's search method (which wraps `QueryPageProjectionAsync`) for a normal `PageIndex=1, PageSize=n` request and assert **both** the page contents **and** `Total`. Only this tier catches a positional call - swapped `pageSize`/`pageIndex` (near-empty page) or `includeTotal:false` (`Total = -1`) - because fast-tier fakes translate it into correct-looking results. See the "Call it with named arguments" note in [repository-template.md](repository-template.md).

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

        // Read - FindAsync takes the key array-wrapped, THEN the token (the named-arg form is a compile break).
        var fetched = await db.{Entities}.FindAsync([id], ct);
        Assert.IsNotNull(fetched);
        Assert.AreEqual("Integration {Entity}", fetched.Name);

        // Update via domain method
        fetched.Update(name: "Updated {Entity}");
        await db.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins, cancellationToken: ct);
        var updated = await db.{Entities}.FindAsync([id], ct);
        Assert.AreEqual("Updated {Entity}", updated!.Name);

        // Delete
        db.{Entities}.Remove(updated);
        await db.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins, cancellationToken: ct);
        var deleted = await db.{Entities}.FindAsync([id], ct);
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
    public async Task TenantQueryFilter_RestrictsResults_WhenTenantIdSet()
    {
        // Only generate when enableMultiTenant is true.
        await using var db = DbContainerFixture.CreateTrxnContext();
        await db.Database.MigrateAsync();

        var entityA = new {Entity}Builder().WithTenantId(TenantA).WithName("Tenant A").Build();
        var entityB = new {Entity}Builder().WithTenantId(TenantB).WithName("Tenant B").Build();
        db.{Entities}.Add(entityA);
        db.{Entities}.Add(entityB);
        await db.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins);

        // IgnoreQueryFilters returns all rows; the active filter must restrict the count.
        var allViaEf = await db.{Entities}.IgnoreQueryFilters()
            .Where(e => e.Name.StartsWith("Tenant"))
            .ToListAsync();
        Assert.IsGreaterThanOrEqualTo(allViaEf.Count, 2);

        var filteredCount = await db.{Entities}
            .Where(e => e.Name.StartsWith("Tenant"))
            .CountAsync();

        Assert.IsGreaterThanOrEqualTo(allViaEf.Count, filteredCount,
            "Query filter should restrict results");
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
| `{Entity}_UpdateFromDto_AddsChildToReloadedParent_AgainstRealSql` | Entity has owned/dependent child collections (1:N) **and** an `{Entity}Updater`. Required regression guard for the `ValueGeneratedNever` key baseline (GR-16) - the only test that adds a NEW child through `repo.UpdateFromDto` against the real database. A green `{Entity}_WithChildren_PersistsCorrectly` does not substitute for it. |
| `{Entity}Tag_ManyToMany_WorksCorrectly` | Entity participates in M:N via a junction. |
| `TenantQueryFilter_RestrictsResults_WhenTenantIdSet` | `enableMultiTenant: true`. |
| `Polymorphic_Index_Exists` | Entity uses a polymorphic ownership pattern (e.g., `Attachment.OwnerType` + `OwnerId`). |

---

## Audit Repository Test

Generate for `auditProvider: Relational`.

### File: `tests/Test.Integration/RelationalAuditLogRepositoryTests.cs`

```csharp
using EF.Common.Contracts;
using Microsoft.EntityFrameworkCore;
using {Project}.Hosting;
using {Project}.Infrastructure.Repositories;
using Test.Integration.Infrastructure;

namespace Test.Integration;

/// <summary>
/// Validates RelationalAuditLogRepository: tenant-first key, sentinel tenant for a null tenant, field round trip.
/// Component tier; each test migrates its own empty database so audit rows never mix with another class's.
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
            EntityType = "{Entity}", EntityKey = Guid.NewGuid().ToString(),
            Status = AuditStatus.Success, Action = "Create", Metadata = "{\"source\":\"relational-test\"}"
        };
        var systemEntry = new AuditEntry<string, Guid?>
        {
            Id = Guid.CreateVersion7(), AuditId = "system", TenantId = null,
            EntityType = "Retention", EntityKey = "sweep", Status = AuditStatus.Success, Action = "Purge"
        };

        await using (var db = DbContainerFixture.CreateTrxnContext(connString))
        {
            var repository = new RelationalAuditLogRepository(db, SystemTenantId);
            await repository.AppendAsync(entry, ct);
            await repository.AppendAsync(systemEntry, ct);
        }

        await using var verify = DbContainerFixture.CreateQueryContext(connString);
        var persisted = await verify.AuditLog.AsNoTracking().SingleAsync(e => e.Id == entry.Id, ct);
        Assert.AreEqual(tenantId.ToString(), persisted.TenantId, "tenant-first key: one tenant's trail is a range scan");
        Assert.AreEqual(entry.AuditId, persisted.AuditId);
        Assert.AreEqual(entry.Status.ToString(), persisted.Status);
        Assert.AreEqual(entry.Metadata, persisted.Metadata);  // assert every mapped field the sink stores

        var system = await verify.AuditLog.AsNoTracking().SingleAsync(e => e.Id == systemEntry.Id, ct);
        Assert.AreEqual(SystemTenantId, system.TenantId, "a null tenant is stored under the sentinel");
    }
}
```

Add `PurgeOlderThan_WalksTheWindowInBatches_AndKeepsRowsInsideIt` when the sink has a retention sweep: seed rows at explicit `RecordedUtc` values on both sides of a fixed cutoff, purge with a batch size smaller than the expired count, and assert the returned total plus the surviving in-window rows - one unbounded `DELETE` reports the same total and proves nothing.

> **Azure arm:** `AuditLogRepositoryAzuriteTests` holds the Azure Table repository (`AuditLogRepository`) to the same contract against `AzuriteContainerFixture`: a `TableServiceClient` over the fixture connection string behind a one-line `IAzureClientFactory<TableServiceClient>` stub, a unique table per test deleted in `finally`, and assertions on the partition-key and row-key shape, behind `RequireLane(HostingLane.Azure)`.

The **API audit pipeline over HTTP** is a mesh test - see [test-templates-aspire.md](test-templates-aspire.md).

---

## RabbitMQ Transport Test

Generate when `messagingProvider: RabbitMq`. Proves the app's half of the provider (the package's own tests cover confirms, prefetch, and dead-lettering); duplicate-delivery proof is the inbox test owned by [../skills/messaging.md](../skills/messaging.md) section At-Least-Once Consumer: Inbox. Staging, envelope, and topology member names follow the reference app - read the generated members before binding (GR-18).

### File: `tests/Test.Integration/RabbitMqTransportTests.cs`

```csharp
using EF.Messaging.RabbitMq;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using RabbitMQ.Client;
using {Project}.Application.Contracts.Messaging;
using {Project}.Hosting;
using {Project}.Infrastructure.Data.Interceptors;
using {Project}.Infrastructure.Messaging.RabbitMq;
using Test.Integration.Infrastructure;
using Test.Support;

namespace Test.Integration;

/// <summary>
/// Validates {Project}RabbitMqEventTransport and {Project}RabbitMqTopology against a real broker: a staged outbox
/// row reaches every bound queue in the shape consumers read back. Component tier: one RabbitMQ Testcontainer.
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
        // The staging interceptor's row builder, so the test sends exactly what SaveChanges stages.
        var row = OutboxStagingInterceptor.ToRow(envelope, TestConstants.TenantId, DateTimeOffset.UtcNow);

        var failures = await provider.GetRequiredService<IIntegrationEventTransport>()
            .SendBatchAsync(row.Destination, [row], ct);
        Assert.IsEmpty(failures, "a confirmed publish reports no failed message");

        foreach (var queue in new[] { {Project}RabbitMqTopology.ProjectionQueue /*, every queue bound to this event */ })
        {
            var delivered = await GetAsync(queue, ct);
            Assert.IsNotNull(delivered, $"nothing arrived on {queue}");
            Assert.AreEqual(row.Id.ToString(), delivered.BasicProperties.MessageId);
            Assert.AreEqual("corr-1", delivered.BasicProperties.CorrelationId);
            Assert.AreEqual(nameof({Entity}CreatedEvent), delivered.RoutingKey);
            Assert.IsTrue(IntegrationEnvelopeReader.TryRead(delivered.Body.Span, out var read, out _));
            Assert.AreEqual(envelope.Id, read!.Id);
        }
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
        services.AddRabbitMqMessaging(config, "Messaging:RabbitMq");
        services.AddSingleton<IIntegrationEventTransport, {Project}RabbitMqEventTransport>();
        var provider = services.BuildServiceProvider();
        await provider.GetRequiredService<IRabbitMqTopologyDeclarer>().DeclareAsync({Project}RabbitMqTopology.Build(), ct);
        return provider;
    }

    /// <summary>Polls briefly: a publisher confirm means the broker has the message, not that it is routed yet.</summary>
    private static async Task<BasicGetResult?> GetAsync(string queue, CancellationToken ct)
    {
        var factory = new ConnectionFactory { Uri = new Uri(RabbitMqBrokerFixture.ConnectionString) };
        await using var connection = await factory.CreateConnectionAsync(ct);
        await using var channel = await connection.CreateChannelAsync(cancellationToken: ct);
        for (var attempt = 0; attempt < 40; attempt++)
        {
            if (await channel.BasicGetAsync(queue, autoAck: true, ct) is { } result) return result;
            await Task.Delay(100, ct);
        }
        return null;
    }
}
```

Add, in the same class: `MalformedBody_FailsEnvelopeParsing_BeforeAnyConsumerRuns` (purge the queue, publish a non-envelope body through `IRabbitMqPublisher` with a bound routing key, assert the delivery fails `IntegrationEnvelopeReader.TryRead` with its malformed reason); one routing assertion per consumer filter (an event bound to one queue reaches no other); one test per optional binding published through the same exchange.

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

> `EF.IntegrationTesting` carries both database container fixtures; `Test.Support` carries `Testcontainers.Redis`. Add `AWSSDK.S3` for an object-storage test. **Azure arm:** add `Testcontainers.Azurite`, `Azure.Data.Tables`, and the `Infrastructure.Storage` reference.

---

## Verification

- [ ] `Test.Integration` references **no** `AppHost` and **no** `Aspire.Hosting.Testing`; tests instantiate the class under test against a fixture connection string.
- [ ] One `IntegrationTestSetup` owns bounded Docker preflight plus the sole `[AssemblyInitialize]`/`[AssemblyCleanup]` and starts only the resolved lane's fixtures; each fixture captures `StartupError`.
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
- `../scaffold-proof/tests/Test.Integration/RelationalAuditLogRepositoryTests.cs`
- `../scaffold-proof/tests/Test.Integration/RabbitMqTransportTests.cs`
- `../scaffold-proof/tests/Test.Integration/AuditLogRepositoryAzuriteTests.cs` (Azure arm)
- `../scaffold-proof/tests/Test.Integration/DomainEventPipelineTests.cs`

**TaskFlow proof (remote fallback):**
<https://github.com/efreeman518/scaffold-proof/tree/main/tests/Test.Integration>
