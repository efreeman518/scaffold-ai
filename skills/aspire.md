# Aspire Orchestration

> **When to read:** Phase 5b/5c, when choosing an Aspire hosting integration, writing the publish-mode branch, wiring Gateway destinations or emulators, or diagnosing an AppHost/substrate failure.
> **Skip if:** the solution has no AppHost; the task is the canonical run-mode resource graph itself (owned by `../patterns/infrastructure-wiring.md`); pure domain, application, or UI work.

Use Aspire AppHost for local orchestration and keep it consistent with IaC outputs.

Reference patterns: [../patterns/infrastructure-wiring.md](../patterns/infrastructure-wiring.md) (Aspire Resource Wiring).

## Official Integration Catalog Awareness

Before adding or rejecting an Aspire-hosted dependency, check the current Aspire integration catalog:

- Aspire integrations: <https://aspire.dev/integrations/>
- Azure integrations overview: <https://aspire.dev/integrations/cloud/azure/overview/>

The integration catalog is the source of truth for the AppHost API, required hosting/client packages, local emulator/container support, and connection pattern. Do not invent a local container, package name, or `Add*` API from memory when the current docs list the integration.

### Selection Rule

When a Phase 2 resource requirement names a service in the Aspire left menu:

1. Prefer the official Aspire hosting integration when it exists.
2. For Azure services, prefer unified `AddAzure*` resources when `deployTarget` needs Azure infrastructure. Add `RunAsEmulator` or `RunAsContainer` only for run mode.
3. If the Azure overview does not list a local emulator/container path for that service, treat local execution as `lazy-optional`, `no-op stub`, or `deployment-only` unless the service-specific page documents a current `RunAs*` path.
4. For non-Azure services in the catalog, use the service-specific `Add*` hosting integration and its documented container/local behavior.
5. Add the matching client integration in the consuming host only when app code needs a typed client. AppHost resources alone do not register application services.
6. Record any chosen service, local mode, publish mode, package names, connection names, and docs URL in `.scaffold/resource-implementation.yaml` or `HANDOFF.md`.

### Azure Run-Mode Matrix

Use this matrix as the default for Azure left-menu services. Re-check the service page during scaffold time because Aspire integrations evolve.

| Service family | Left-menu services | Local scaffold stance |
| --- | --- | --- |
| Azure emulators | App Configuration, Cosmos DB, Event Hubs, Service Bus, SignalR Service, Storage Blob/Queue/Table via Azure Storage | Use `AddAzure*().RunAsEmulator(...)` in run mode, real Azure on publish. Storage uses Azurite; Cosmos can use the preview emulator/Data Explorer where appropriate. |
| Azure local containers | Azure Cache for Redis, Azure PostgreSQL Flexible Server, Azure SQL Database/Server | Use `AddAzure*().RunAsContainer(...)` in run mode, real Azure on publish (Redis: `AddAzureManagedRedis` - see Aspire API Facts). Prefer this over plain `AddRedis`, `AddPostgres`, or `AddSqlServer` when the published target must be Azure-managed. |
| Azure AI cloud-only | Microsoft Foundry (model inference), Azure AI Inference, Azure AI Search, Azure OpenAI, Foundry projects + server-hosted agents (`AddProject`/`AddPromptAgent`) | Use live Azure only when `AiServices:Provider` explicitly selects it and its settings validate; otherwise no-op stubs locally. There is no on-device model lane - `None` is the offline answer. An existing account uses `RunAsExisting`/`PublishAsExisting`/`AsExisting`. Azure AI Search has no local emulator in this scaffold. Foundry prompt agents always deploy to Azure even under `aspire run` (no offline path), so keep them opt-in. |
| Azure app/platform resources | App Service, Container Registry, AKS, Container App Jobs, Front Door, Virtual Network, Log Analytics, Application Insights, Data Explorer, Data Lake Storage, Web PubSub, Key Vault, User-assigned managed identity, role assignments | Model for publish or existing-resource wiring. Do not assume a local emulator. Use `RunAsExisting`, `PublishAsExisting`, `AsExisting`, or app-level no-op/lazy wiring as appropriate. |

### Non-Azure Local Integration Families

The Aspire catalog also lists local/container integrations outside Azure. Use the category-specific skill file for application architecture, but use the official Aspire page for AppHost package/API details.

| Category | Left-menu services | Scaffold stance |
| --- | --- | --- |
| Artificial Intelligence | GitHub Models, Ollama, OpenAI | Only add when `includeAiServices: true`. The scaffold's supported provider set is Azure, OpenAI-compatible, or none - see [ai-integration.md](ai-integration.md) -> *Provider Activation Contract*. Keep no-op AI services so the app boots offline. |
| Caching and state | Redis, Redis Distributed Cache, Redis Output Cache, Valkey, Garnet | Use the documented hosting integration for local state. The scaffold default remains FusionCache plus Redis unless Phase 2 selects another cache. |
| Data and databases | ClickHouse, Elasticsearch, EF Core integrations, KurrentDB, Meilisearch, Milvus, MongoDB, MySQL, Oracle, PostgreSQL, Qdrant, RavenDB, SQL Server, SQLite, SurrealDB | Pick by domain need. SQL remains default for relational aggregates. Vector/search stores are optional projection stores, not source of truth, unless Phase 2 records that decision. |
| Messaging and eventing | Apache Kafka, LavinMQ, NATS, RabbitMQ | Use when the domain eventing requirement fits better than Azure Service Bus. Record delivery semantics, local container support, and publish/deployment story. |
| Frameworks and runtimes | .NET projects, Blazor, Orleans, Dapr, Go, Java, JavaScript/Node/Bun/Deno, PowerShell, Python, Rust, MAUI, WPF/WinForms | Use only for selected hosts/runtimes. Do not add a runtime just because Aspire supports it. |
| Observability and logging | Seq | Use for local log inspection when selected. Keep OpenTelemetry in ServiceDefaults either way. |
| Security and identity | Keycloak | Use only when Phase 2 selects Keycloak/local OIDC. Otherwise keep scaffold-mode auth or Entra guidance. |
| Reverse proxies and APIs | YARP | This scaffold uses YARP for Gateway when `includeGateway: true`. |
| Dev tools and extensions | Browser logs, Data API Builder, Dev Tunnels, flagd, goff, k6, MailPit, SQL Database Projects | Add only when the feature requires it. k6/load tooling belongs in quality/performance phases, MailPit in notification/email local tests, Dev Tunnels in callback scenarios. |

