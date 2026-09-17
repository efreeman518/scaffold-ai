# Infrastructure Wiring Patterns

Cross-project wiring for caching and Aspire orchestration. Load in Phase 5b when runtime services are enabled. Reload in Phase 5c only when an enabled optional host needs shared infrastructure wiring.

For base types used here, see [../support/ef-packages-reference.md](../support/ef-packages-reference.md).

---

## Multi-Cache Configuration

**Owner:** [../skills/caching.md](../skills/caching.md) section Registration Pattern (Bootstrapper) owns the FusionCache multi-cache registration - named caches, entry-option defaults bound from `CacheSettings`, and the conditional Redis L2 + backplane - loaded in the same Phase 5b session. It is a Bootstrapper DI concern co-located with the `CacheSettings` model it binds; do not restate the loop here.

---

## ServiceDefaults Configuration

**Source:** `Host/Aspire/ServiceDefaults/Extensions.cs`

**Every server-hosted .NET host calls `builder.AddServiceDefaults(...)` as the first registration step** - not just the API-shaped hosts. This includes the UI hosts: **Blazor Server and the Uno `WasmHost`** are server-hosted .NET processes and MUST participate in the shared telemetry pipeline. The full set: API, Gateway, Scheduler, Functions, DatabaseMigrator, Blazor Server, Uno WasmHost. A host left out of `AddServiceDefaults` emits no traces/metrics/logs and is invisible in the telemetry backend. This extension lives in the shared ServiceDefaults project and wires OpenTelemetry, health checks, service discovery, and HTTP resilience defaults.

```csharp
public static IHostApplicationBuilder AddServiceDefaults(
    this IHostApplicationBuilder builder,
    IConfiguration config,
    string appName)
{
    builder.ConfigureOpenTelemetry();
    builder.AddDefaultHealthChecks();
    builder.Services.AddServiceDiscovery();
    builder.Services.ConfigureHttpClientDefaults(http =>
    {
        http.AddStandardResilienceHandler();
        http.AddServiceDiscovery();
    });
    return builder;
}
```

**Rules:**
- Call once per host, before any other service registration.
- Do not duplicate OpenTelemetry or health check setup in individual hosts - ServiceDefaults owns it.
- `AddDefaultHealthChecks()` registers `"self"` tagged `"live"`; host-specific dependencies are tagged `"ready"`.
- Add domain-specific readiness checks (SQL, Redis) in host registration, not in ServiceDefaults.

### Telemetry Export (`ConfigureOpenTelemetry`)

`ConfigureOpenTelemetry` registers instrumentation (metrics + tracing + logging) and then wires exporters, each **gated on a connection string** so local runs work with zero Azure resources and cloud export lights up the moment the setting is present:

```csharp
public static IHostApplicationBuilder ConfigureOpenTelemetry(this IHostApplicationBuilder builder)
{
    builder.Logging.AddOpenTelemetry(o => { o.IncludeFormattedMessage = true; o.IncludeScopes = true; });

    // Functions worker: skip ASP.NET Core request instrumentation (see below) but keep everything else.
    var suppressAspNetCore = string.Equals(
        builder.Configuration["{APP}_SUPPRESS_ASPNETCORE_INSTRUMENTATION"], "true", StringComparison.OrdinalIgnoreCase);

    builder.Services.AddOpenTelemetry()
        .WithMetrics(m => { m.AddHttpClientInstrumentation().AddRuntimeInstrumentation();
                            if (!suppressAspNetCore) m.AddAspNetCoreInstrumentation(); })
        .WithTracing(t => { t.AddHttpClientInstrumentation();
                            if (!suppressAspNetCore) t.AddAspNetCoreInstrumentation(); });

    // OTLP -> Aspire dashboard locally (present via ASPIRE injected env).
    if (!string.IsNullOrWhiteSpace(builder.Configuration["OTEL_EXPORTER_OTLP_ENDPOINT"]))
        builder.Services.AddOpenTelemetry().UseOtlpExporter();

    // Azure Monitor (Application Insights) in cloud - gated on the connection string only.
    if (!string.IsNullOrWhiteSpace(builder.Configuration["APPLICATIONINSIGHTS_CONNECTION_STRING"]))
        builder.Services.AddOpenTelemetry().UseAzureMonitor();

    return builder;
}
```

