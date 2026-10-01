# Test Templates - Endpoint (Phase 5b)

| | |
|---|---|
| **Generates** | `tests/Test.Endpoints/Endpoints/{Entity}EndpointsTests.cs`, `tests/Test.Endpoints/Middleware/ExceptionMappingTests.cs`, `tests/Test.Endpoints/HealthProbeContractTests.cs` |
| **Requires** | [endpoint-template](endpoint-template.md), [exception-handler-template](exception-handler-template.md), [health-check-template](health-check-template.md), CustomApiFactory from Phase 4, DTOs from Phase 4 |
| **Phase** | 5b (App Core TDD) |
| **Protocol** | Write these tests BEFORE implementing endpoints. See [../ai/tdd-protocol.md](../ai/tdd-protocol.md). |

## Test Naming Convention

Owned by [../skills/testing.md](../skills/testing.md) section Test Naming Convention. `Given_When_Then` is the
default; `<Subject>_<Condition>_<Outcome>` applies when a named member or structural fact is under test.

---

## Shared JSON Options (Required)

Every `ReadFromJsonAsync<T>` / `PostAsJsonAsync<T>` call must pass `JsonTestOptions.Default` from `Test.Support`. Without it, responses carrying string enums (`"status": "InProgress"`) fail to deserialize against the default `JsonSerializerOptions` and tests pass-then-fail based on whether the API host happened to emit a numeric or named enum. The shared options align the test deserializer with the host's `ConfigureHttpJsonOptions` (see [../skills/api.md](../skills/api.md) section JSON Contract Across Hosts and Tests).

```csharp
// Required at the top of every endpoint test file
using static {Project}.Test.Support.JsonTestOptions;

var dto = await response.Content.ReadFromJsonAsync<DefaultResponse<{Entity}Dto>>(Default);
await client.PostAsJsonAsync("/api/{entities}", request, Default);
```

If the test base evolves to wrap `HttpClient` in an extension method (e.g. `client.GetJsonAsync<T>("/api/...")`), the extension must close over `JsonTestOptions.Default` internally so no individual test forgets the converter set.

---

## Shared WebApplicationFactoryBase (in Test.Support)

The plumbing for swapping the production DbContext + interceptors + pooled factories with a test-mode store ships in the `EF.IntegrationTesting` package as `EF.IntegrationTesting.AspNetCore.EfWebApplicationFactoryBase<TProgram, TTrxnContext, TQueryContext>`. `Test.Support` carries only a thin app adapter, `WebApplicationFactoryBase<TProgram, TTrxnContext, TQueryContext>`, and both `Test.Endpoints` (in-memory) and `Test.E2E` (Testcontainers database) derive specializations that declare the store and the lane.

The adapter pins every mode-selecting config key (auth mode, provider toggles) explicitly - a Development-environment test host loads the developer's **user secrets**, which override both appsettings files and can flip test topology on one machine while CI stays green. Test factories extend base configuration; they never replace it wholesale, or the pinned keys silently vanish in derived factories.

> **Phase 4 generates this file.** The adapter is part of the contract-scaffolding output (see [../ai/contract-scaffolding.md](../ai/contract-scaffolding.md), `### 4. Test Infrastructure`) so the solution builds and both `Test.Endpoints` and `Test.E2E` compile before Phase 5 begins; the swap takes effect in 5b.

`tests/Test.Support/WebApplicationFactoryBase.cs`:

```csharp
using EF.Data;
using EF.IntegrationTesting.AspNetCore;
using Microsoft.AspNetCore.Hosting;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace Test.Support;

/// <summary>
/// App-specific adapter over the reusable EF.IntegrationTesting WebApplicationFactory base.
/// Keeps test factories stable while the shared EF host-replacement plumbing lives in the package.
/// </summary>
public abstract class WebApplicationFactoryBase<TProgram, TTrxnContext, TQueryContext>
    : EfWebApplicationFactoryBase<TProgram, TTrxnContext, TQueryContext>
    where TProgram : class
    where TTrxnContext : DbContextBase<string, Guid?>
    where TQueryContext : DbContextBase<string, Guid?>
{
    // EF.Host keeps registered startup tasks in one registry; removing it makes RunStartupTasksAsync a no-op.
    protected override string? StartupTaskServiceTypeFullName => "EF.Host.StartupTaskRegistry";

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        base.ConfigureWebHost(builder);
        builder.ConfigureLogging(logging =>
        {
            logging.ClearProviders();
            logging.AddConsole();
        });
    }

    // Tenant-less harness contexts read nothing under the fail-closed filter unless marked all-tenants;
    // tenant isolation is proven by the container-backed tests.
    protected override void ConfigureAdditionalTestServices(IServiceCollection services)
    {
        AllTenants<TTrxnContext>(services);
        AllTenants<TQueryContext>(services);
    }

    private static void AllTenants<TContext>(IServiceCollection services)
        where TContext : DbContextBase<string, Guid?>
    {
        var scoped = services.Last(d => d.ServiceType == typeof(TContext)).ImplementationFactory!;
        services.AddScoped(sp =>
        {
            var context = (TContext)scoped(sp);
            context.AllTenants = true;
            return context;
        });

        var factory = (IDbContextFactory<TContext>)services
            .Last(d => d.ServiceType == typeof(IDbContextFactory<TContext>)).ImplementationInstance!;
        services.AddSingleton<IDbContextFactory<TContext>>(new EfTestDbContextFactory<TContext>(() =>
        {
            var context = factory.CreateDbContext();
            context.AllTenants = true;
            return context;
        }));
    }
}
```

**What the package base does** (`EfWebApplicationFactoryBase`, namespace `EF.IntegrationTesting.AspNetCore`): removes the production EF registrations for both contexts (pooled contexts and pool/lease plumbing, `DbContextOptions<T>`, `IDbContextFactory<T>` + `DbContextScopedFactory`, the audit interceptor and the SQL Server NOLOCK interceptor by type name), re-registers test-mode `IDbContextFactory<T>` + scoped contexts built from the options the derived factory supplies, creates contexts via reflection (bypasses `required` audit/tenant member enforcement - no CS9035), and suppresses app startup tasks named by `StartupTaskServiceTypeFullName`. Descriptor removal no-ops when a registration is absent, so the adapter is safe in a Phase 4 contract scaffold where the host registers no DbContext yet.

**Critical details:**

1. **Typed options per context** (`DbContextOptionsFactory.BuildInMemoryOptions<{App}DbContextTrxn>(...)`). `DbContextBase` constructors take non-generic `DbContextOptions`, but EF validates the generic type at runtime.
2. Derived factories provide only the test-mode store: override `BuildTrxnOptions()` / `BuildQueryOptions()`, or `ConnectionString` plus `BuildOptionsFor<TContext>(connectionString)`, which has no provider default and throws until overridden with `PostgreSqlTestDbContextOptions.Build` or `SqlServerTestDbContextOptions.Build`.
3. **`HostSettings` vs `ConfigureTestConfiguration`:** `Program` reads configuration while it registers services, before `ConfigureAppConfiguration` sources exist. A key registration reads (lane, application style, provider toggles) goes in `HostSettings`, which the base applies both as a host setting and in the final configuration; `ConfigureTestConfiguration(IConfigurationBuilder)` affects only the final configuration.
4. **`ConfigureAdditionalTestServices`** runs after the swap; the adapter marks both harness contexts all-tenants there.
5. Do not hand-roll descriptor-removal or reflection-creation plumbing in the app - it ships in `EF.IntegrationTesting` (see [../support/ef-packages-optional.md](../support/ef-packages-optional.md) section Testing (EF.Testing, EF.Testing.Architecture, EF.AI.Testing, EF.IntegrationTesting.*)).

