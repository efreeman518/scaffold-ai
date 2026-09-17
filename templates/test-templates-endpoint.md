# Test Templates - Endpoint (Phase 5b)

| | |
|---|---|
| **Generates** | `tests/Test.Endpoints/Endpoints/{Entity}EndpointsTests.cs`, `tests/Test.Endpoints/Middleware/DefaultExceptionHandlerTests.cs`, `tests/Test.Endpoints/HealthProbeContractTests.cs` |
| **Requires** | [endpoint-template](endpoint-template.md), [exception-handler-template](exception-handler-template.md), [health-check-template](health-check-template.md), CustomApiFactory from Phase 4, DTOs from Phase 4 |
| **Phase** | 5b (App Core TDD) |
| **Protocol** | Write these tests BEFORE implementing endpoints. See [../ai/tdd-protocol.md](../ai/tdd-protocol.md). |

## BDD Naming Convention

All test methods use `Given_When_Then`:
```csharp
[TestMethod]
public async Task Given_ValidPayload_When_PostEntity_Then_Returns201() { }
```

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

The plumbing for swapping the production DbContext + interceptors + pooled factories with a test-mode store ships in the `EF.IntegrationTesting` package as `EF.IntegrationTesting.AspNetCore.EfWebApplicationFactoryBase<TProgram, TTrxnContext, TQueryContext>`. `Test.Support` carries only a thin app adapter, `WebApplicationFactoryBase<TProgram, TTrxnContext, TQueryContext>`, and both `Test.Endpoints` (in-memory) and `Test.E2E` (Testcontainers SQL) derive specializations that only declare which options to use.

The adapter pins every mode-selecting config key (auth mode, provider toggles) explicitly - a Development-environment test host loads the developer's **user secrets**, which override both appsettings files and can flip test topology on one machine while CI stays green. Test factories extend base configuration; they never replace it wholesale, or the pinned keys silently vanish in derived factories.

> **Phase 4 generates this file.** The adapter is part of the contract-scaffolding output (see [../ai/contract-scaffolding.md](../ai/contract-scaffolding.md), `### 4. Test Infrastructure`) so the solution builds and both `Test.Endpoints` and `Test.E2E` compile before Phase 5 begins. The package base's descriptor removal no-ops when a descriptor is absent - at Phase 4 the host registers no DbContext yet; the swap takes effect in 5b.

`tests/Test.Support/WebApplicationFactoryBase.cs`:

```csharp
using EF.Data;
using EF.IntegrationTesting.AspNetCore;
using Microsoft.AspNetCore.Hosting;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
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
    protected override string? StartupTaskServiceTypeFullName => "{App}.Bootstrapper.IStartupTask";

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        base.ConfigureWebHost(builder);
        builder.ConfigureLogging(logging =>
        {
            logging.ClearProviders();
            logging.AddConsole();
        });
    }
}
```

**What the package base does** (`EfWebApplicationFactoryBase`, namespace `EF.IntegrationTesting.AspNetCore`): removes the production EF registrations for both contexts (pooled contexts and pool/lease plumbing, `DbContextOptions<T>`, `IDbContextFactory<T>` + `DbContextScopedFactory`, the audit and SQL-only interceptors), re-registers test-mode `IDbContextFactory<T>` + scoped contexts built from the options the derived factory supplies, creates contexts via reflection (bypasses `required` audit/tenant member enforcement - no CS9035), and suppresses app startup tasks named by `StartupTaskServiceTypeFullName`. Descriptor removal no-ops when a registration is absent, so the adapter is safe in a Phase 4 contract scaffold where the host registers no DbContext yet.

**Critical details:**

1. **Typed options per context.** Use `new DbContextOptionsBuilder<{App}DbContextTrxn>().UseInMemoryDatabase(name).Options` - do NOT use generic `DbContextOptions` when multiple contexts exist. `DbContextBase` constructors take `DbContextOptions` (non-generic base), but EF validates the generic type at runtime.
2. Derived factories provide only the test-mode store (override the abstract `BuildTrxnOptions()` / `BuildQueryOptions()`); `ConfigureTestConfiguration(IConfigurationBuilder)` is the hook for app-specific test configuration.
3. Do not hand-roll descriptor-removal or reflection-creation plumbing in the app - it ships in `EF.IntegrationTesting` (see [../support/ef-packages-reference.md](../support/ef-packages-reference.md) section Testing).

## SqlAggregateSeeder (in Test.Support)

**Conditional - generate on first need, not by default.** When the API can create every row a test acts
on (dev-seam auth supplies user/tenant), seed through the API - that is the reference pattern, and this
file is not generated. Builders (`tests/Test.Support/Builders/{Entity}Builder.cs`) construct **domain objects
in memory**; they do not persist a valid FK chain. When tests need prerequisite rows the API never
creates (a real user in a real tenant owning the aggregate), do not duplicate that insert inline - it
drifts per-test and reintroduces the user/tenant FK bugs the dev seam fixes. Provide this one shared
seeder in `Test.Support` that persists the full FK chain in dependency order through the live DbContext.

`tests/Test.Support/SqlAggregateSeeder.cs`:

```csharp
namespace Test.Support;

/// <summary>
/// Persists a valid FK chain (tenant -> user -> aggregate -> children) against a real store via the
/// transactional DbContext, so workflow/E2E tests start from a row the API will accept. Builders
/// construct the domain objects; this seeder owns insert order and FK wiring. Idempotent per id.
/// </summary>
public sealed class SqlAggregateSeeder(IDbContextFactory<{App}DbContextTrxn> factory)
{
    public async Task<SeededContext> SeedAsync(CancellationToken ct = default)
    {
        await using var db = await factory.CreateDbContextAsync(ct);

        // 1. Tenant first (and the user, when the app models users as an entity with an owner FK) -
        //    use the same fixed ids the dev principal/claims use so seeded rows, ScaffoldAuthHandler
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

`tests/Test.Endpoints/CustomApiFactory.cs`:

```csharp
public sealed class CustomApiFactory : WebApplicationFactoryBase<Program, {App}DbContextTrxn, {App}DbContextQuery>
{
    private readonly string _dbName = $"TestDb_{Guid.NewGuid()}";

    protected override DbContextOptions BuildTrxnOptions() =>
        new DbContextOptionsBuilder<{App}DbContextTrxn>().UseInMemoryDatabase(_dbName).Options;

    protected override DbContextOptions BuildQueryOptions() =>
        new DbContextOptionsBuilder<{App}DbContextQuery>().UseInMemoryDatabase(_dbName).Options;
}
```

That's the entire file. The pooled-context swap, interceptor removal, factory plumbing, and reflection-based context creation are inherited.

## Test.E2E derived factory (Testcontainers SQL)

`tests/Test.E2E/SqlApiFactory.cs` is identical except the options use `UseSqlServer(connectionString, sql => sql.UseCompatibilityLevel(170))` and the class manages a static Testcontainers SQL lifecycle (`StartContainerAsync` / `StopContainerAsync`). Full template: [test-templates-e2e.md](test-templates-e2e.md) section SqlApiFactory.

## Multi-resource Integration tier

When a test needs the **full distributed app over HTTP** (the API + audit pipeline across resources, Service Bus -> Function handoffs), do not extend `WebApplicationFactoryBase` - use the lazy `AspireTestHost` mesh fixture in `Test.Aspire` from [test-templates-aspire.md](test-templates-aspire.md). For **one class vs one real store** (repository vs SQL, audit repo vs Azurite), use the standalone Testcontainers fixtures in `Test.Integration` from [test-templates-integration.md](test-templates-integration.md). The WAF base is for HTTP-in-API-out testing.

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

        // Update
        var updateDto = new DefaultRequest<{Entity}Dto>
        {
            Item = new {Entity}Dto { Id = entityId, Name = "Updated", TenantId = tenantId }
        };
        var updateResponse = await client.PutAsJsonAsync($"v1/tenant/{tenantId}/{entities}/{entityId}", updateDto);
        Assert.AreEqual(HttpStatusCode.OK, updateResponse.StatusCode);

        // Delete
        var deleteResponse = await client.DeleteAsync($"v1/tenant/{tenantId}/{entities}/{entityId}");
        Assert.AreEqual(HttpStatusCode.OK, deleteResponse.StatusCode);

        // Verify deleted
        var verifyResponse = await client.GetAsync($"v1/tenant/{tenantId}/{entities}/{entityId}");
        Assert.AreEqual(HttpStatusCode.NotFound, verifyResponse.StatusCode);
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

## Exception Handler Tests

### File: `tests/Test.Endpoints/Middleware/DefaultExceptionHandlerTests.cs`

**Generate this whenever [exception-handler-template](exception-handler-template.md) is generated - it is not optional.** The handler decides by environment whether the client receives `exception.ToString()` (full stack trace, internal type names, file paths) or `exception.Message`. That is an information-disclosure control, so both arms need a test that fails if the environment gate is inverted, widened, or dropped. The handler is a plain class, so test it directly against a `DefaultHttpContext` - no host boot, no HTTP.

```csharp
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging.Abstractions;
using Moq;
using {Host}.Api.Middleware;

namespace Test.Endpoints.Middleware;

/// <summary>
/// Pins the environment gate on <c>ProblemDetails.Detail</c>. Development/Staging may return the full
/// exception; Production must return only the message. Also covers the HasStarted guard, which exists so a
/// second write cannot mask the original exception.
/// </summary>
[TestClass]
[TestCategory("Endpoint")]
public sealed class DefaultExceptionHandlerTests
{
    // Async test class -> declare the instance TestContext and flow TestContext.CancellationToken
    // into every cancellable async call. See ../skills/testing.md Cancellation-Token discipline.
    public TestContext TestContext { get; set; } = null!;

    private readonly Mock<IProblemDetailsService> _problemDetailsServiceMock = new();
    private ProblemDetails? _written;

    [TestInitialize]
    public void Setup()
    {
        _problemDetailsServiceMock
            .Setup(s => s.TryWriteAsync(It.IsAny<ProblemDetailsContext>()))
            .Callback<ProblemDetailsContext>(context => _written = context.ProblemDetails)
            .ReturnsAsync(true);
    }

