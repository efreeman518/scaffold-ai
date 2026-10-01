# Test Templates - Aspire / Mesh (Phase 5b, on-demand)

| | |
|---|---|
| **Generates** | `tests/Test.Aspire/AspireTestHost.cs`, `tests/Test.Aspire/AspireMeshLifecycle.cs`, `tests/Test.Aspire/AssemblyInfo.cs`, `tests/Test.Aspire/OutboxMeshTests.cs` (when an outbox is generated), `tests/Test.Aspire/ApiAuditPipelineTests.cs` + `FunctionAuditPipelineTests.cs` (`Azure` arm), Blazor-mesh smoke (when `includeBlazorUI`), `tests/Test.Aspire/Test.Aspire.csproj` |
| **Requires** | an Aspire AppHost project, [test-templates-integration.md](test-templates-integration.md) (the component tier this splits from; section Lane switch owns `TestHostingLane`), `Aspire.Hosting.Testing` on Aspire-backed consumers, EF.IntegrationTesting.Aspire (host context) and EF.Testing (environment helpers) |
| **Phase** | Host + lifecycle shells in Phase 4; mesh tests filled in Phase 5b (and Phase 5c for opt-in hosts: scheduler/worker, Functions, Blazor) |
| **Protocol** | Tests-after - the mesh tier verifies the production AppHost graph end-to-end once the component and endpoint tiers pin behavior. |

## Why this tier exists

`Test.Aspire` is the **mesh** tier - it boots the **production AppHost graph in-process** for the resolved lane (API, dispatcher/consumer host, database, broker, storage) via `DistributedApplicationTestingBuilder` and drives it over **HTTP**. It is the only tier that exercises the full service mesh: `HTTP -> API -> outbox -> broker -> consumer -> inbox/projection row`. Use it for:

- Outbox -> broker -> every bound consumer, asserted on the consumers' inbox rows.
- `Azure` arm: API and Functions requests -> audit middleware -> Azurite Table row, with polling read-back.
- Blazor-mesh smoke (Gateway routing + Refit + tenant header) when `includeBlazorUI: true`.

Placement against the component tier: [../skills/testing.md](../skills/testing.md) section Component vs Mesh split. The mesh graph costs ~60-90 s on warm Docker (minutes cold), so it boots **once per run**, only when a mesh test executes.

## One AppHost Graph Per Mesh Run