## DbAggregateSeeder (in Test.Support)

**Conditional - generate on first need, not by default.** When the API can create every row a test acts
on (dev-seam auth supplies user/tenant), seed through the API - that is the reference pattern, and this
file is not generated. Builders (`tests/Test.Support/Builders/{Entity}Builder.cs`) construct **domain objects
in memory**; they do not persist a valid FK chain. When tests need prerequisite rows the API never
creates (a real user in a real tenant owning the aggregate), do not duplicate that insert inline - it
drifts per-test and reintroduces the user/tenant FK bugs the dev seam fixes. Provide this one shared
seeder in `Test.Support` that persists the full FK chain in dependency order through the live DbContext.

`tests/Test.Support/DbAggregateSeeder.cs`:

```csharp
namespace Test.Support;

/// <summary>
/// Persists a valid FK chain (tenant -> user -> aggregate -> children) against a real store via the
/// transactional DbContext, so workflow/E2E tests start from a row the API will accept. Builders
/// construct the domain objects; this seeder owns insert order and FK wiring. Idempotent per id.
/// </summary>
public sealed class DbAggregateSeeder(IDbContextFactory<{App}DbContextTrxn> factory)
{
    public async Task<SeededContext> SeedAsync(CancellationToken ct = default)
    {
        await using var db = await factory.CreateDbContextAsync(ct);

        // 1. Tenant first (and the user, when the app models users as an entity with an owner FK) -
        //    use the same fixed ids the dev principal/claims use so seeded rows, fixed-principal
        //    claims, and stamped owners all line up. Drop the user step for audit-id-string owners.
        if (!await db.Set<Tenant>().AnyAsync(t => t.Id == SeedConstants.DevTenantId, ct))
            db.Add(Tenant.Create("Test Tenant", SeedConstants.DevTenantId));
        if (!await db.Set<User>().AnyAsync(u => u.Id == SeedConstants.DevUserId, ct))
            db.Add(User.Create(SeedConstants.DevUserId, "Test Principal", SeedConstants.DevTenantId));

        // 2. Aggregate + children via the builder, owned by the seeded user/tenant.
        var parent = new {Entity}Builder()
            .WithTenant(SeedConstants.DevTenantId)
            .WithOwner(SeedConstants.DevUserId)
            .WithChild(/* ... */)
            .Build();
        db.Add(parent);

        await db.SaveChangesAsync(ct);
        return new SeededContext(SeedConstants.DevTenantId, SeedConstants.DevUserId, parent.Id);
    }
}

public sealed record SeededContext(Guid TenantId, Guid UserId, Guid AggregateId);
```

Use it from `[ClassInitialize]`/`[TestInitialize]` in `Test.E2E` and `Test.Integration` after migrations
are applied, instead of inline seeding. The primary domain-journey E2E
([test-templates-e2e.md](test-templates-e2e.md) section Primary domain-journey E2E) and the multi-resource
integration tier ([test-templates-integration.md](test-templates-integration.md)) both consume it.

## Test.Endpoints derived factory (in-memory)

The endpoint tier needs no container. It pins the lane explicitly - a Development host otherwise resolves whatever the developer's environment selects - and gives each of that lane's external data planes an inert endpoint plus an in-process replacement. Pin a lane whose registration opens no connection: the package Redis Data Protection store and the EF.Cache shared multiplexer connect lazily, so the default `NonAzure` lane qualifies.

`tests/Test.Support/Hosting/InertLane.cs` holds the registration-time `Settings` and a `ReplaceDataPlanes(IServiceCollection)` that swaps every store the in-memory contexts cannot serve (Data Protection to `EphemeralDataProtectionProvider`, object storage, audit sink, read-model store) for an in-process implementation. `tests/Test.Endpoints/CustomApiFactory.cs`:

```csharp
public sealed class CustomApiFactory : WebApplicationFactoryBase<Program, {App}DbContextTrxn, {App}DbContextQuery>
{
    private readonly string _dbName = $"TestDb_{Guid.NewGuid()}";

    // Program reads these while registering services, so they go in as host settings.
    protected override IReadOnlyDictionary<string, string?> HostSettings => InertLane.Settings;

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        base.ConfigureWebHost(builder);
        builder.ConfigureServices(InertLane.ReplaceDataPlanes);
    }

    protected override DbContextOptions BuildTrxnOptions() =>
        DbContextOptionsFactory.BuildInMemoryOptions<{App}DbContextTrxn>(_dbName);

    protected override DbContextOptions BuildQueryOptions() =>
        DbContextOptionsFactory.BuildInMemoryOptions<{App}DbContextQuery>(_dbName);
}
```

`DbContextBase` stamps `Version` and the timestamps on save, so the in-memory contexts carry the ETag contract without an extra interceptor. The API host registers no outbox dispatcher, so staged rows stay in the in-memory database and no transport needs replacing.

> **`NonAzure` pin:** `Hosting:Lane=NonAzure` with inert `Redis1` (`abortConnect=false`), `Storage:S3:*`, and `Messaging:RabbitMq:ConnectionString` values, and a `CacheSettings` Redis connection name with no connection string so the cache and the rate limiter stay in process. **Azure pin:** inert Blob, Table, Cosmos and Service Bus endpoints; the SDK clients are lazy.

The pooled-context swap, interceptor removal, factory plumbing, and reflection-based context creation are inherited. `Test.E2E` derives `DbApiFactory` from the same base on a real database container: [test-templates-e2e.md](test-templates-e2e.md) section DbApiFactory. Full distributed-app tests use `AspireTestHost` ([test-templates-aspire.md](test-templates-aspire.md)); one-class-vs-one-store tests use the `Test.Integration` fixtures ([test-templates-integration.md](test-templates-integration.md)). The WAF base is for HTTP-in-API-out testing.

---

## Endpoint Tests

### File: `tests/Test.Endpoints/Endpoints/{Entity}EndpointsTests.cs`