### AppHost API Naming Discipline

- Plain local resource APIs such as `AddRedis`, `AddSqlServer`, `AddPostgres`, and service-specific container integrations publish as containers unless documented otherwise.
- Unified Azure APIs such as `AddAzureSqlServer`, `AddAzurePostgresFlexibleServer`, and `AddAzureManagedRedis` can run locally through `RunAsContainer` and publish as Azure-managed services.
- Azure emulator APIs such as `AddAzureStorage`, `AddAzureServiceBus`, `AddAzureEventHubs`, `AddAzureCosmosDB`, and `AddAzureAppConfiguration` can run locally through `RunAsEmulator` and publish as Azure resources.
- Existing-resource modes are explicit: `RunAsExisting` for run mode, `PublishAsExisting` for publish mode, and `AsExisting` for both. Require parameterized resource names/resource groups and compatible authentication.

## Structure

```text
Host/Aspire/
  AppHost/
    AppHost.cs
    AppHost.csproj
  ServiceDefaults/
    Extensions.cs
```

### AppHost Entry File: `AppHost.cs` (not `Program.cs`)

The AppHost project's entry file is **`AppHost.cs`**, not `Program.cs`:

- Top-level statements emit an implicit `class Program` regardless of file name, so reflective lookups like `Type.GetType("Program, AppHost", ...)` and `WebApplicationFactory<Program>` keep working.
- No code references need updating. `.csproj` only needs editing if it has explicit `<Compile>` items (default item-includes do not).
- "`Program.cs` in the AppHost project" reads as a generic ASP.NET Core entry point - `AppHost.cs` correctly signals an Aspire orchestrator. Humans grep by file name; align it with intent.

> **Single-file AppHost** (a single `apphost.cs` lowercase with `#:sdk` / `#:package` directives, no `.csproj`) is a separate prototype-only feature. Not adopted; not supported in Visual Studio.

---

## AppHost Baseline Pattern

The canonical AppHost resource graph - SQL/Redis with per-host `connectionName` DbContext references, `WithExternalHttpEndpoints()`, and the optional Vite app - is owned by [../patterns/infrastructure-wiring.md](../patterns/infrastructure-wiring.md) section Aspire Resource Wiring, loaded in the same Phase 5b session. Do not restate it here. The Aspire-specific concerns below layer on top of that graph: reverse-proxy destination injection, publish-mode resources, and run-mode parameters.

---

## Gateway Reverse-Proxy Destinations Under Aspire (DCP)

When `includeGateway: true`, the Gateway's YARP cluster destinations must be supplied by the AppHost as resolved endpoints - **not** read from the Gateway's own `appsettings.json`/`launchSettings.json`.

DCP (the Aspire orchestrator) starts every child resource with `--no-launch-profile`, so the Gateway's launch profile and any fixed-port destination addresses baked into its config are not applied. A destination pointing at `http://localhost:<fixed-port>` will not reach the API resource, which DCP binds to a dynamic port. The route resolves to nothing and browser/Gateway calls 502/404 in a way that looks like a routing bug but is a wiring gap.

Inject the destination from AppHost using the resolved endpoint and double-underscore config keys:

```csharp
var gateway = builder.AddProject<Projects.{Gateway}_Gateway>("{gateway}")
    .WithReference(api)
    .WithEnvironment("ReverseProxy__Routes__api-route__Match__Path", "/api/{**catch-all}")
    .WithEnvironment("ReverseProxy__Clusters__api-cluster__Destinations__api__Address", api.GetEndpoint("http"))
    .WaitFor(api);
```

- `api.GetEndpoint("http")` resolves to the address DCP actually assigned - the only value that works under both `dotnet run` and `Test.Aspire`.
- The env keys mirror the `ReverseProxy:Routes:*` / `ReverseProxy:Clusters:*` structure the Gateway binds; `__` maps to the config `:` separator.
- Keep the Gateway's static `appsettings.json` route/cluster shape for standalone (non-Aspire) runs, but never rely on its destination *addresses* under Aspire - the AppHost override wins and must be present.

This is why the Gateway belongs in the default test graph: the AppHost is the only component that knows the resolved API endpoint, so a Gateway smoke test that bypasses the AppHost cannot route correctly.

---

## Publish-Mode Branch (deployTarget: ContainerApps)

Key the deployable graph on `builder.ExecutionContext.IsPublishMode` so the SAME model runs locally (run mode) and provisions Azure resources on publish. Start from the run-mode graph in [../patterns/infrastructure-wiring.md](../patterns/infrastructure-wiring.md) (Aspire Resource Wiring); this branch only swaps the local-only resource types for the unified `AddAzure*` types and guards every emulator/run-only affordance behind the execution context.