**Discipline gate (docs must match wiring).** "Azure Monitor in cloud" is a wiring claim, not a doc sentence. Every exporter or resource named in an Observability section (tech-design `§Observability`, `infra/README`, the implementation plan) MUST have a matching call-site here, or be explicitly tagged `not wired`. Do not assert a telemetry capability the code does not deliver. The same rule covers instrumentation meters: if a doc lists FusionCache/EF/etc. as instrumented, `ConfigureOpenTelemetry` must register that meter, or the doc drops the claim. Adding `UseAzureMonitor()` requires the `Azure.Monitor.OpenTelemetry.AspNetCore` package.

Exporter gates are signal-specific. If configuration disables metrics, omit the metrics provider/exporter and application meters without gating away logs or traces. Where an all-signals convenience call cannot express that contract, register log, trace, and metric exporters separately and pin the disabled-metrics registration shape in a service-provider test. Deployment-sink requirements live in [../skills/observability.md](../skills/observability.md) section Signal and Deployment Sink Contract.

**One shared telemetry resource.** In cloud there is exactly **one** shared, workspace-based Application Insights resource fanned to every host via `APPLICATIONINSIGHTS_CONNECTION_STRING` - never a per-host ad-hoc component. The resource lives in IaC ([../skills/iac.md](../skills/iac.md) section App Insights); this seam only consumes the injected connection string. App-level logging/metrics/tracing conventions are owned by [../skills/observability.md](../skills/observability.md); the Functions worker's instrumentation caveat by [../skills/function-app.md](../skills/function-app.md) section Telemetry.

`MapDefaultEndpoints` maps three probes with distinct semantics - keep all three:

```csharp
app.MapHealthChecks("/healthz/live",  new HealthCheckOptions { Predicate = r => r.Tags.Contains("live") }).AllowAnonymous();
app.MapHealthChecks("/healthz/ready", new HealthCheckOptions { Predicate = r => r.Tags.Contains("ready") }).AllowAnonymous();
app.MapHealthChecks("/healthz",       new HealthCheckOptions()).AllowAnonymous();
```

`/healthz/live` reports only the self check tagged `live`; `/healthz/ready` reports critical dependency checks tagged `ready` (e.g. DB reachable, migrations applied); `/healthz` is the operator aggregate and is never an orchestrator liveness target. **Why:** dependency failure must remove a host from traffic without turning a healthy process into a liveness failure and restart loop. Tests and orchestration gate on `WaitForResourceHealthyAsync` + `/healthz/ready`, never on a resource merely reaching `Running`. Verify a failed critical dependency makes `/healthz/ready` unhealthy while `/healthz/live` stays healthy.

Readiness is host-specific. Exclude an optional cache or telemetry sink when the host has a tested degraded path, and include broker/outbox/scheduler checks only on hosts that require them. Multi-lane provider selection and the full probe contract are owned by [../support/scalability-and-hosting.md](../support/scalability-and-hosting.md).

**Non-negotiable:** do NOT add `http.AddHeaderPropagation()` in `AddServiceDefaults` unless a host also registers the `UseHeaderPropagation` middleware AND configures which headers to propagate. The handler alone throws `InvalidOperationException: HeaderPropagationValues.Headers not initialized` the moment an `HttpClient` is used outside an inbound HTTP request scope - a Blazor Server circuit, a background service, or any startup task. Forward cross-cutting context (tenant, correlation) explicitly with a per-client `DelegatingHandler` instead (see [../skills/ui-blazor.md](../skills/ui-blazor.md) section Dev Tenant Header).

---

## Aspire Resource Wiring

**Source:** `Host/Aspire/AppHost/AppHost.cs`

Canonical tokens (see [../ai/placeholder-tokens.md](../ai/placeholder-tokens.md)): `{Host}` = host project prefix, `{Project}` = DB/connection-name prefix, `{Gateway}` = `{Host}`. Aspire maps `.csproj` dots/hyphens to `_` in `Projects.*` (derivation rule 7).