```csharp
[TestClass]
public class {Entity}EndpointsTests : EndpointTestBase
{
    [TestCategory("Endpoint")]
    [TestMethod]
    public async Task Given_ValidPayload_When_PostEntity_Then_Returns201()
    {
        // Arrange
        using var client = await GetHttpClient();
        var tenantId = Guid.NewGuid();
        var createDto = new DefaultRequest<{Entity}Dto>
        {
            Item = new {Entity}Dto { Name = "NewEntity", TenantId = tenantId }
        };

        // Act
        var response = await client.PostAsJsonAsync($"v1/tenant/{tenantId}/{entities}", createDto);

        // Assert
        Assert.AreEqual(HttpStatusCode.Created, response.StatusCode);
        var created = await response.Content.ReadFromJsonAsync<DefaultResponse<{Entity}Dto>>();
        Assert.IsNotNull(created?.Item);
        Assert.AreEqual("NewEntity", created.Item.Name);
    }

    [TestCategory("Endpoint")]
    [TestMethod]
    public async Task Given_NonExistentId_When_GetEntity_Then_Returns404()
    {
        // Arrange
        using var client = await GetHttpClient();
        var tenantId = Guid.NewGuid();
        var nonExistentId = Guid.NewGuid();

        // Act
        var response = await client.GetAsync($"v1/tenant/{tenantId}/{entities}/{nonExistentId}");

        // Assert
        Assert.AreEqual(HttpStatusCode.NotFound, response.StatusCode);
        var problemDetails = await response.Content.ReadFromJsonAsync<ProblemDetails>();
        Assert.IsNotNull(problemDetails);
        Assert.AreEqual(404, problemDetails.Status);
    }

    [TestCategory("Endpoint")]
    [TestMethod]
    public async Task Given_ExistingEntities_When_SearchWithFilter_Then_ReturnsFilteredPage()
    {
        // Arrange
        using var client = await GetHttpClient();
        var tenantId = Guid.NewGuid();

        // Seed
        var create1 = new DefaultRequest<{Entity}Dto>
        {
            Item = new {Entity}Dto { Name = "SearchTarget", TenantId = tenantId }
        };
        var create2 = new DefaultRequest<{Entity}Dto>
        {
            Item = new {Entity}Dto { Name = "OtherItem", TenantId = tenantId }
        };
        await client.PostAsJsonAsync($"v1/tenant/{tenantId}/{entities}", create1);
        await client.PostAsJsonAsync($"v1/tenant/{tenantId}/{entities}", create2);

        // Act
        var searchRequest = new SearchRequest<{Entity}SearchFilter>
        {
            PageIndex = 1,
            PageSize = 10,
            Filter = new {Entity}SearchFilter { SearchTerm = "SearchTarget" }
        };
        var response = await client.PostAsJsonAsync(
            $"v1/tenant/{tenantId}/{entities}/search", searchRequest);

        // Assert
        Assert.AreEqual(HttpStatusCode.OK, response.StatusCode);
        var page = await response.Content.ReadFromJsonAsync<PagedResponse<{Entity}Dto>>();
        Assert.IsNotNull(page);
        Assert.AreEqual(1, page.Total);
        Assert.AreEqual("SearchTarget", page.Data.First().Name);
    }

    [TestCategory("Endpoint")]
    [TestMethod]
    public async Task Given_FullCrudCycle_When_AllOperationsExecuted_Then_AllSucceed()
    {
        // Arrange
        using var client = await GetHttpClient();
        var tenantId = Guid.NewGuid();

        // Create
        var createDto = new DefaultRequest<{Entity}Dto>
        {
            Item = new {Entity}Dto { Name = "CrudTest", TenantId = tenantId }
        };
        var createResponse = await client.PostAsJsonAsync($"v1/tenant/{tenantId}/{entities}", createDto);
        Assert.AreEqual(HttpStatusCode.Created, createResponse.StatusCode);
        var created = await createResponse.Content.ReadFromJsonAsync<DefaultResponse<{Entity}Dto>>();
        var entityId = created!.Item!.Id;

        // Read
        var getResponse = await client.GetAsync($"v1/tenant/{tenantId}/{entities}/{entityId}");
        Assert.AreEqual(HttpStatusCode.OK, getResponse.StatusCode);

        // Update - EF.Testing ConcurrencyHttpExtensions sends the strong ETag as If-Match
        var updateDto = new DefaultRequest<{Entity}Dto>
        {
            Item = new {Entity}Dto { Id = entityId, Name = "Updated", TenantId = tenantId }
        };
        var updateResponse = await client.PutAsJsonWithIfMatchAsync($"v1/tenant/{tenantId}/{entities}/{entityId}", updateDto,
            ConcurrencyHttpExtensions.FormatStrongETag(created.Item.Version!.Value), Default);
        Assert.AreEqual(HttpStatusCode.OK, updateResponse.StatusCode);
        var updated = await updateResponse.Content.ReadFromJsonAsync<DefaultResponse<{Entity}Dto>>(Default);

        // Delete
        var deleteResponse = await client.DeleteWithIfMatchAsync($"v1/tenant/{tenantId}/{entities}/{entityId}",
            ConcurrencyHttpExtensions.FormatStrongETag(updated!.Item!.Version!.Value));
        Assert.AreEqual(HttpStatusCode.NoContent, deleteResponse.StatusCode);

        // Verify deleted
        var verifyResponse = await client.GetAsync($"v1/tenant/{tenantId}/{entities}/{entityId}");
        Assert.AreEqual(HttpStatusCode.NotFound, verifyResponse.StatusCode);
    }

    [TestCategory("Endpoint")]
    [TestMethod]
    public async Task Given_NoIfMatch_When_PutEntity_Then_Returns428()
    {
        using var client = await GetHttpClient();
        var tenantId = Guid.NewGuid();
        var id = Guid.NewGuid();

        var response = await client.PutAsJsonAsync($"v1/tenant/{tenantId}/{entities}/{id}",
            new DefaultRequest<{Entity}Dto> { Item = new {Entity}Dto { Id = id, Name = "x", TenantId = tenantId } }, Default);

        Assert.AreEqual(HttpStatusCode.PreconditionRequired, response.StatusCode);
    }

    [TestCategory("Endpoint")]
    [TestMethod]
    public async Task Given_EmptyDatabase_When_SearchExecuted_Then_ReturnsEmptyPage()
    {
        // Arrange
        using var client = await GetHttpClient();
        var tenantId = Guid.NewGuid();
        var searchRequest = new SearchRequest<{Entity}SearchFilter>
        {
            PageIndex = 1,
            PageSize = 10,
            Filter = new {Entity}SearchFilter()
        };

        // Act
        var response = await client.PostAsJsonAsync($"v1/tenant/{tenantId}/{entities}/search", searchRequest);

        // Assert
        Assert.AreEqual(HttpStatusCode.OK, response.StatusCode);
        var page = await response.Content.ReadFromJsonAsync<PagedResponse<{Entity}Dto>>();
        Assert.IsNotNull(page);
    }
}
```