```csharp
// ACA environment + dashboard exist only in the published graph.
if (builder.ExecutionContext.IsPublishMode)
    builder.AddAzureContainerAppEnvironment("cae").WithDashboard();

// Unified Azure types: local affordance in run mode, provisioned Azure resource on publish.
var sql = builder.AddAzureSqlServer("sql");
var storage = builder.AddAzureStorage("storage");
var serviceBus = builder.AddAzureServiceBus("servicebus");
var cosmos = builder.AddAzureCosmosDB("cosmos");

if (!builder.ExecutionContext.IsPublishMode)
{
    // Create the sql-password parameter INSIDE this branch (see Run-Mode Parameter Placement) so
    // azd never prompts for it. Container/port/lifetime details: infrastructure-wiring.md.
    var sqlPassword = builder.AddParameter("sql-password", LocalSqlSettings.SharedSaPassword, secret: true);
    sql = sql.RunAsContainer(c => c.WithHostPort(38433).WithPassword(sqlPassword) /* tag + SHA256 */);
    storage.RunAsEmulator();
    serviceBus.RunAsEmulator();
    cosmos.RunAsPreviewEmulator(e => e.WithGatewayPort(8081).WithDataExplorer(1234));
}
var projectDb = sql.AddDatabase("{project}db");

// Ingress: WithExternalHttpEndpoints ONLY on services that must be public.
var gateway = builder.AddProject<Projects.{Gateway}_Gateway>("{gateway}")
    .WithReference(api)
    .WithExternalHttpEndpoints();   // public -> ACA ingress.external=true
```

### Ingress Rules (verified against the publish manifest)

- `.WithExternalHttpEndpoints()` present -> ACA `ingress.external=true` (public).
- omitted, but the project has an HTTP endpoint -> internal-only ingress.
- project has no HTTP endpoint -> no ingress at all.

Call `.WithExternalHttpEndpoints()` only on the public surface (typically Gateway + a Blazor/React host). Leave API, Functions, and internal workers without it so they stay internal.

### Run-Mode Parameter Placement

The fixed local SQL port and the `sql-password` parameter live INSIDE the `RunAsContainer` / run-mode branch. Creating `AddParameter("sql-password", ...)` there (not at the top level) keeps it out of the publish manifest, so `azd` does not prompt for a SQL password it does not need (Azure SQL uses managed-identity auth - see below). Tests and dev tooling that depend on the fixed `38433` port and `sql-password` parameter still work because both exist in run mode.

### Aspire API Facts

- **`AddAzureSqlServer(...)`** auto-assigns a user-assigned managed identity as the SQL admin and grants each deployed app container `db_owner` during provisioning. The deploying principal is also granted `db_owner`. **Consequence:** no manual `CREATE USER ... FROM EXTERNAL PROVIDER` in the pipeline when provisioning and migration run under the same OIDC identity. Use `AddAzureSqlServer` (not `AddSqlServer`) for `deployTarget: ContainerApps` - `AddSqlServer` publishes a SQL container into ACA instead of provisioning Azure SQL. A bare `AddAzureSqlServer(...).RunAsContainer()` (no `WithPassword`) auto-generates the local SA credential - no `sql-password` parameter, no user-secrets preflight; wire the explicit parameter only when tests/tooling need the deterministic fixed-port/password fixture (`LocalSqlSettings.SharedSaPassword`).
- **`AddAzureCosmosDB(...)`** provisions a SERVERLESS account by default. No SKU/capability config needed; `.WithDefaultAzureSku()` is the opt-in for provisioned throughput.
- **Use `AddAzureManagedRedis`** for Azure Redis (not `AddAzureRedis(...).RunAsContainer()`). If the app uses FusionCache, omitting Redis on publish degrades it to L1-only with no `IDistributedCache` (a valid cost lever). If you omit Redis, guard every `.WithReference(redis, "Redis1")` with a null check so the model still builds.

---

## Azure AI Foundry

Use `Aspire.Hosting.Foundry` to model a chat model that provisions Azure on publish. The package is preview-only - pin it with an inline reason in `Directory.Packages.props`. The deployment resource name is the connection name consumers bind to.

**Provider doctrine, the lifecycle x consumption axes, the lifecycle table, and the model-selection rule are owned by [ai-integration.md](ai-integration.md)** (*Provider Activation Contract*, *Aspire Integration*). The AppHost wiring snippet is owned by [../patterns/infrastructure-wiring.md](../patterns/infrastructure-wiring.md) (its Azure AI Foundry wiring), loaded in the same Phase 5b session. Do not restate either here.

The AppHost-side facts this file owns:

- `FoundryResource : AzureProvisioningResource`, so the general existing-resource APIs apply: `RunAsExisting(nameParam, rgParam)` / `PublishAsExisting(...)` / `AsExisting(...)` point at an already-provisioned account, and the deployment name must match a model already deployed there.
- `AiServices:Provider` is the only activation source in the graph. `AzureInference` wires the Foundry account + `chat` deployment; `OpenAICompatible` and `None` wire no `chat` resource. Raw endpoint/deployment settings and publish mode never override the selected provider.
- **The testing AppHost bakes its provider in at graph construction.** `Test.Aspire` selects `AiServices:Provider=None` by default. Its optional Azure live smoke does not re-flip that on the shared graph - AppHost environment variables are read once when the graph is built, so a lazily-started shared graph cannot change provider per test. The live lane constructs its **own** graph with `AzureInference` selected before creation. See [ai-integration.md](ai-integration.md) -> *Deciding the Live Lane*.

---

## ServiceDefaults Pattern

`AddServiceDefaults` (OpenTelemetry, health checks, service discovery, HTTP resilience) and the `/healthz/live` + `/healthz/ready` + `/healthz` probes are owned by [../patterns/infrastructure-wiring.md](../patterns/infrastructure-wiring.md) section ServiceDefaults Configuration, loaded in the same Phase 5b session. Do not restate the method body here.