Wire a secret SQL password parameter (persistent volume + fixed port in dev; non-persistent + random port under test so each run is clean), then Redis, then each host keyed by `connectionName`. **Give each pooled DbContext its own `WithReference(db, connectionName: ...)`** even when they map to one database - the runtime binds by connection name (`{Project}DbContextTrxn`, `{Project}DbContextQuery`, plus any extra contexts). Reference Redis as `Redis1`.

```csharp
var builder = DistributedApplication.CreateBuilder(args);
var isTesting = builder.Environment.EnvironmentName == "Testing";

// -- Shared infrastructure (persistent in dev, fresh per test run)
var sqlPassword = builder.AddParameter("sql-password", secret: true);
var sql = builder.AddSqlServer("sql", sqlPassword, port: isTesting ? null : 38433)
    .WithImageTag("<resolved-reviewed-sql-tag>")
    .WithImageSHA256("<resolved-sql-manifest-sha256>");
if (!isTesting)
    sql = sql.WithLifetime(ContainerLifetime.Persistent).WithDataVolume("{project}-sql-data");
var db = sql.AddDatabase("{project}db");

var redis = builder.AddRedis("redis")
    .WithImageTag("<resolved-reviewed-redis-tag>")
    .WithImageSHA256("<resolved-redis-manifest-sha256>");
if (!isTesting)
    redis = redis.WithLifetime(ContainerLifetime.Persistent).WithDataVolume("{project}-redis-data");

// -- Database migrator: sole migration owner, runs to completion before any runtime host.
//    One local SQL database, multiple schemas + logical connection names (extra names only
//    when the matching feature is enabled).
var migrator = builder.AddProject<Projects.{Host}_DatabaseMigrator>("{host}migrator")
    .WithReference(db, connectionName: "{Project}DbContextTrxn")
    .WithReference(db, connectionName: "{Project}FlowEngineDbContext")
    .WithReference(db, connectionName: "TickerQDbContext")
    .WaitFor(db);

// -- API: one WithReference per pooled DbContext connection name, plus Redis
var api = builder.AddProject<Projects.{Host}_Api>("{host}api")
    .WithReference(db, connectionName: "{Project}DbContextTrxn")
    .WithReference(db, connectionName: "{Project}DbContextQuery")
    .WithReference(redis, connectionName: "Redis1")
    .WaitFor(db)
    .WaitFor(redis)
    .WaitForCompletion(migrator)
    .WithExternalHttpEndpoints();

// -- Scheduler: same DB refs, pinned to one replica (dev/prod only)
var scheduler = builder.AddProject<Projects.{Host}_Scheduler>("{host}scheduler")
    .WithReference(db, connectionName: "{Project}DbContextTrxn")
    .WithReference(db, connectionName: "{Project}DbContextQuery")
    .WithReplicas(1)
    .WaitFor(db)
    .WaitForCompletion(migrator);

// -- Gateway (YARP): references API only. Destinations are injected here from resolved
//    endpoints, never read from the Gateway's own config (see aspire.md Gateway Reverse-Proxy).
var gateway = builder.AddProject<Projects.{Gateway}_Gateway>("{gateway}")
    .WithReference(api)
    .WaitFor(api);

// -- React SPA: only when includeReactUI: true
builder.AddViteApp("{host}react", "../../../UI/{Project}.React")
    .WithReference(gateway)
    .WithEnvironment("VITE_API_BASE_URL", gateway.GetEndpoint("http"))
    .WaitFor(gateway)
    .WithExternalHttpEndpoints();

await builder.Build().RunAsync();
```