---

## Exception Mapping Tests

### File: `tests/Test.Endpoints/Middleware/ExceptionMappingTests.cs`

**Generate this whenever [exception-handler-template](exception-handler-template.md) is generated - it is not optional.** It builds the API's exception registration alone (`AddEfProblemDetails()` plus `AddExceptionClassifier(RegisterApiServices.MapExceptions)`) and drives the package `ProblemDetailsExceptionHandler` against a `DefaultHttpContext` - no host boot. The exception-text gate and the mapping table both need a test that fails if either drifts.

```csharp
using System.Text.Json;
using EF.AspNetCore.ExceptionHandling;
using EF.Common.Contracts;
using EF.Common.Exceptions;
using EF.Data.Contracts;
using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Hosting.Internal;
using {Host}.Api;

namespace Test.Endpoints.Middleware;

[TestClass]
[TestCategory("Endpoint")]
public sealed class ExceptionMappingTests
{
    public TestContext TestContext { get; set; } = null!;

    [TestMethod]
    public async Task Given_CallerAbort_When_Handled_Then_Returns499WithoutBody()
    {
        using var aborted = new CancellationTokenSource();
        await aborted.CancelAsync();
        using var provider = BuildProvider();
        var context = NewContext(provider);
        context.RequestAborted = aborted.Token;

        await Handler(provider).TryHandleAsync(context, new OperationCanceledException(aborted.Token), TestContext.CancellationToken);

        Assert.AreEqual(499, context.Response.StatusCode);
        Assert.AreEqual(0, context.Response.Body.Length);
    }

    [TestMethod]
    [DataRow("Production")]
    [DataRow("Staging")]
    public async Task Given_ServerFaultOutsideDevelopment_When_Handled_Then_NoExceptionText(string environmentName)
    {
        using var provider = BuildProvider(environmentName);
        var context = NewContext(provider);

        await Handler(provider).TryHandleAsync(
            context, new Exception("Login failed for user 'sa' on server sql-internal"), TestContext.CancellationToken);

        var root = await ReadBodyAsync(context);
        Assert.AreEqual(StatusCodes.Status500InternalServerError, context.Response.StatusCode);
        Assert.IsFalse(root.TryGetProperty("detail", out var detail) && detail.ValueKind == JsonValueKind.String,
            "A 5xx must not carry exception text outside Development.");
    }

    [TestMethod]
    public async Task Given_MappedExceptions_When_Handled_Then_ReturnTheirStatus()
    {
        (Exception Exception, int Status)[] cases =
        [
            (new PreconditionFailedException("{Entity}", Guid.CreateVersion7().ToString(), 1, 2), StatusCodes.Status412PreconditionFailed),
            (new DbUpdateConcurrencyException(), StatusCodes.Status412PreconditionFailed),
            (new ConflictException("{Entity}", Guid.CreateVersion7().ToString()), StatusCodes.Status409Conflict),
            (new InvalidRequestException("page size out of range"), StatusCodes.Status400BadRequest),
            (new InvalidCursorException("tampered"), StatusCodes.Status400BadRequest),
            (new OperationCanceledException(), StatusCodes.Status504GatewayTimeout)
        ];

        using var provider = BuildProvider();
        foreach (var (exception, status) in cases)
        {
            var context = NewContext(provider);
            await Handler(provider).TryHandleAsync(context, exception, TestContext.CancellationToken);
            Assert.AreEqual(status, context.Response.StatusCode, exception.GetType().Name);
        }
    }

    /// <summary>Framework exceptions are server bugs, never caller mistakes: 500 with no exception text.</summary>
    [TestMethod]
    public async Task Given_FrameworkFaults_When_Handled_Then_Return500()
    {
        Exception[] faults =
        [
            Capture(() => ArgumentOutOfRangeException.ThrowIfLessThan(0, 1)),
            Capture(() => int.Parse("x", System.Globalization.CultureInfo.InvariantCulture)),
            Capture(() => Array.Empty<int>().First())
        ];

        using var provider = BuildProvider();
        foreach (var fault in faults)
        {
            var context = NewContext(provider);
            await Handler(provider).TryHandleAsync(context, fault, TestContext.CancellationToken);
            Assert.AreEqual(StatusCodes.Status500InternalServerError, context.Response.StatusCode, fault.GetType().Name);
        }
    }

    private static ServiceProvider BuildProvider(string environmentName = "Production")
    {
        var services = new ServiceCollection();
        services.AddLogging();
        services.AddSingleton<IHostEnvironment>(new HostingEnvironment { EnvironmentName = environmentName, ContentRootFileProvider = new NullFileProvider() });
        services.AddEfProblemDetails();
        services.AddExceptionClassifier(RegisterApiServices.MapExceptions);
        return services.BuildServiceProvider();
    }

    private static IExceptionHandler Handler(IServiceProvider provider) =>
        provider.GetServices<IExceptionHandler>().OfType<ProblemDetailsExceptionHandler>().Single();

    private static DefaultHttpContext NewContext(IServiceProvider provider)
    {
        var context = new DefaultHttpContext { RequestServices = provider };
        context.Request.Method = HttpMethods.Get;
        context.Request.Path = "/failure";
        context.Response.Body = new MemoryStream();
        return context;
    }

    private static async Task<JsonElement> ReadBodyAsync(DefaultHttpContext context)
    {
        context.Response.Body.Position = 0;
        using var document = await JsonDocument.ParseAsync(context.Response.Body);
        return document.RootElement.Clone();
    }

    /// <summary>A genuinely thrown exception, so the stack trace is populated.</summary>
    private static Exception Capture(Action action)
    {
        try { action(); }
        catch (Exception ex) { return ex; }
        throw new AssertFailedException("The action did not throw.");
    }

}
```

