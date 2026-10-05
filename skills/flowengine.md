# FlowEngine (EF.FlowEngine)

Durable, JSON-defined workflow orchestration. Load when `includeFlowEngine: true` in `.scaffold/resource-implementation.yaml`.

## Prerequisites

- [solution-structure.md](solution-structure.md), [bootstrapper.md](bootstrapper.md), [data-persistence.md](data-persistence.md), [aspire.md](aspire.md)
- [../support/ef-packages-optional.md](../support/ef-packages-optional.md) section Workflow Engine and section FlowEngine Data-Layout Variants

## Non-Negotiables

1. FlowEngine is a **separate DbContext** from the app's primary `{Project}DbContextTrxn`. Do not subclass `DbContextBase<TUser,TKey>` - use interface composition.
2. Default data layout is **Variant A** (same database, separate schema), the only layout that preserves FE's atomic outbox. `separate-db` degrades `message`/`integration`/`agent` delivery to best-effort - flag in `HANDOFF.md` and wire FE message nodes to the app's at-least-once publisher.
3. Workflow JSON is **content-copied** by the API csproj and seeded by `AddWorkflowJsonSeeding()`; the test project guards file presence.
4. FE migrations use their own history table (never the app's `__EFMigrationsHistory`) and a dedicated startup task.
5. Admin endpoints use an **explicit prefix**: `MapFlowEngineAdmin(prefix: "/api/flowengine")`; the default drifts.
6. **The node `retryPolicy` is the sole retry owner.** Every `integration` node sets one (`{ "maxAttempts": 3, "backoff": "Exponential" }`); the client sends once per attempt. An unsafe method (POST, PUT, PATCH, DELETE) retries only 409, 429 and 503 unless the node sets `idempotencyKeyHeader` and the API deduplicates by that header ([data-persistence.md](data-persistence.md) section Idempotent Create). 412 never appears in a retry list. A loop-body node resolves its policy from the node, else the nearest enclosing loop, else the workflow default; attempts never multiply. A loop-body POST sets `"idempotencyKeyHeader": "Idempotency-Key"` and a `retryPolicy` exactly like a top-level POST: the engine generates one key per iteration, stable across retries and lease recovery. `idempotencyKey` in config is metadata only.
7. **HTTP and self-call clients use a dedicated named client:** `services.AddHttpClient(name, c => c.BaseAddress = ...)` plus `fe.AddResilientHttpClient(clientRef, name)`. The package removes the inherited ServiceDefaults handler from that name and adds a no-retry pipeline that keeps the timeout and circuit breaker. Created per request, so a workflow can call its host. Never hand-build a `ResilientHttpFlowClient` or suppress `RemoveAllResilienceHandlers` for it.
8. **Definition validation is strict.** An unknown config key is an error; canonical keys: loop `items`, integration `path` and `body`, decision `target` (not `over`, `request`, `valuePath`, integration-as-URL, `_loopItem`, or an undefined `storeAs`). Every `clientRef` on every node, untaken branches included, must be registered before definitions are saved or seeded, or host start fails (`WorkflowDefinitionValidationException.Details`: `CLIENT_NOT_REGISTERED`, `CLIENT_TYPE_MISMATCH`, `DEFINITION_INVALID`) and Admin API saves return 400. A `query` node needs an `IQueryClient`; a `document` node has no `clientRef` and reads through `UseDocumentStore`.
9. **Loops.** An inline body (`bodyEntryNodeId`) runs only its entry node per iteration, in the shared parent context. A multi-node per-item flow uses a child workflow (`subWorkflowId`) that reads `$.params.<itemAs>` (default `currentItem`) in its own context; `mode: parallel` is safe only with child workflows.
10. **Tenant.** Start every tenant-scoped instance with `StartRequest.TenantId`; loop, workflow and parallel children inherit it. An `IDocumentStore` receives the instance tenant and refuses a null or different one; a document node reads only ids from a tenant-scoped API search in the same workflow. An API search filter carries `"tenantId": "$.params.tenantId"`.

---

## Solution Layout

```
src/
  Infrastructure/
    {Project}.Data/
      {Project}DbContextTrxn.cs          # primary app context
      {Project}FlowEngineDbContext.cs    # FE context - interface composition
      FlowEngineSqlOptions.cs            # FE-specific SQL options
    {Project}.Bootstrapper/
      RegisterServices.FlowEngine.cs     # partial: AddFlowEngine chain
  Host/
    {Project}.Api/
      Workflows/                         # workflow JSON, copied to output
tests/
  Test.Integration.{Project}.FlowEngine/ # guard tests (flowengine-test-template.md)
```

---

## DbContext (interface composition)

`{Project}DbContextTrxn` inherits `DbContextBase<string, Guid?>` for the audit interceptor, so it cannot also inherit FE's `FlowEngineOutboxDbContext` / `FlowEngineCircuitBreakerDbContext`. Use a fresh DbContext declaring all three roles via interfaces.

```csharp
using EF.FlowEngine.Persistence;
using Microsoft.EntityFrameworkCore;

namespace {Project}.Data;

public sealed class {Project}FlowEngineDbContext(DbContextOptions<{Project}FlowEngineDbContext> options)
    : DbContext(options),
      IFlowEngineStateDbContext,
      IFlowEngineOutboxDbContext,
      IFlowEngineCircuitBreakerDbContext
{
    public const string SchemaName = "flowengine";
    public const string MigrationsHistoryTable = "__EFMigrationsHistory_FlowEngine";

    public DbSet<WorkflowInstance> WorkflowInstances => Set<WorkflowInstance>();
    public DbSet<OutboxEntry> OutboxEntries => Set<OutboxEntry>();
    public DbSet<CircuitBreakerState> CircuitBreakerStates => Set<CircuitBreakerState>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.HasDefaultSchema(SchemaName);
        modelBuilder.ApplyFlowEngineStateConfiguration();
        modelBuilder.ApplyFlowEngineOutboxConfiguration();
        modelBuilder.ApplyFlowEngineCircuitBreakerConfiguration();
    }
}
```

History-table isolation:

```csharp
public static class FlowEngineSqlOptions
{
    public static void Configure(SqlServerDbContextOptionsBuilder b)
    {
        b.UseCompatibilityLevel(170);
        b.MigrationsAssembly(typeof({Project}FlowEngineDbContext).Assembly.FullName);
        b.MigrationsHistoryTable(
            {Project}FlowEngineDbContext.MigrationsHistoryTable,
            {Project}FlowEngineDbContext.SchemaName);
    }
}
```

---

## Registration (Bootstrapper partial)

```csharp
// RegisterServices.FlowEngine.cs
public static partial class RegisterServices
{
    public static IServiceCollection AddFlowEngine(this IServiceCollection services, IConfiguration cfg)
    {
        var connectionString = cfg.GetConnectionString("Default")
            ?? throw new InvalidOperationException("Connection string 'Default' is required for FlowEngine.");

        services.AddDbContext<{Project}FlowEngineDbContext>(opts =>
            opts.UseSqlServer(connectionString, FlowEngineSqlOptions.Configure));

        var fe = services.AddFlowEngine()
            .UseStateStoreSql<{Project}FlowEngineDbContext>()
            .UseLockProviderSql<{Project}FlowEngineDbContext>()
            .UseWorkflowRegistrySql<{Project}FlowEngineDbContext>()
            .UseHumanTaskStoreSql<{Project}FlowEngineDbContext>()
            .UseOutboxSql<{Project}FlowEngineDbContext>()
            .UseCircuitBreakerSql<{Project}FlowEngineDbContext>();

        // Self-call: dedicated named client, node retryPolicy owns retries (Non-Negotiable 7)
        services.AddHttpClient("{project}-api", c => c.BaseAddress = new Uri(cfg["FlowEngine:ApiBaseUrl"]!));
        fe.AddResilientHttpClient("{project}-api", "{project}-api");
        fe.AddServiceBusClient("integration-events",
            sp => sp.GetRequiredService<IAzureClientFactory<ServiceBusClient>>().CreateClient("{Project}SBClient"),
            cfg["FlowEngine:ServiceBusTopic"]!);
        fe.AddChatClientAgentClient(clientRef: "ai-agent", chatClientFactory: sp => sp.GetRequiredService<IChatClient>());

        fe.AddWorkflowJsonSeeding(opts =>
        {
            opts.Directory = "Workflows";
            opts.SearchPattern = "*.json";
            opts.ActivateOnSeed = true;
        });

        return services;
    }
}
```

Call it from `RegisterServices.AddInfrastructure`.

## Migration target

The FE context is an ordered target in the dedicated migrator host; no runtime host migrates it (see [../support/data-persistence-advanced.md](../support/data-persistence-advanced.md) section Migration Ownership: Dedicated Migrator Host):

```csharp
.AddEfCoreMigrationTarget<{Project}FlowEngineDbContext>("{Project}FlowEngineDbContext", 20)
```

The migrator's FE context registration and the FE design-time factory apply `FlowEngineSqlOptions.Configure` so the `flowengine` schema keeps its own history table. `AddWorkflowJsonSeeding` seeds definitions, never schema.

## Workflow JSON content copy

In the API csproj:

```xml
<ItemGroup>
  <Content Include="Workflows\*.json">
    <CopyToOutputDirectory>PreserveNewest</CopyToOutputDirectory>
  </Content>
</ItemGroup>
```

The file-presence guard ([../templates/flowengine-test-template.md](../templates/flowengine-test-template.md)) catches a broken glob.

## Admin API mapping

In `WebApplicationBuilderExtensions`:

```csharp
app.MapFlowEngineAdmin(prefix: "/api/flowengine");
```

## Trigger model

Something must invoke each workflow. Canonical patterns in [../templates/flowengine-trigger-template.md](../templates/flowengine-trigger-template.md):

- **Service Bus subscriber in `{Project}.Functions`** - `includeFunctionApp: true`, an integration event starts a workflow.
- **Inline call from a service** - an in-process command.
- **TickerQ recurring job in `{Project}.Scheduler`** - `includeScheduler: true`, a cron starts it.

`IWorkflowTrigger` is an app-level facade over `IFlowEngine`, not an FE interface. Generate it in `{Project}.Application.Services`.

---

## Phase Routing

| Phase | What FlowEngine adds |
|---|---|
| **2** | `includeFlowEngine: true`, `flowEngineDbStrategy: same-db-separate-schema` (Variant A default). For `separate-db`, record the outbox trade-off in `.scaffold/DESIGN-DECISIONS.md`. |
| **3** | Add FE NuGet packages to the package matrix and verify feed access: `EF.FlowEngine`, `.StateStore.Sql`, `.Locks.Sql`, `.WorkflowRegistry.Sql`, `.HumanTaskStore.Sql`, `.Outbox.Sql`, `.CircuitBreaker.Sql`, `.Clients.Http`, `.Clients.Sql`, `.Clients.ServiceBus` (if Service Bus), `.Clients.AI` (if AI), `.AdminApi`, `.Testing`. |
| **5a** | Generate `{Project}FlowEngineDbContext`, `FlowEngineSqlOptions`, and the FE migration; no FE tables in the app's `OnModelCreating`. |
| **5b** | Generate `RegisterServices.FlowEngine.cs` partial, register the FE context as a migrator target in `{Project}.DatabaseMigrator`, and add the `MapFlowEngineAdmin` call in the API host. Add one placeholder workflow JSON to `Workflows/` and the seeding hosted service. |
| **5c** | Emit the chosen trigger template(s) when `includeFunctionApp` or `includeScheduler` is on. |
| **5d** | Generate `Test.Integration.{Project}.FlowEngine` with the guards (file-presence, deserialize, validate, registry round-trip, builder, retry policy, client registration, structured warnings, loop-body keys). |
| **5e** | When AI is in scope, FE `agent` nodes use `AddChatClientAgentClient` over the app's existing `IChatClient` ([ai-integration.md](ai-integration.md)). |

## Anti-patterns

- Subclassing the FE outbox/circuit-breaker abstract bases, adding FE `DbSet`s to the app's primary DbContext, or sharing `__EFMigrationsHistory` (Non-Negotiables 1 and 4).
- Omitting the file-presence test (silent "workflow not found" at start).
- FE `message` nodes under `separate-db` without an at-least-once relay.