**Rules:**
- Wait for the logical resource each consumer binds, such as `db`, not only its parent server/container. Declare the intended database explicitly (for PostgreSQL, set `POSTGRES_DB` when the image would otherwise create a different default), and leave a topology test that asserts every consumer's exact reference name and readiness edge.
- **Every runtime host that touches the database declares `.WaitForCompletion(migrator)`** (API, Scheduler, Functions, workers). Runtime hosts never migrate - the migrator host owns schema (canonical rules: [../support/data-persistence-advanced.md](../support/data-persistence-advanced.md) section Migration Ownership: Dedicated Migrator Host).
- **`.WithExternalHttpEndpoints()` on every host a developer must reach in a browser** (`api`, `gateway`, and UI hosts registered via `AddProject`). Without it the Aspire dashboard shows no URL and does not proxy browser traffic. `AddViteApp` applies it automatically; `AddProject` hosts do not.
- Only include `AddViteApp(...)` when `includeReactUI: true`; if Gateway is disabled, reference the API project and pass its endpoint to `VITE_API_BASE_URL`.
- A static UI reused across environments may read a same-origin `/app-config.json` generated at container startup. Serve it with `Cache-Control: no-store`, exclude it from immutable asset caching and SPA fallback, and fail deployment startup when required public values are absent. Keep local development on relative `/api` plus the Vite/Aspire proxy; a missing deployment config must not invent or require a workstation URL.
- Gateway (YARP) destinations must be injected from the AppHost as resolved `api.GetEndpoint("http")` values - never read from the Gateway's own `appsettings.json` (DCP starts children with `--no-launch-profile` on dynamic ports). Depth: [../skills/aspire.md](../skills/aspire.md) -> *Gateway Reverse-Proxy Destinations Under Aspire (DCP)*.
- This graph wires only local emulators/containers - **no** deployable Azure resources. When `deployTarget: ContainerApps` you MUST add the publish-mode branch: [../skills/aspire.md](../skills/aspire.md) -> *Publish-Mode Branch (deployTarget: ContainerApps)*.

### Azure AI Foundry (when `includeAiServices: true`)

Wire the model with `Aspire.Hosting.Foundry` so it provisions Azure on publish. The deployment resource name is the connection name consumers bind to. This snippet covers the default **inference** surface; for the **existing-account** and **project + server-hosted agent** surfaces see [../skills/ai-integration.md](../skills/ai-integration.md) -> *Foundry Projects and Server-Hosted Agents*.

> **Activation note (canonical owner: [../skills/ai-integration.md](../skills/ai-integration.md)).** `AiServices:Provider` is the sole activation source - an endpoint, deployment name, or connection string validates the selected arm but never selects one. Only `AzureInference` adds a `chat` resource; `OpenAICompatible` is validated in the consuming host and `None` wires no provider at all.

```csharp
IResourceBuilder<FoundryDeploymentResource>? chat = null;
var provider = AiProviderResolver.Resolve(builder.Configuration); // closed and lane-aware
var api = builder.AddProject<Projects.MyApp_Api>("api");

if (provider == AiProvider.AzureInference)
{
    // Validate required Azure endpoint/deployment settings before adding resources.
    // Azure path stays on Aspire: provisions (or connects to) a Foundry account + "chat" deployment.
    chat = builder.AddFoundry("foundry").AddDeployment("chat", FoundryModel.OpenAI.Gpt4oMini);
}

api = api.WithEnvironment("AiServices__Provider", provider.ToString());

// AzureInference: wire the deployment (injects ConnectionStrings:chat + CHAT_* env).
// OpenAICompatible: the consuming host validates endpoint/key/model. None: no provider.
// A TESTING AppHost selects None:
//   api = api.WithEnvironment("AiServices__Provider", "None");
if (chat is not null)
    api = api.WithReference(chat);
```

To consume an **existing** Foundry account instead of provisioning a new one (the `chat` deployment must already exist), replace the `AzureInference` provision branch with `RunAsExisting`:

```csharp
var name = builder.AddParameter("foundry-name");
var rg = builder.AddParameter("foundry-rg");
chat = builder.AddFoundry("foundry").RunAsExisting(name, rg)
    .AddDeployment("chat", FoundryModel.OpenAI.Gpt4oMini);
```

**Registration boundary:** the shared resolver selects the provider before any client registration. The Azure client is registered at the **host** (`IHostApplicationBuilder.AddAzureChatCompletionsClient("chat").AddChatClient()` from `Aspire.Azure.AI.Inference`) after the selected arm validates its connection; `OpenAICompatible` validates endpoint/key/model in the consuming host. The `IServiceCollection` extension registers no-op/stub only for explicit `None` and fails if a selected live arm did not register `IChatClient`. See [../skills/ai-integration.md](../skills/ai-integration.md).
```