---

## Hosting Package Discovery Rule

When adding infra dependencies:
1. Check for `Aspire.Hosting.{Service}` package first.
2. If Azure service supports emulator mode, use `.RunAsEmulator()`.
3. If no official package exists, use local emulator/container or stub.

Examples:

```csharp
var storage = builder.AddAzureStorage("storage").RunAsEmulator();
var cosmos = builder.AddAzureCosmosDB("cosmos").RunAsEmulator();
var serviceBus = builder.AddAzureServiceBus("servicebus").RunAsEmulator();
var eventHubs = builder.AddAzureEventHubs("eventhubs").RunAsEmulator();
```

> **Do NOT use `ContainerLifetime.Persistent` on Azure emulator containers** (Storage, Service Bus, Cosmos, Event Hubs) by default. Persistent emulator containers survive Aspire restarts but get stranded on deleted Podman/Docker networks, causing `netavark "eth2 already exists"` errors and broken restarts. Only SQL Server and Redis use `Persistent` + named volumes - Azure emulators should use the default ephemeral lifetime.
>
> **Narrow exception: Cosmos preview emulator.** Cosmos image is large and slow to start, so a long local-dev session may justify `ContainerLifetime.Persistent` on the Cosmos preview emulator specifically. If used, document the restart cleanup procedure (manually remove the container and its network when network errors appear) in `HANDOFF.md`. Do not extend this exception to Azurite, Service Bus, or Event Hubs without an explicit reason - those startup costs are low and not worth the stranding risk.

### Emulator Image Pinning (and the Service Bus SQL sidecar)

Resolve a concrete, reviewed tag for every emulator at scaffold time and record it in the implementation plan. Shared CI also sets the immutable manifest digest through `WithImageSHA256`; omit the digest only for an explicitly local-only or unresolved cross-architecture topology and record that boundary. A bare `.RunAsEmulator()` rides whatever image the hosting package defaults to, while a floating `latest` tag changes without a source diff.

```csharp
var storage = builder.AddAzureStorage("storage")
    .RunAsEmulator(e => e
        .WithImageTag("<resolved-reviewed-azurite-tag>")
        .WithImageSHA256("<resolved-azurite-manifest-sha256>"));
var serviceBus = builder.AddAzureServiceBus("servicebus")
    .RunAsEmulator(e => e
        .WithImageTag("<resolved-reviewed-servicebus-tag>")
        .WithImageSHA256("<resolved-servicebus-manifest-sha256>"));
```

**The Service Bus emulator bundles its own SQL Server sidecar** - a separate container named `{servicebus}-mssql`. The Aspire package **hardcodes that SQL image tag**, and the `RunAsEmulator` callback **cannot reach it** (the callback configures only the emulator container, not the sidecar). Left alone it pulls a different, usually older SQL Server major than your `sql` resource - so the machine ends up with two full SQL images. Override it by pulling the resource out of the model right after `RunAsEmulator` and re-tagging it to match `sql`:

```csharp
// Align the Service Bus emulator's bundled SQL sidecar with the `sql` tag so Docker shares layers
// instead of pulling a second SQL Server major (matters most on disk-constrained CI runners).
// builder.Resources.Single(...) needs System.Linq in scope.
builder.CreateResourceBuilder(
        (ContainerResource)builder.Resources.Single(r => r.Name == "servicebus-mssql"))
    .WithImageTag("<resolved-reviewed-sql-tag>")
    .WithImageSHA256("<resolved-sql-manifest-sha256>");
```

> **Compatibility caveat.** The Service Bus emulator is validated against its bundled SQL version, so forcing a newer major is a mild risk. Verify the emulator still reaches a healthy state after re-tagging (a mesh/Aspire test that exercises the bus is enough). If it regresses, drop the override and accept the second image.

### Azure Service Bus Topics and Subscriptions

```csharp
var sb = builder.AddAzureServiceBus("servicebus").RunAsEmulator();
sb.AddTopic("domain-events", ["api", "other-subscriber"]);
sb.AddQueue("commands"); // optional queue
```

> **API note:** Use `AddTopic(name, subscriptions[])` - the chained `.AddServiceBusTopic().AddServiceBusSubscription()` API does not exist. Queues use `AddQueue(name)`.

Services like `AddSqlServer`, `AddRedis`, `AddPostgres`, `AddRabbitMQ` already run local containers by default.

---

## Local Explorer Tooling (Non-Test Runs)

Stable host ports plus integrated explorer UIs make local-dev sessions inspectable without rediscovering connection strings or ports on every restart. **All explorer wiring below is local-dev only.** Gate it behind an `isTesting` flag so test runs keep dynamic ports and skip explorer containers entirely.

### Decision Rule

1. **Pin host ports** for resources humans inspect from host tools (SQL Server, Redis, Azurite, Service Bus, Cosmos gateway/Data Explorer).
2. **Keep test runs dynamic.** Wrap pinned ports and explorer containers in `if (!isTesting)` so parallel test runs and CI do not collide on fixed ports.
3. **Prefer Aspire-integrated browser UIs** when the hosting package offers one (`WithRedisInsight`, `WithDataExplorer`). They reuse the Aspire container network and avoid host-tool installation.
4. **Use first-party desktop tools as the supported fallback** when browser UIs are third-party or weaker (Microsoft Azure Storage Explorer for Azurite, VS Code SQL extension for SQL).
5. **Record connection strings and ports in `HANDOFF.md`**, not in code comments, so future sessions can attach without rediscovering values.