Add one case per row the app adds to `MapExceptions`. Correlation assertions (`requestId` separate from W3C `traceId`/`spanId`) run here too: start a W3C `Activity`, set `context.TraceIdentifier`, and assert the three properties on the body.

---

## Health Probe Contract Tests

### File: `tests/Test.Endpoints/HealthProbeContractTests.cs`

**Generate this whenever [health-check-template](health-check-template.md) is generated.** The liveness/readiness split only pays for itself if a failed dependency stops new traffic without making the orchestrator restart a healthy process. The load-bearing test therefore forces a readiness check to fail and asserts the two probes diverge - registering the probes is not evidence that they behave differently.

```csharp
using System.Net;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Diagnostics.HealthChecks;

namespace Test.Endpoints;

/// <summary>
/// Pins the probe contract: <c>/healthz/live</c> answers for the process alone, <c>/healthz/ready</c>
/// answers for its tagged dependencies, and <c>/healthz</c> is the operator aggregate - never the
/// liveness target. See [health-check-template](health-check-template.md) Rules.
/// </summary>
[TestClass]
[TestCategory("Endpoint")]
public sealed class HealthProbeContractTests
{
    private static CustomApiFactory _factory = null!;

    public TestContext TestContext { get; set; } = null!;

    [ClassInitialize]
    public static void ClassInit(TestContext _) => _factory = new CustomApiFactory();

    [ClassCleanup]
    public static void ClassCleanup() => _factory?.Dispose();

    [TestMethod]
    public async Task Given_HealthyProcess_When_LivenessProbed_Then_ReturnsHealthy()
    {
        // Arrange
        using var client = _factory.CreateClient();

        // Act
        using var response = await client.GetAsync("/healthz/live", TestContext.CancellationToken);

        // Assert
        Assert.AreEqual(HttpStatusCode.OK, response.StatusCode);
        Assert.AreEqual("Healthy",
            await response.Content.ReadAsStringAsync(TestContext.CancellationToken));
    }

    [TestMethod]
    public async Task Given_FailedCriticalDependency_When_BothProbesQueried_Then_ReadyUnhealthyAndLiveHealthy()
    {
        // Arrange - an always-failing "ready"-tagged check stands in for a down dependency, so the test
        // needs no real outage. It is additive: the app's own readiness checks stay registered.
        using var factory = _factory.WithWebHostBuilder(builder =>
            builder.ConfigureTestServices(services => services
                .AddHealthChecks()
                .AddCheck("forced-dependency-failure",
                    () => HealthCheckResult.Unhealthy("forced for test"),
                    tags: ["ready"])));
        using var client = factory.CreateClient();

        // Act
        using var ready = await client.GetAsync("/healthz/ready", TestContext.CancellationToken);
        using var live = await client.GetAsync("/healthz/live", TestContext.CancellationToken);

        // Assert - the whole point of the split: traffic stops, the process is not restarted.
        Assert.AreEqual(HttpStatusCode.ServiceUnavailable, ready.StatusCode);
        Assert.AreEqual(HttpStatusCode.OK, live.StatusCode);
        Assert.AreEqual("Healthy",
            await live.Content.ReadAsStringAsync(TestContext.CancellationToken));
    }

    [TestMethod]
    public async Task Given_ReadinessProbe_When_Get_Then_MappedAndAnonymous()
    {
        // Arrange
        using var client = _factory.CreateClient();

        // Act
        using var response = await client.GetAsync("/healthz/ready", TestContext.CancellationToken);

        // Assert - mapped (not 404) and anonymous (not 401); its health value is asserted above.
        Assert.AreNotEqual(HttpStatusCode.NotFound, response.StatusCode);
        Assert.AreNotEqual(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [TestMethod]
    public async Task Given_OperatorAggregate_When_Get_Then_MappedAndAnonymous()
    {
        // Arrange
        using var client = _factory.CreateClient();

        // Act
        using var response = await client.GetAsync("/healthz", TestContext.CancellationToken);

        // Assert
        Assert.AreNotEqual(HttpStatusCode.NotFound, response.StatusCode);
        Assert.AreNotEqual(HttpStatusCode.Unauthorized, response.StatusCode);
    }
}
```

Add a `Given_RetiredAlias_When_Get_Then_NotFound` case for any probe path the app previously exposed and has since retired - two names for one probe is what the three-path contract rejects.

---

High-contention domains (inventory, reservations, financial flows) prove concurrency against the real database: `{Entity}_ConcurrentUpdates_OptimisticConcurrencyEnforced` in [test-templates-e2e.md](test-templates-e2e.md) section E2E test coverage matrix.