    [DataTestMethod]
    [DataRow(Environments.Development)]
    [DataRow(Environments.Staging)]
    public async Task Given_NonProductionEnvironment_When_ExceptionHandled_Then_DetailCarriesStackTrace(
        string environmentName)
    {
        // Arrange
        var exception = CaptureThrownException();
        var handler = CreateHandler(environmentName);

        // Act
        var handled = await handler.TryHandleAsync(
            NewHttpContext(), exception, TestContext.CancellationToken);

        // Assert
        Assert.IsTrue(handled);
        Assert.IsNotNull(_written);
        Assert.AreEqual(exception.ToString(), _written!.Detail);
        StringAssert.Contains(_written.Detail!, nameof(CaptureThrownException));  // a real stack frame leaked
    }

    [TestMethod]
    public async Task Given_ProductionEnvironment_When_ExceptionHandled_Then_DetailOmitsStackTrace()
    {
        // Arrange
        var exception = CaptureThrownException();
        var handler = CreateHandler(Environments.Production);

        // Act
        var handled = await handler.TryHandleAsync(
            NewHttpContext(), exception, TestContext.CancellationToken);

        // Assert
        Assert.IsTrue(handled);
        Assert.IsNotNull(_written);
        Assert.AreEqual(exception.Message, _written!.Detail);
        Assert.IsFalse(_written.Detail!.Contains(nameof(CaptureThrownException), StringComparison.Ordinal),
            "Production ProblemDetails must not expose stack frames");
        Assert.IsFalse(_written.Detail.Contains(exception.GetType().FullName!, StringComparison.Ordinal),
            "Production ProblemDetails must not expose internal type names");
    }

    [TestMethod]
    public async Task Given_ResponseAlreadyStarted_When_ExceptionHandled_Then_NothingIsWritten()
    {
        // Arrange - a started response cannot take a body; writing one would throw and mask the original.
        var context = NewHttpContext(responseHasStarted: true);
        var handler = CreateHandler(Environments.Production);

        // Act
        var handled = await handler.TryHandleAsync(
            context, new InvalidOperationException("boom"), TestContext.CancellationToken);

        // Assert
        Assert.IsTrue(handled);
        _problemDetailsServiceMock.Verify(
            s => s.TryWriteAsync(It.IsAny<ProblemDetailsContext>()), Times.Never);
    }

    private DefaultExceptionHandler CreateHandler(string environmentName) =>
        new(NullLogger<DefaultExceptionHandler>.Instance,
            new TestHostEnvironment { EnvironmentName = environmentName },
            _problemDetailsServiceMock.Object);

    /// <summary>Throws and catches so <c>StackTrace</c> is populated - a constructed exception has none.</summary>
    private static Exception CaptureThrownException()
    {
        try
        {
            throw new InvalidOperationException("boom");
        }
        catch (InvalidOperationException ex)
        {
            return ex;
        }
    }

    private static DefaultHttpContext NewHttpContext(bool responseHasStarted = false)
    {
        var context = new DefaultHttpContext { TraceIdentifier = "request-123" };
        if (responseHasStarted)
        {
            // HasStarted is driven by the response feature, not settable on DefaultHttpContext.
            // Swap the feature before touching Response, or the body set here is discarded with it.
            context.Features.Set<IHttpResponseFeature>(new StartedResponseFeature());
        }

        context.Request.Method = HttpMethods.Get;
        context.Request.Path = "/failure";
        context.Response.Body = new MemoryStream();
        return context;
    }

    private sealed class TestHostEnvironment : IHostEnvironment
    {
        public string EnvironmentName { get; set; } = Environments.Production;
        public string ApplicationName { get; set; } = nameof(Test.Endpoints);
        public string ContentRootPath { get; set; } = AppContext.BaseDirectory;
        public IFileProvider ContentRootFileProvider { get; set; } = new NullFileProvider();
    }

    private sealed class StartedResponseFeature : HttpResponseFeature
    {
        public override bool HasStarted => true;
    }
}
```

Add one `[DataTestMethod]` over the *Exception-to-Status Mapping* table in [exception-handler-template](exception-handler-template.md) as each mapping is added - one `DataRow` per exception type asserting `context.Response.StatusCode`. Keep correlation assertions (`requestId` separate from W3C `traceId`/`spanId`) in whichever test already boots a real host; they need the registered `CustomizeProblemDetails` callback, which this class replaces with a mock.

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

## Test Configuration

### File: `tests/Test.Endpoints/appsettings-test.json`

```json
{
  "TestSettings": {
    "DBSource": "UseInMemoryDatabase",
    "DBName": "Test.Endpoints.TestDB"
  }
}
```

---

## Contention/Concurrency Scenario (Optional)

For high-contention domains (inventory, reservations, financial flows), add:

```csharp
[TestCategory("Endpoint")]
[TestMethod]
public async Task Given_ConcurrentUpdates_When_Executed_Then_OptimisticConcurrencyEnforced()
{
    // Run parallel operations against the same entity
    // Assert: no duplicate side effects, concurrency behavior enforced
}
```