### Canonical Local Port Matrix

| Resource | Host port | Tool | Notes |
| --- | ---: | --- | --- |
| SQL Server | `38433` | VS Code SQL extension | Host: `localhost,38433`. From another container on the Aspire network: `sql,1433`. |
| Redis | `6379` | RedisInsight (Aspire-managed) | Pin via `port` arg on `AddRedis`. |
| RedisInsight UI | `5540` | Browser | `WithRedisInsight(...)` - browser UI, no desktop install. |
| Azurite Blob | `10000` | Microsoft Azure Storage Explorer (desktop) | Default port enables Storage Explorer auto-detection. |
| Azurite Queue | `10001` | Microsoft Azure Storage Explorer (desktop) | Default port enables Storage Explorer auto-detection. |
| Azurite Table | `10002` | Microsoft Azure Storage Explorer (desktop) | Default port enables Storage Explorer auto-detection. |
| Service Bus AMQP | `5672` | SDKs, emulator-aware tools | Messaging connection endpoint. |
| Service Bus management | `5300` | Messentra, admin client | Admin endpoint; health at `http://localhost:5300/health`. |
| Cosmos gateway | `8081` | SDKs | Required by Cosmos explorer and clients. |
| Cosmos Data Explorer | `1234` | Browser | `WithDataExplorer(1234)` on preview emulator. |

Browser UIs running in Docker do not resolve host `localhost`. From inside an explorer container, use the Aspire service DNS name on the Aspire network (e.g., `sql`, `redis`) or `host.docker.internal` for host services.

### Redis + RedisInsight (preferred)

`builder.AddRedis(...)` accepts an explicit `port` and an Aspire-managed RedisInsight browser UI via `WithRedisInsight`. RedisInsight pre-wires environment variables for the Redis resource - no manual config inside the UI.

```csharp
var redisPwd = builder.AddParameter(
    "redis-password",
    () => "{Project}!Redis#Pwd123",
    secret: true);

var redis = builder.AddRedis("redis", port: isTesting ? null : 6379, password: redisPwd)
    .WithImageTag("<resolved-reviewed-redis-tag>")
    .WithImageSHA256("<resolved-redis-manifest-sha256>");

if (!isTesting)
{
    redis = redis
        .WithDataVolume("{project}-redis-data")
        .WithLifetime(ContainerLifetime.Persistent)
        .WithRedisInsight(insight => insight
            .WithHostPort(5540)
            .WithDataVolume("{project}-redisinsight-data")
            .WithLifetime(ContainerLifetime.Persistent));
}
```

Redis + RedisInsight are not Azure emulators - persistent lifetime + named volume is the normal pattern. The RedisInsight UI lives at `http://localhost:5540`.

### Service Bus Emulator + Management Endpoint

Pin the AMQP port for SDK clients and expose an HTTP management endpoint for admin clients and health probes. **Messentra** is a UI-only inspector (not an emulator); Aspire still owns the emulator container.

```csharp
var serviceBus = builder.AddAzureServiceBus("servicebus")
    .RunAsEmulator(emulator =>
    {
        var serviceBusEmulator = emulator
            .WithImageTag("<resolved-reviewed-servicebus-tag>")
            .WithImageSHA256("<resolved-servicebus-manifest-sha256>");

        if (!isTesting)
        {
            serviceBusEmulator
                .WithHostPort(5672)
                .WithEndpoint(targetPort: 5300, port: 5300, scheme: "http", name: "management");
        }
    });
```

Connection-string forms differ by tool:

- Messaging SDK: `Endpoint=sb://localhost;...;UseDevelopmentEmulator=true;`
- Administration-client tools: `Endpoint=sb://localhost:5300;...;UseDevelopmentEmulator=true;`

In Messentra, save the namespace under Options, then click `+` in Explorer to select it - the saved connection does not auto-load.

### Azurite + Storage Explorer

Microsoft Azure Storage Explorer (desktop) is the supported tool for Azurite. With Blob/Queue/Table on default ports `10000`/`10001`/`10002`, it auto-detects local emulator. Browser-based storage explorers are third-party; use only with explicit approval.

Host connection string for Azurite tools:

```text
DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;QueueEndpoint=http://127.0.0.1:10001/devstoreaccount1;TableEndpoint=http://127.0.0.1:10002/devstoreaccount1;
```

### Cosmos Preview Emulator + Data Explorer

Use the preview emulator with pinned gateway and Data Explorer ports for local dev. Keep Cosmos out of default test runs - the image is large and startup is slow.

```csharp
var cosmos = builder.AddAzureCosmosDB("cosmos");

if (!isTesting)
{
    cosmos = cosmos.RunAsPreviewEmulator(emulator => emulator
        .WithGatewayPort(8081)
        .WithDataExplorer(1234));
}
```

When `http://localhost:1234` spins forever, **inspect the Cosmos resource health and container logs first** - the Data Explorer is loaded from the emulator itself, so a stalled emulator presents as a stuck UI. Do not assume the explorer is broken before the gateway/emulator is healthy.

### SQL + VS Code SQL Extension

VS Code SQL extension (`mssql`) is the default developer tool for local SQL Server. Pin the host port to `38433` for non-test runs; tests use dynamic ports.

```text
Server=localhost,38433;Database={project}db;User Id=sa;Password={sql-password};Encrypt=True;TrustServerCertificate=True;
```

From a containerized SQL UI on the same Aspire network: server `sql`, port `1433`.

### Test-Mode Discipline

Fixed ports and explorer UIs are **local-dev affordances only**. In test runs:

- Use Aspire/Testcontainers-injected connection strings, not pinned ports.
- Skip explorer containers (e.g. RedisInsight) from the test graph unless a specific test requires them.
- Gate every explorer wiring on `if (!isTesting)`. The `isTesting` flag is the same one already used to scope opt-in resources - see [testing.md](testing.md) -> *Opt-In Graph Scope via Env Flag*.

---

## Key Rules

1. `WithReference(..., connectionName: "X")` must map to runtime key `ConnectionStrings:X`.
2. **Every project that needs a resource must have its own `.WithReference()` call.** A common bug: adding a new consumer project (e.g., Functions) that uses the same database as the API but forgetting to add `.WithReference(db, connectionName: "...")`. The project silently falls back to `appsettings.json` connection strings (often LocalDB or nonexistent), causing connection errors that look like infrastructure problems.
3. Keep scheduler single replica when using TickerQ.
4. Use `WaitFor(...)` for startup ordering dependencies; database-touching runtime hosts also take `WaitForCompletion(migrator)` on the one-shot `{Host}.DatabaseMigrator` resource (graph owner: [../patterns/infrastructure-wiring.md](../patterns/infrastructure-wiring.md) section Aspire Resource Wiring).
5. Keep Gateway as public ingress, backend hosts internal.
6. Keep AppHost resource names aligned with IaC modules in [iac.md](iac.md).
7. Resolve and pin a reviewed SQL Server image tag plus manifest digest for shared CI; EF SQL registrations must use the selected compatibility level.
8. Pin every shared-CI emulator with a reviewed tag plus `WithImageSHA256`, never `latest`, and override the Service Bus emulator's hidden SQL sidecar reference - see *Emulator Image Pinning (and the Service Bus SQL sidecar)* above.

---

## Parameter Resolution and Credential Management

### Aspire Parameter Resolution Order

Aspire resolves `AddParameter` values in this priority order (highest wins):

1. Environment variables (`Parameters__<name>`)
2. `appsettings.{Environment}.json` entries under `Parameters:<name>`
3. `AddParameter(..., default: ...)` code default

**A value in `appsettings.Development.json` or `appsettings.Testing.json` silently overrides the code default on every run.** This is the most common source of "why isn't my password change taking effect?" bugs.

### Rules

- **Never put `Parameters:sql-password` (or any credential parameter) in any AppHost `appsettings` file.** It overrides everything silently. Keep those files as `{}` or omit the `Parameters` key entirely.
- **Define passwords as a single shared constant** (e.g., `LocalSqlSettings.SharedSaPassword`). Use that constant as the `AddParameter` default and in test fixture setup. Change in one place only.
- **Persistent SQL volumes lock in the SA password at volume creation time.** If you change the password constant, you must delete the named volume (e.g., `taskflow-sql-data`) before the next run - the container will re-initialize with the new password.
- **Gate persistent lifetime + data volume on `!IsAspireTesting()`.** Apply `.WithLifetime(ContainerLifetime.Persistent)` and `.WithDataVolume(...)` only in local `dotnet run` (canonical graph: [../patterns/infrastructure-wiring.md](../patterns/infrastructure-wiring.md) section Aspire Resource Wiring). Under `IsAspireTesting()` the container must stay **ephemeral** so that `DistributedApplication.DisposeAsync()` in the mesh fixture's teardown removes exactly the containers that run started - no machine-wide cleanup, no leaked SQL/Redis container holding a port, and no risk to another project's or session's containers. This is what lets the test tier avoid any `docker rm` sweep entirely. The `IsAspireTesting()` helper already exists (the same one that gates opt-in resources - see [testing.md](testing.md), Opt-In Graph Scope).
- **Killing the AppHost process does not stop Docker/Podman containers.** Persistent containers are intentional - clean them up **deliberately, by this project's resource name/volume**, never by a generic Aspire label:
  ```bash
  docker rm -f {project}-sql {project}-redis     # by name (RunAsContainer resource names)
  docker volume rm {project}-sql-data {project}-redis-data   # only if discarding state
  ```
  Or remove them from the Aspire dashboard.
  > **Never sweep by the generic Aspire label.** `docker ps --filter label=com.microsoft.dotnet.aspire.container.name ... | xargs docker rm -f` matches **every** project's and **every** session's Aspire containers on the machine - including other developers' work and intentional persistent stacks. Scope cleanup to this project's resource names. Test-owned containers are handled separately and automatically - see the ephemeral-under-test rule above.

### Pattern: Shared Constant + Clean appsettings

```csharp
// AppHost/LocalSqlSettings.cs
public static class LocalSqlSettings
{
    public const string SharedSaPassword = "YourStr0ngP@ssword!";
}

// AppHost/AppHost.cs
var sqlPassword = builder.AddParameter("sql-password", LocalSqlSettings.SharedSaPassword, secret: true);
var sqlServer = builder.AddSqlServer("sql", sqlPassword)
    .WithLifetime(ContainerLifetime.Persistent)
    .WithDataVolume("{project}-sql-data")
    .WithImageTag("<resolved-reviewed-sql-tag>")
    .WithImageSHA256("<resolved-sql-manifest-sha256>");
```

`AppHost/appsettings.Development.json` and `appsettings.Testing.json` must **not** contain a `Parameters` section. Leave them as `{}`.

---

## Package Source Mapping for Aspire Dependencies

When the project uses `nuget.config` with `<packageSourceMapping>`, the following patterns must be mapped to `nuget.org` or Aspire transitive restores will fail:

```xml
<packageSource key="nuget.org">
  <package pattern="AspNetCore.HealthChecks.*" />
  <!-- ... existing patterns ... -->
</packageSource>
```

`Aspire.Hosting.*` and `Aspire.ServiceDefaults` pull `AspNetCore.HealthChecks.UI.*` transitively. Without this entry, `dotnet restore` fails with NU1100.