Canonical rule: [../skills/testing.md](../skills/testing.md#heavy-aspire-mesh-graph-rule) (**Heavy Aspire Mesh Graph Rule**). In short: one assembly-scoped `AspireTestHost` graph per mesh run; prove opt-in branches with a cheap topology guard, never a second `DistributedApplicationTestingBuilder` in a test class, and push live-provider behavior to a lighter lane.

## Lazy startup + lifecycle

Rule: [../skills/testing.md](../skills/testing.md) section Lazy Aspire Fixture Startup (canonical for `Test.Aspire`) - `EnsureStartedAsync` from each mesh class's `[ClassInitialize]`, teardown once in `AspireMeshLifecycle.[AssemblyCleanup]`. All mesh tests are `[DoNotParallelize]`.

> **Naming:** `AspireTestHost` (not `DatabaseFixture`). The fixture owns the full distributed application - database, broker, hosts, storage, lifecycle - and the name reflects that. It can stay `internal` (consumed only within `Test.Aspire`).

## Shared Aspire test-host context

`AspireTestHostContext` (EF.IntegrationTesting.Aspire) owns the Docker preflight, one cumulative startup budget, named resource waits with state diagnostics, and bounded stop and dispose; `EnvironmentVariableScope`, `TestEnvironment` and `FunctionsCoreToolsDiscovery` come from EF.Testing (`EF.Testing.Environment`). Mesh, admin/browser, and WasmUI fixtures construct the package context instead of generating lifecycle code, and component Testcontainers fixtures call `DockerRuntimePreflight.GetUnavailableReasonAsync` (EF.Testing) without an AppHost dependency. The package references no test framework: thin MSTest adapters alone translate an explicit opt-out or the Docker-unavailable reason to `Assert.Inconclusive`. Optional Azure `LiveAI` performs provider eligibility before calling the shared host, as specified below.

Usage rules:

1. Construct it once per graph: `new AspireTestHostContext(TestEnvironment.GetPositiveSeconds("{APP}_ASPIRE_STARTUP_TIMEOUT_SECONDS", TimeSpan.FromSeconds(900)), new AspireTestHostOptions { IncludeResourceLogs = TestEnvironment.IsTrue("{APP}_ASPIRE_RESOURCE_LOGGING") })`. The budget starts at construction.
2. Run every startup step through `RunStartupStepAsync`, which grants only the remaining budget; a step's own exception, including its own timeout, propagates unchanged.
3. `Attach` the built `DistributedApplication` before `WaitForResourceHealthyAsync`; a failed wait writes the resource's state, health, exit code and start/stop times before rethrowing. Resource logs are added only when `IncludeResourceLogs` is set.
4. `StopAndDisposeAsync` bounds stop and dispose together. Restore fixture-owned environment in a caller `finally` even when cleanup fails.

---

## AspireTestHost

### File: `tests/Test.Aspire/AspireTestHost.cs`

```csharp
using Aspire.Hosting;
using Aspire.Hosting.Testing;
using AppHost;
using EF.IntegrationTesting.Aspire;
using EF.Testing.Environment;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using {Project}.Hosting;
using Test.Support.Hosting;

namespace Test.Aspire;

/// <summary>
/// Lazy assembly-scoped fixture that starts the full Aspire AppHost graph for the resolved lane (NonAzure
/// unless {APP}_LANE=Azure) the first time a mesh test class calls <see cref="EnsureStartedAsync"/> from
/// <c>[ClassInitialize]</c>. Mesh tier (Aspire.Hosting.Testing) - the only tier that exercises the full
/// service mesh, which no lighter tier reproduces. Teardown runs once via
/// <c>AspireMeshLifecycle.[AssemblyCleanup]</c>. The package AspireTestHostContext owns the Docker
/// preflight, cumulative startup deadline, named waits, diagnostics, and bounded cleanup.
/// </summary>
internal static class AspireTestHost
{
    /// <summary>
    /// Internal diagnostic switch (NOT a test-selection opt-in). Resource logging is off by default to keep
    /// TRX output readable; set <c>{APP}_ASPIRE_RESOURCE_LOGGING=true</c> only while diagnosing a startup or
    /// routing failure. Document it under troubleshooting, never in the normal test opt-in surface.
    /// </summary>
    internal const string ResourceLoggingEnvironmentVariable = "{APP}_ASPIRE_RESOURCE_LOGGING";

    /// <summary>Guards the lazy single-start so concurrent <c>[ClassInitialize]</c> calls boot the graph once.</summary>
    private static readonly SemaphoreSlim Gate = new(1, 1);

    private static EnvironmentVariableScope? _environment;
    private static AspireTestHostContext? _hostContext;
    internal static string ConnectionString = null!;
    internal static TimeSpan DefaultTimeout => _hostContext?.RemainingStartupBudget ?? StartupBudget;

    private static TimeSpan StartupBudget =>
        TestEnvironment.GetPositiveSeconds("{APP}_ASPIRE_STARTUP_TIMEOUT_SECONDS", TimeSpan.FromSeconds(900));

    /// <summary>Shared Aspire app started once for all mesh tests.</summary>
    internal static DistributedApplication? AspireApp { get; private set; }

    /// <summary>
    /// Starts the Aspire graph on first call and returns immediately afterwards. Mesh test classes call this
    /// from <c>[ClassInitialize]</c> so the ~60-90 s boot is paid only when a mesh test runs.
    /// </summary>
    internal static async Task EnsureStartedAsync(TestContext context)
    {
        if (AspireApp is not null)
            return;

        if (TestEnvironment.IsFalse("{APP}_RUN_ASPIRE_TESTS"))
        {
            Assert.Inconclusive("{APP}_RUN_ASPIRE_TESTS=false - Aspire mesh tier opted out.");
            return;
        }

        await Gate.WaitAsync(context.CancellationToken);
        try
        {
            if (AspireApp is not null)
                return;

            _hostContext = new AspireTestHostContext(
                StartupBudget,
                new AspireTestHostOptions { IncludeResourceLogs = TestEnvironment.IsTrue(ResourceLoggingEnvironmentVariable) });
            var dockerUnavailable = await _hostContext.GetDockerUnavailableReasonAsync(context.CancellationToken);
            if (dockerUnavailable is not null)
            {
                _hostContext = null;
                Assert.Inconclusive(dockerUnavailable);
                return;
            }

            try
            {
                await StartAsync(context.CancellationToken);
            }
            catch
            {
                await _hostContext.DumpResourceDiagnosticsAsync(
                    ["{app}db", "{app}migrator", "{app}api", "{app}gateway"], CancellationToken.None);

                try { await StopAsync(CancellationToken.None); }
                catch (Exception cleanupException) { Console.Error.WriteLine($"Cleanup also failed: {cleanupException.Message}"); }
                throw;
            }
        }
        finally
        {
            Gate.Release();
        }
    }

    private static async Task StartAsync(CancellationToken ct)
    {
        var hostContext = _hostContext ?? throw new InvalidOperationException("Aspire host context is not initialized.");
        // AppHost.cs reads these via Environment.GetEnvironmentVariable, so they must be process env vars.
        _environment = new EnvironmentVariableScope()
            .Set("{APP}_ASPIRE_TESTING", "true");

        if (!TestEnvironment.IsFalse("{APP}_RUN_FUNCTIONS_TESTS") && EnsureFuncToolAvailable())
            _environment.Set("{APP}_INCLUDE_FUNCTIONS", "true");

        var appHostProgramType = Type.GetType("Program, AppHost", throwOnError: true)!;

        var builder = await hostContext.RunStartupStepAsync(
            "create Aspire mesh test host",
            token => DistributedApplicationTestingBuilder.CreateAsync(
                appHostProgramType,
                args: [],
                configureBuilder: (appOptions, hostSettings) =>
                {
                    appOptions.DisableDashboard = true;
                    appOptions.EnableResourceLogging = hostContext.IncludeResourceLogs;
                    hostSettings.Configuration ??= new();
                    // One shared local password backs the lane's database parameter.
                    hostSettings.Configuration[TestHostingLane.Current.Lane == HostingLane.Azure
                        ? "Parameters:sql-password" : "Parameters:postgres-password"] = LocalSqlSettings.SharedSaPassword;
                },
                cancellationToken: token),
            ct);

        builder.Services.AddLogging(logging =>
        {
            logging.SetMinimumLevel(LogLevel.Information);
            logging.AddFilter("Microsoft.AspNetCore", LogLevel.Warning);
            logging.AddFilter("Aspire.", LogLevel.Warning);
        });

        AspireApp = await hostContext.RunStartupStepAsync("build Aspire mesh test host", token => builder.BuildAsync(token), ct);
        hostContext.Attach(AspireApp);
        await hostContext.RunStartupStepAsync("start Aspire mesh test host", token => AspireApp.StartAsync(token), ct);

        await hostContext.WaitForResourceHealthyAsync("{app}db", ct);

        ConnectionString = await hostContext.RunStartupStepAsync(
            "resolve {app}db connection string",
            token => AspireApp.GetRequiredConnectionStringAsync("{app}db", hostContext.RemainingStartupBudget, token),
            ct);
    }

    /// <summary>Stops and disposes the graph (if started) and restores env vars. Invoked once by AspireMeshLifecycle.</summary>
    internal static async Task StopAsync(CancellationToken ct)
    {
        var hostContext = _hostContext;
        try
        {
            if (hostContext is not null)
                await hostContext.StopAndDisposeAsync(ct);
        }
        finally
        {
            AspireApp = null;
            _hostContext = null;
            _environment?.Dispose();
            _environment = null;
        }
    }

    /// <summary>Waits for a named Aspire resource within the one cumulative startup deadline.</summary>
    internal static Task WaitForResourceHealthyAsync(string resourceName, CancellationToken cancellationToken = default)
    {
        var hostContext = _hostContext ?? throw new InvalidOperationException("Aspire host context is not initialized.");
        return hostContext.WaitForResourceHealthyAsync(resourceName, cancellationToken);
    }

    /// <summary>Checks if Azure Functions Core Tools (func.exe) is available on PATH.</summary>
    internal static bool EnsureFuncToolAvailable() => FunctionsCoreToolsDiscovery.EnsureFuncToolAvailable();

    /// <summary>A mesh class whose resources exist on one lane reports the lane instead of timing out.</summary>
    internal static void RequireLaneOrInconclusive(HostingLane lane)
    {
        if (TestHostingLane.Current.Lane != lane)
            Assert.Inconclusive($"Requires {APP}_LANE={lane}; current lane is {TestHostingLane.Current.Lane}.");
    }
}
```

### File: `tests/Test.Aspire/AspireMeshLifecycle.cs`

```csharp
namespace Test.Aspire;

/// <summary>
/// Assembly lifecycle for the mesh tier. The graph is started lazily by
/// <c>AspireTestHost.EnsureStartedAsync</c> from each mesh test class's <c>[ClassInitialize]</c>, so the
/// <c>[AssemblyInitialize]</c> here is intentionally a no-op. <c>[AssemblyCleanup]</c> stops and disposes
/// the graph exactly once, regardless of which mesh class warmed it up.
/// </summary>
[TestClass]
public class AspireMeshLifecycle
{
    [AssemblyInitialize]
    public static void AssemblyInit(TestContext _) { }

    [AssemblyCleanup]
    public static Task AssemblyCleanup(TestContext context) => AspireTestHost.StopAsync(context.CancellationToken);
}
```

### File: `tests/Test.Aspire/AssemblyInfo.cs`

```csharp
[assembly: DoNotParallelize]
```

### Aspire fixture non-negotiables

The shared rules - lazy single start, `Parameters:*` via `configureBuilder.hostSettings.Configuration`, scoped env vars, one startup deadline, health before use, bounded cleanup, the distinct `Aspire` category - are owned by [../skills/testing.md](../skills/testing.md) section Aspire Test Host (recipe) and its One Startup Budget. This fixture adds:

1. **Graph choices are baked in.** `{APP}_ASPIRE_TESTING`, `{APP}_INCLUDE_FUNCTIONS`, and the lane are read at graph construction, so they cannot be re-flipped per test; never add an explicitly opted-out Functions/UI resource. A test that needs a different provider/config builds its own isolated graph (see [ai-integration.md](../skills/ai-integration.md) section Deciding the Live Lane).
2. **`{APP}_ASPIRE_STARTUP_TIMEOUT_SECONDS`** defaults to 900 s and is read once when the context starts.
3. **Default-on, narrow inconclusive boundary for required mesh infrastructure** - honour `{APP}_RUN_ASPIRE_TESTS=false` and failed Docker preflight with precise `Assert.Inconclusive` messages. Docker success means AppHost/container/create/build/start/readiness failures are red after state diagnostics. Fast CI lanes set the explicit opt-out when they intentionally exclude the tier. Optional Azure `LiveAI` uses the pre-host eligibility exception owned by [../skills/ai-integration.md](../skills/ai-integration.md).
4. **Test containers are ephemeral; the SDK owns teardown.** The AppHost gates `ContainerLifetime.Persistent` + `WithDataVolume` on `!IsAspireTesting()` (see [../skills/aspire.md](../skills/aspire.md), Rules), so the graph this fixture boots uses **ephemeral** containers. `AspireApp.StopAsync()`/`DisposeAsync()` in `AspireTestHost.StopAsync` removes **exactly** the containers this run started. **Never** add a `docker rm` sweep filtered by image, name prefix, or the generic `com.microsoft.dotnet.aspire.container.name` label - that deletes other projects' and sessions' containers, including intentional persistent stacks. The mesh tier needs no Docker cleanup beyond `DisposeAsync`.

When Functions is in the graph, its project must override the Functions SDK's relative `RunWorkingDirectory` with an absolute path per [../skills/function-app.md](../skills/function-app.md) section Make the local Functions run directory absolute. Do not call `WithWorkingDirectory(...)` on `AzureFunctionsProjectResource`; that extension only supports executable resources. A Running resource whose proxy returns 500 because Core Tools never bound its port is a host startup failure, not an inconclusive prerequisite gap.

### State diagnostics on by default; resource logs optional

Resource logging floods the TRX and buries the real failure, so it stays **off by default**. The package context writes resource state (from `ResourceNotifications`, which works with logging off) on every failed wait and on `DumpResourceDiagnosticsAsync`; resource logs join only when `IncludeResourceLogs` is set, bounded by `ResourceLogLimit`, and a log read failure is written as a line, never thrown.

### Cleanup: ephemeral-by-default, per-run label only as a fallback

The default needs no Docker commands at all - ephemeral test containers are torn down by `DisposeAsync` (non-negotiable 4). Only a project that **must** keep persistent lifetime under test (rare - e.g. a slow emulator reused across runs) adds explicit cleanup, scoped to this run's exact ownership:

1. Generate one run id in the test host.
2. Pass it to the AppHost through `hostSettings.Configuration` (the same channel as the database password parameter in `StartAsync`), e.g. `hostSettings.Configuration["Parameters:test-run-id"] = runId;`.
3. In the AppHost, under `IsAspireTesting()`, stamp each test-owned container: `c.WithContainerRuntimeArgs("--label", $"{app}.aspire.test-run-id={runId}")`.
4. In `AspireMeshLifecycle.[AssemblyCleanup]`, **after** `StopAsync`/`DisposeAsync`, remove only the matching run: `docker ps -aq --filter "label={app}.aspire.test-run-id=<runId>"` -> `docker rm -f`.

Never sweep old stopped containers unless the developer explicitly asks for machine-level Docker cleanup.

### Required-mesh opt-out + Docker preflight

The required mesh tier is default-on so Test Explorer discovers it. Inconclusive versus red follows the prerequisite rule in [../skills/testing.md](../skills/testing.md#never-silently-pass-applies-to-every-tier). The thin MSTest adapter translates the opt-out and Docker preflight - the package `AspireTestHostContext` returns the Docker reason and never depends on MSTest - and `EnsureStartedAsync` (above) runs the `{APP}_RUN_ASPIRE_TESTS=false` check and the shared Docker preflight, so a mesh class's `[ClassInitialize]` is only `AspireTestHost.EnsureStartedAsync(context)`. It never catches AppHost startup/readiness failures as availability; those dump diagnostics and propagate red.

### Optional Azure LiveAI eligibility before host creation

When AI is generated, the Azure `LiveAI` class must check provider eligibility before it can call `AspireTestHost.EnsureStartedAsync`. `{APP}_RUN_AZURE_FOUNDRY_TESTS=false` is a fast opt-out, not a required flag when Azure configuration is absent.

```csharp
[ClassInitialize]
public static async Task ClassInit(TestContext context)
{
    if (string.Equals(
        Environment.GetEnvironmentVariable("{APP}_RUN_AZURE_FOUNDRY_TESTS"),
        "false",
        StringComparison.OrdinalIgnoreCase))
    {
        Assert.Inconclusive("{APP}_RUN_AZURE_FOUNDRY_TESTS=false - Azure live AI opted out.");
        return;
    }

    var unavailable = AzureFoundryTestEligibility.GetUnavailableReason();
    if (unavailable is not null)
    {
        Assert.Inconclusive(unavailable);
        return;
    }

    await AspireTestHost.EnsureStartedAsync(context);
}
```

Generate `AzureFoundryTestEligibility` as a thin, process-only preflight. It loads the same environment/user-secret inputs the AppHost consumes and calls the same pure Azure-selection predicate. If selection is currently inline in AppHost `Program.cs`, extract one pure predicate and reuse it; do not duplicate a second heuristic in tests. The preflight must not create `DistributedApplicationTestingBuilder`, call `EnsureStartedAsync`, query `/api/v1/ai/status`, authenticate, or call a model. Missing selection inputs return a precise unavailable reason. Once eligible, startup/authentication/provider/status/routing/HTTP/JSON/schema/contract failures stay red. Full classification: [../skills/ai-integration.md](../skills/ai-integration.md) section Optional Live-Provider Classification.

---

## Outbox Mesh Test

End-to-end: `POST /api/{entities}` -> the create stages an outbox row -> the dispatcher publishes it -> every consumer bound to the event records its inbox row. Asserts those rows in the lane's database, never the broker ([../skills/testing.md](../skills/testing.md) section Assertion Surface - Prefer Downstream Effects). The dispatcher/consumer host joins the test graph only through its opt-in flag.

### File: `tests/Test.Aspire/OutboxMeshTests.cs`

```csharp
using System.Net;
using System.Net.Http.Json;
using Aspire.Hosting.Testing;
using EF.Common.Contracts;
using Microsoft.EntityFrameworkCore;
using {Project}.Application.Models;
using {Project}.Infrastructure.Data;
using Test.Support.Hosting;

namespace Test.Aspire;

/// <summary>
/// The durable-messaging mesh: an HTTP create stages an outbox row, the dispatcher publishes it, and every
/// consumer bound to the event records its inbox row once. Mesh tier (Aspire.Hosting.Testing) - API,
/// dispatcher/consumer host, broker, and database in one graph; the inbox rows are the downstream effect.
/// Manual run (Docker must be running):
///   dotnet test tests/Test.Aspire/Test.Aspire.csproj --filter TestCategory=Aspire -m:1
/// Set {APP}_RUN_ASPIRE_TESTS=false to skip the mesh tier (e.g. in fast CI lanes).
/// </summary>
[TestClass]
[TestCategory("Aspire")]
[DoNotParallelize]
public class OutboxMeshTests
{
    private static readonly TimeSpan MeshBudget = TimeSpan.FromMinutes(3);

    public TestContext TestContext { get; set; } = null!;

    /// <summary>Boots the Aspire graph lazily on first mesh-test class to run; teardown is owned by <c>AspireMeshLifecycle</c>.</summary>
    [ClassInitialize]
    public static Task ClassInit(TestContext context) => AspireTestHost.EnsureStartedAsync(context);

    [TestInitialize]
    public void TestSetup()
    {
        if (Environment.GetEnvironmentVariable("{APP}_ASPIRE_SCHEDULER_AVAILABLE") != "true")
            Assert.Inconclusive("{APP}_ASPIRE_SCHEDULER_AVAILABLE is not true, so no outbox dispatcher runs in this graph.");
    }

    [TestMethod]
    [Timeout(1_200_000, CooperativeCancellation = true)]
    public async Task Given_{Entity}CreatedOverHttp_When_MeshDrains_Then_EveryConsumerRecordsItExactlyOnce()
    {
        var ct = TestContext.CancellationToken;
        await AspireTestHost.WaitForResourceHealthyAsync("{app}api", ct);
        using var client = AspireTestHost.AspireApp!.CreateHttpClient("{app}api");

        // Correlate on inbox rows, not on the outbox row: the dispatcher removes it once sent.
        var before = await InboxMessageIdsAsync(ct);
        using var response = await client.PostAsJsonAsync("api/v1/{entities}",
            new DefaultRequest<{Entity}Dto> { Item = new {Entity}Dto { Name = $"mesh-{Guid.NewGuid():N}" } }, ct);
        Assert.AreEqual(HttpStatusCode.Created, response.StatusCode, await response.Content.ReadAsStringAsync(ct));

        string[] expected = [/* the name of every consumer bound to {Entity}CreatedEvent */];
        List<string> consumers = [];
        var deadline = DateTimeOffset.UtcNow + MeshBudget;
        while (consumers.Count < expected.Length && DateTimeOffset.UtcNow < deadline)
        {
            await using var db = CreateContext();
            var rows = await db.ConsumerInbox.AsNoTracking().Select(i => new { i.MessageId, i.Consumer }).ToListAsync(ct);
            var group = rows.Where(r => !before.Contains(r.MessageId)).GroupBy(r => r.MessageId)
                .FirstOrDefault(g => g.Count() >= expected.Length);
            if (group is not null) consumers = [.. group.Select(r => r.Consumer)];
            else await Task.Delay(TimeSpan.FromSeconds(2), ct);
        }

        CollectionAssert.AreEquivalent(expected, consumers,
            "every bound consumer records the event once; otherwise the outbox never drained or a binding never delivered");
    }

    private static async Task<HashSet<Guid>> InboxMessageIdsAsync(CancellationToken ct)
    {
        await using var db = CreateContext();
        return [.. await db.ConsumerInbox.AsNoTracking().Select(i => i.MessageId).ToListAsync(ct)];
    }

    private static {App}DbContextTrxn CreateContext() =>
        new(new DbContextOptionsBuilder<{App}DbContextTrxn>()
            .Use{App}Provider(TestHostingLane.DatabaseProvider, AspireTestHost.ConnectionString)
            .Options) { AuditId = "mesh-test" };
}
```

RabbitMQ replay and malformed-body handling are proven in the component tier (`RabbitMqTransportTests`, the inbox test) and the package's broker tests.

> **Azure arm:** Service Bus consumers run in the Functions host, so the class follows the `FunctionAuditPipelineTests` rule below for a missing `func`. Add a replay leg (republish the same `MessageId` through a `ServiceBusSender` and assert the inbox still holds one row per consumer) and a malformed-body test that finds the message on the projection subscription's dead-letter sub-queue with the envelope reader's malformed reason. The audit pipeline tests exist only on this arm: `ApiAuditPipelineTests` posts through `{app}api` and polls `AuditLogTableEntity` (EF.Audit.AzureTable) rows in `TableStorage1` (a `TableServiceClient` over `GetRequiredConnectionStringAsync("TableStorage1", ...)`) over the tenant's partition-key range (`{tenantId}|{yyyyMMdd}` partitions) inside the request's time window, treating a 404 before the table exists as not-yet-written, behind `AspireTestHost.RequireLaneOrInconclusive(HostingLane.Azure)`. The default lane's relational audit is proven in the component tier.

---

## Other mesh tests (generate when the host is enabled)

- **`FunctionAuditPipelineTests`** (`Azure` arm, `includeFunctions`): the `ApiAuditPipelineTests` shape against the `{app}functions` resource. An explicit `{APP}_RUN_FUNCTIONS_TESTS=false` opts out before graph construction; when `AspireTestHost.EnsureFuncToolAvailable()` finds no `func`, the class is `Inconclusive` with the Core Tools install command, and a Functions host that fails to start is red ([../skills/testing.md](../skills/testing.md#never-silently-pass-applies-to-every-tier) prerequisite rule). Functions has the longest cold-start; its coarse MSTest `[Timeout]` must exceed the configurable global startup budget plus assertion time (for a 900 s startup default, use at least 1200 s).
- **Blazor-mesh smoke** (`includeBlazorUI`): `tests/Test.Aspire/BlazorMeshSmokeTests`. Opt the Blazor resource into the graph via `{APP}_INCLUDE_BLAZOR=true` and hit one page that round-trips through the API (Gateway routing + Refit + tenant header). Calls `AspireTestHost.EnsureStartedAsync` from `[ClassInitialize]`.

---

## Project file

### File: `tests/Test.Aspire/Test.Aspire.csproj`

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <IsTestProject>true</IsTestProject>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="MSTest" />
    <PackageReference Include="Aspire.Hosting.Testing" />
    <PackageReference Include="EF.IntegrationTesting" />
    <PackageReference Include="EF.IntegrationTesting.Aspire" />
  </ItemGroup>
  <ItemGroup>
    <Using Include="Microsoft.VisualStudio.TestTools.UnitTesting" />
  </ItemGroup>
  <ItemGroup>
    <ProjectReference Include="..\Test.Support\Test.Support.csproj" />
    <ProjectReference Include="..\..\src\Host\{Host}.Api\{Host}.Api.csproj" />
    <ProjectReference Include="..\..\src\Application\{Project}.Application.Models\{Project}.Application.Models.csproj" />
    <ProjectReference Include="..\..\src\Infrastructure\{Project}.Infrastructure.Data\{Project}.Infrastructure.Data.csproj" />
    <ProjectReference Include="..\..\src\Host\Aspire\AppHost\AppHost.csproj" AdditionalProperties="SkipUnoWasmBuild=true" />
  </ItemGroup>
</Project>
```

> **Azure arm:** add `Aspire.Hosting.Azure.Storage`, `Azure.Data.Tables`, `Azure.Messaging.ServiceBus`, and the `Infrastructure.Storage` reference.

> **`SkipUnoWasmBuild=true` on the AppHost reference.** When the AppHost registers a Uno WASM wrapper host (`{Project}.Uno.WasmHost`), referencing AppHost transitively drags in the Uno WASM build - minutes of `wasm-tools` work that a mesh test never needs. Pass `AdditionalProperties="SkipUnoWasmBuild=true"` on **every** test project that references AppHost (`Test.Aspire`, the C# `Test.PlaywrightUI` host) so they compile fast without forcing the browser-asset build. Omit it only when the scaffold has no Uno UI. The full-solution build still produces the WASM assets - this flag scopes out the cost for AppHost-referencing *test* projects, not the solution.

---

## Verification

- [ ] `Test.Aspire` references `AppHost` and `Aspire.Hosting.Testing`; it is registered in the solution.
- [ ] `AspireTestHost` (named for what it wraps) is lazy (`EnsureStartedAsync` + `SemaphoreSlim`) and called from every mesh class's `[ClassInitialize]`; `AspireMeshLifecycle.[AssemblyCleanup]` stops/disposes the graph once within one bounded deadline.
- [ ] Mesh and Playwright/WasmUI adapters construct the package `AspireTestHostContext`; no generated code duplicates Docker probing, deadlines, state dumps, or cleanup.
- [ ] `Parameters:*` passed via `configureBuilder.hostSettings.Configuration`; env vars scoped + restored.
- [ ] Multi-resource pipeline tests assert against the **downstream persistent effect** (inbox, audit, or projection row), not the bus/queue; lane-specific classes call `RequireLaneOrInconclusive`.
- [ ] Every mesh test carries `[TestCategory("Aspire")]` (not `Integration`); `--filter TestCategory=Integration` boots **no** graph.
- [ ] Mesh classification follows the testing.md prerequisite rule: opt-out, failed Docker preflight, or a missing tool is inconclusive with its enabling command; AppHost/container/start/readiness failures dump diagnostics and fail.
- [ ] Azure `LiveAI` checks the app's shared provider-selection predicate before `AspireTestHost.EnsureStartedAsync`; missing optional Azure configuration is inconclusive without booting the graph, while eligible-provider failures stay red per `skills/ai-integration.md`.
- [ ] Test-booted containers are **ephemeral** (AppHost gates persistent lifetime + data volume on `!IsAspireTesting()`); cleanup is `DisposeAsync` only - no `docker rm` sweep by image, name prefix, or the generic `com.microsoft.dotnet.aspire.container.name` label.
- [ ] `EnableResourceLogging` and `IncludeResourceLogs` default to **false**; the `{APP}_ASPIRE_RESOURCE_LOGGING=true` override enables both.

---

**TaskFlow proof (local):**
- `../scaffold-proof/tests/Test.Aspire/AspireTestHost.cs`
- `../scaffold-proof/tests/Test.Aspire/AspireMeshLifecycle.cs`
- `../scaffold-proof/tests/Test.Aspire/OutboxMeshTests.cs`
- `../scaffold-proof/tests/Test.Aspire/ApiAuditPipelineTests.cs` (Azure arm)
- `../scaffold-proof/tests/Test.Aspire/FunctionAuditPipelineTests.cs` (Azure arm)

**TaskFlow proof (remote fallback):**
<https://github.com/efreeman518/scaffold-proof/tree/main/tests/Test.Aspire>