---

## Azure SQL Transitive Version Conflict

When using `Aspire.Hosting.Azure.Sql`, `Microsoft.Data.SqlClient` pulls `Microsoft.IdentityModel.JsonWebTokens` at a version that conflicts with other Aspire dependencies. To resolve NU1605:

1. Pin in `Directory.Packages.props` - **documented exception** to the latest-not-pinned rule (see [package-dependencies.md](package-dependencies.md) -> *Latest, Not Pinned*). Resolve the lowest version that satisfies both consumers at scaffold time and keep the inline reason comment:
   ```xml
   <!-- Pinned: NU1605 conflict between Microsoft.Data.SqlClient and other Aspire deps. Re-evaluate on SDK bump. -->
   <PackageVersion Include="Microsoft.IdentityModel.JsonWebTokens" Version="<resolved-at-scaffold>" />
   ```
2. Add a redundant `<PackageReference>` for this package in the AppHost `.csproj` to suppress the downgrade warning.
3. **Re-evaluate on every SDK bump.** When the underlying conflict is resolved upstream, remove the pin and revert to central latest-stable resolution.

---

## Dev Tunnel Pattern (Optional)

```csharp
var tunnel = builder.AddDevTunnel(
    name: "{gateway}-tunnel",
    tunnelId: "{project}-dev-tunnel",
    options: new DevTunnelOptions { AllowAnonymous = false });

tunnel.WithReference(gateway.GetEndpoint("https-gateway"), allowAnonymous: true);
```

Use persistent `tunnelId` for stable callback URLs.

---

## AppHost.csproj Essentials

Use the `Aspire.AppHost.Sdk` MSBuild SDK. It handles `Projects.*` type proxy generation, `IsAspireHost`, and `AspireHostingSDKVersion` automatically.

```xml
<Project Sdk="Aspire.AppHost.Sdk/<latest-stable>">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>$(LatestStableTfm)</TargetFramework>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Aspire.Hosting.SqlServer" />
    <PackageReference Include="Aspire.Hosting.Redis" />
    <!-- Include only when registering React/Vite UI with AddViteApp. -->
    <PackageReference Include="Aspire.Hosting.JavaScript" />
  </ItemGroup>
</Project>
```

Substitute `<latest-stable>` and the TFM at scaffold time. Do not hard-code versions in templates - see [package-dependencies.md](package-dependencies.md) -> *Latest, Not Pinned*.

> **Publish-mode package gaps (`deployTarget: ContainerApps`).** The local-only baseline does not pull the packages the publish-mode branch needs. Add to `Directory.Packages.props` + AppHost.csproj when targeting Container Apps:
> - `Aspire.Hosting.Azure.AppContainers` - `AddAzureContainerAppEnvironment`, dashboard, scale.
> - `Aspire.Hosting.Azure.Sql` - `AddAzureSqlServer`.
>
> The Azure Storage/Service Bus/Cosmos/Functions hosting packages are typically already referenced for the emulator wiring; confirm they are present before adding the publish branch.

> **SDK upgrade discipline.** A major Aspire SDK bump is a **deliberate, scheduled task**, not routine work. Major bumps can tighten APIs (e.g., `IDistributedApplicationTestingBuilder` inheritance), so existing code may need adjustments. Consult the official Aspire upgrade guide on MS Learn and the version-specific compatibility pages before bumping.

If using dev tunnels, add `Aspire.Hosting.DevTunnels`.

---

## Preflight (Before First Launch)

Before running `dotnet run --project src/Host/Aspire/AppHost`, confirm the substrate:

1. **Docker/Podman running:** `docker info` or `podman info` succeeds. If not, start the container runtime - do not debug app code.
2. **Aspire CLI available when using `aspire run`:** `aspire --version` succeeds. If missing, install it:
   ```powershell
   dotnet tool install -g Aspire.Cli
   ```
   You can still run the AppHost with `dotnet run --project src/Host/Aspire/AppHost`, but having the CLI installed keeps local and docs commands aligned.
3. **launchSettings.json exists:** AppHost requires `Properties/launchSettings.json` with OTLP/dashboard endpoints. Without it, `dotnet run` starts but the dashboard never opens and the terminal appears blank. Minimal template:
   ```json
   {
     "profiles": {
       "https": {
         "commandName": "Project",
         "dotnetRunMessages": true,
         "launchBrowser": true,
         "applicationUrl": "https://localhost:17179;http://localhost:15180",
         "environmentVariables": {
           "ASPIRE_DASHBOARD_OTLP_ENDPOINT_URL": "https://localhost:21147",
           "DOTNET_DASHBOARD_OTLP_ENDPOINT_URL": "https://localhost:21147",
           "ASPIRE_ALLOW_UNSECURED_TRANSPORT": "true"
         }
       },
       "http": {
         "commandName": "Project",
         "dotnetRunMessages": true,
         "launchBrowser": true,
         "applicationUrl": "http://localhost:15180",
         "environmentVariables": {
           "ASPIRE_DASHBOARD_OTLP_ENDPOINT_URL": "http://localhost:19197",
           "DOTNET_DASHBOARD_OTLP_ENDPOINT_URL": "http://localhost:19197",
           "ASPIRE_ALLOW_UNSECURED_TRANSPORT": "true"
         }
       }
     }
   }
   ```
4. **User secrets initialized for SQL password:** If the AppHost uses `builder.AddParameter("sql-password", secret: true)`, the secret must exist in user secrets before launch:
   ```powershell
   dotnet user-secrets init --project src/Host/Aspire/AppHost
   dotnet user-secrets set "Parameters:sql-password" "<YourPassword>" --project src/Host/Aspire/AppHost
   ```
   Without this, the SQL container starts but cannot authenticate. Not needed when the parameter is created with an inline value (the canonical AppHost passes `LocalSqlSettings.SharedSaPassword`) or when `AddAzureSqlServer(...).RunAsContainer()` runs bare - see Aspire API Facts.
5. **Ports available:** No stale containers holding SQL/Redis ports. Run `docker ps` / `podman ps` to check.
6. **NuGet restore clean:** `dotnet restore` on the AppHost project succeeds (catches `packageSourceMapping` issues before launch).
7. **AI provider (only when `includeAiServices: true`):** the default `AiServices:Provider=None` needs nothing installed - the app boots with a no-op `IChatClient`. A live run needs the selected provider's configuration present before launch (Azure endpoint/deployment, or OpenAI-compatible endpoint/model/secret key); see [ai-integration.md](ai-integration.md) -> *Local Run Preflight*. There is no on-device model runtime to install.
8. **Functions Core Tools (only if running Azure Functions locally):**
   ```powershell
   npm i -g azure-functions-core-tools@4 --unsafe-perm true
   func --version
   ```

Only after the applicable checks pass, proceed to `dotnet run`.

---

## Run

```bash
dotnet run --project src/Host/Aspire/AppHost
```

If running from CLI without launch profile, set required env vars for dashboard/OTLP endpoints.

---

## Ephemeral URL Discovery

Aspire dashboard URLs, proxy ports, and host endpoints are **assigned at runtime** and may change between launches. Do not carry forward URLs from a previous session.

On each launch:
1. Read the dashboard URL from the `dotnet run` console output.
2. Confirm resource health on the dashboard before testing endpoints.
3. Use the dashboard's resource list to find current host URLs - do not assume prior ports.

When writing `HANDOFF.md`, record the **method to discover URLs** (e.g., "check Aspire dashboard"), not the URLs themselves.

---

## Detecting Aspire at Runtime - Presence, Not Environment

Hosts often need to know "am I being orchestrated by Aspire?" to decide whether to register real Azure clients vs. local no-op stubs. **Gate on the presence of an Aspire-injected connection string, not on `IHostEnvironment.IsEnvironment("Testing")` or any other environment name.**

```csharp
// CORRECT - presence-based
var runningUnderAspire = !string.IsNullOrEmpty(
    builder.Configuration.GetConnectionString("{App}DbContextTrxn"));

if (runningUnderAspire)
{
    builder.AddAzureServiceBusClient("servicebus");
    builder.Services.Replace(
        ServiceDescriptor.Scoped<I{App}EventPublisher, ServiceBus{App}EventPublisher>());
}
```

**Why not environment-name gates.** `WebApplicationFactory<Program>` sets `ASPNETCORE_ENVIRONMENT=Testing` via `UseEnvironment("Testing")`, and `DistributedApplicationTestingBuilder` propagates the same env name to **every child project** it brings up under test. A gate like `!builder.Environment.IsEnvironment("Testing")` therefore returns `false` in **both** WAF tier and Aspire-mesh tier - the API silently keeps its `NoOp` publishers, and integration events are dropped without an error. The bug is invisible (POST 201, row persisted) and only manifests when a downstream consumer fails to observe the event.

The connection-string presence check distinguishes the two tiers correctly: WAF tier injects in-memory DbContext options (no connection string), Aspire tier injects real Aspire-resolved connection strings.

Apply the same principle to Functions hosts, Worker hosts, and Scheduler hosts - any host that has both an Aspire path and a non-Aspire test path. If a host has **no** non-Aspire test path (i.e., always-Aspire), document that explicitly in the host's `Program.cs` and skip the gate entirely.

---

## Debugging Individual Hosts

When a multi-host Aspire run fails, isolate the problem by running hosts standalone:

```powershell
cd src/Host/{Host}.Api
dotnet run 2>&1
```

This bypasses Aspire orchestration and surfaces startup exceptions (DI failures, missing config, migration errors) directly in the console. Fix standalone first, then return to AppHost.

**Common gotcha:** Orphaned `dotnet.exe` processes from prior runs can hold file locks and prevent builds. Check with `Get-Process -Name dotnet` and kill if needed.

---

## Uno.Sdk Incompatibility

Uno.Sdk projects (`<Project Sdk="Uno.Sdk/..."`) do not expose the `GetTargetPath` MSBuild target that Aspire uses for project introspection. Adding the Uno SDK project directly to AppHost causes `MSB4057`.

Do not register the Uno SDK project directly. Host browserwasm through the ASP.NET Core wrapper under `src/Host/{Project}.Uno.WasmHost/`, then register that wrapper in AppHost. The wrapper participates in Aspire, so AppHost-backed `WasmUI` tests can start Gateway/API/resources and resolve the UI URL from the wrapper resource's named endpoint.

If a legacy scaffold already added the Uno SDK project to AppHost, remove that direct `ProjectReference` / `AddProject` pair and replace it with the wrapper host. Running Uno separately is only a temporary manual diagnostic path, not the scaffold pattern.

---

## Verification

- [ ] AppHost starts and dashboard is reachable
- [ ] All resources show "Running" in dashboard (not just "Starting")
- [ ] API/Gateway/Scheduler startup order works (`WaitFor`); migrator completes before DB-touching hosts start (`WaitForCompletion`)
- [ ] SQL/Redis references inject expected connection keys
- [ ] Scheduler runs with single replica
- [ ] Functions listeners start without connection refused errors
- [ ] Aspire resources match IaC resource list
- [ ] Optional emulators/dev tunnel are wired only when needed
