# Data Layer Wiring Patterns

Cross-project wiring for database context setup, startup tasks, migrations, and seed data. Load before Phase 5a (Foundation) and Phase 5b (App Core).

For base types used here (`DbContextBase`, `DbContextScopedFactory`, `AuditInterceptor`), see [../support/ef-packages-reference.md](../support/ef-packages-reference.md).

---

## Database Context Pooling & Scoped Wrappers

**Source:** `{App}.Bootstrapper/Registration/RegisterServices.Database.cs`

Dual-context registration: pooled factories only after their option delegates and interceptors pass lifetime validation, `DbContextScopedFactory` wrappers with the explicit all-tenants rule for scoped resolution, audit (and [MESSAGING] outbox staging) interceptors on Trxn only, one provider branch over the EF.Data provider packages (PostgreSQL on the default `NonAzure` lane; SQL Server or Azure SQL on the `Azure` lane), and an independently authored Query connection string.

On the `Azure` lane, set all SQL Server and Azure SQL EF registrations to compatibility level 170. This is SQL Server 2025 compatibility and enables native JSON type support, vector data types, and related indexing features.

### DbSet Declarations

Declare all DbSets in the **abstract base context**, not in the concrete Trxn/Query contexts. Use auto-property syntax with `null!` initializer:

```csharp
public abstract class {App}DbContextBase(DbContextOptions options)
    : DbContextBase<string, Guid?>(options)
{
    public DbSet<{Entity}> {Entities} { get; set; } = null!;
    public DbSet<{ChildEntity}> {ChildEntities} { get; set; } = null!;
    // ... all entity DbSets here
}
```

`{Entities}` / `{ChildEntities}` are the English plurals of the entity names (`Category` -> `Categories`, `TaskItem` -> `TaskItems`), never the singular token plus a literal `s` - that yields `Categorys`. See [../ai/placeholder-tokens.md](../ai/placeholder-tokens.md) section Derivation Rules. Phase 4 emits the identical shape in its DbContext shells - [../ai/contract-scaffolding.md](../ai/contract-scaffolding.md).

> **Do NOT** use the expression-body `=> Set<T>()` pattern - it creates a new `DbSet` instance on every access and defeats EF's internal caching.
>
> **One exception: a vendor interface-composition DbContext.** When `includeFlowEngine: true`, `{App}FlowEngineDbContext` composes the `EF.FlowEngine` interfaces (`IFlowEngineStateDbContext` + `IFlowEngineOutboxDbContext` + `IFlowEngineCircuitBreakerDbContext`) and satisfies their `DbSet` members with the expression body `=> Set<T>()`. That is the vendor's contract shape, and it is correct there. It applies only to the dedicated FlowEngine context and its vendor row types - never to `{App}DbContextBase` or any application entity DbSet.

### Registration

```csharp
private static void AddDatabaseServices(IServiceCollection services, IConfiguration config)
{
    // Repository registrations. Under repositoryContractStyle: hybrid/generic-only, register the
    // open-generic pair ONCE (serves every generic-coverable entity via the closed-over-context
    // subclasses) and add bespoke repos only where read/write logic earns a per-aggregate contract.
    services.AddScoped(typeof(IRepositoryTrxn<,>), typeof({App}RepositoryTrxn<,>));
    services.AddScoped(typeof(IRepositoryQuery<,>), typeof({App}RepositoryQuery<,>));
    services.AddScoped<I{Entity}RepositoryQuery, {Entity}RepositoryQuery>();   // bespoke only
    services.AddScoped<I{Root}RepositoryTrxn, {Root}RepositoryTrxn>();         // ALWAYS for aggregate roots with owned children (GR-15), even under generic-only
    // (repositoryContractStyle: per-entity - omit the open generics and register a pair per entity.)

    // Interceptors
    // Empty sink list: persistence goes through the bus handler (skills/data-persistence.md section Audit Strategy)
    services.AddTransient(sp => new AuditInterceptor<string, Guid?>(sp.GetRequiredService<IInternalMessageBus>(), []));
    // [MESSAGING] EF.Data.Outbox stages raised domain events in the same SaveChanges as the write
    // services.AddSingleton<IOutboxEventMapper, {App}OutboxEventMapper>();
    // services.AddOutbox<{App}DbContextTrxn>(o => o.DefaultDestination = {App}IntegrationEvents.Destination);
    // services.AddInbox<{App}DbContextTrxn>();

    ConfigureDatabaseContexts(services, config);
}
```

**Dual context wiring with pooling compatibility proof:**

```csharp
// The EF.Data tenant filter fails closed: a tenant-less context reads nothing unless marked all-tenants.
internal static bool AllowsAllTenants(IRequestContext<string, Guid?> rc) =>
    rc.TenantId is null && (rc.RoleExists(AppConstants.ROLE_SYSTEM) || rc.RoleExists(AppConstants.ROLE_GLOBAL_ADMIN));

private static void ConfigureSqlDatabase(IServiceCollection services, {App}DbProvider provider,
    string dbConnectionStringTrxn, string dbConnectionStringQuery)
{
    // -- TRXN context: audit interceptor (+ [MESSAGING] OutboxStagingInterceptor)
    services.AddPooledDbContextFactory<{App}DbContextTrxn>((sp, options) =>
    {
        options.Use{App}Provider(provider, dbConnectionStringTrxn);
        options.AddInterceptors(sp.GetRequiredService<AuditInterceptor<string, Guid?>>());
    });
    services.AddScoped(sp => new DbContextScopedFactory<{App}DbContextTrxn, string, Guid?>(
        sp.GetRequiredService<IDbContextFactory<{App}DbContextTrxn>>(),
        sp.GetRequiredService<IRequestContext<string, Guid?>>(),
        sp.GetService<TimeProvider>(),
        AllowsAllTenants));
    services.AddScoped(sp => sp.GetRequiredService<DbContextScopedFactory<{App}DbContextTrxn, string, Guid?>>()
        .CreateDbContext());

    // -- QUERY context: no audit interceptor, no-tracking
    services.AddPooledDbContextFactory<{App}DbContextQuery>((sp, options) =>
    {
        options.UseQueryTrackingBehavior(QueryTrackingBehavior.NoTracking);
        options.Use{App}Provider(provider, dbConnectionStringQuery);
    });
    services.AddScoped(sp => new DbContextScopedFactory<{App}DbContextQuery, string, Guid?>(
        sp.GetRequiredService<IDbContextFactory<{App}DbContextQuery>>(),
        sp.GetRequiredService<IRequestContext<string, Guid?>>(),
        sp.GetService<TimeProvider>(),
        AllowsAllTenants));
    services.AddScoped(sp => sp.GetRequiredService<DbContextScopedFactory<{App}DbContextQuery, string, Guid?>>()
        .CreateDbContext());
}
```

The all-tenants rule is owned by [../skills/multi-tenant.md](../skills/multi-tenant.md) section Automatic Query Filters.

**The one provider branch:** `provider` comes from the shared lane resolver (`HostingLaneResolver.Resolve(config).Database`). Runtime registrations, the migrator, design-time factories and test fixtures all call this one extension, so schema, history table, retry and timeout cannot drift.

```csharp
public static DbContextOptionsBuilder Use{App}Provider(this DbContextOptionsBuilder options,
    {App}DbProvider provider, string connectionString)
{
    var settings = new RelationalProviderSettings
    {
        ConnectionString = connectionString,
        MigrationsAssembly = {App}DbProviderSelector.MigrationsAssembly(provider),
        MigrationsHistoryTable = "__EFMigrationsHistory",
        MigrationsHistorySchema = "{app}",
        MaxRetryCount = 5,
        MaxRetryDelay = TimeSpan.FromSeconds(30)
    };
    return provider switch
    {
        {App}DbProvider.PostgreSql => options.UsePostgreSqlProvider(settings),        // NonAzure lane (default), EF.Data.PostgreSql
        {App}DbProvider.SqlServer => options.UseSqlServerProvider(settings, 170),     // Azure lane, EF.Data.SqlServer
        _ => throw new ArgumentOutOfRangeException(nameof(provider), provider, null)
    };
}
```

`UseSqlServerProvider` selects the Azure SQL flavor from the data-source host suffix and the generic SQL Server provider otherwise; both providers register the typed constraint-exception processor. The Query connection string is authored independently per environment: SQL Server callers put `ApplicationIntent=ReadOnly` in it, PostgreSQL callers point it at the read replica. Nothing is appended at runtime.

Pooling is an optimization, not a blanket context rule. Every service resolved by a pooled factory's options delegate is retained with the pool and must be safe for that lifetime; it must not capture request/tenant state or resolve a dependency that needs the same context. Register a context with scoped `AddDbContextFactory(..., ServiceLifetime.Scoped)` when a required interceptor or option dependency is genuinely scoped. Keep another context pooled when its dependency graph is safe.

Leave one DI composition test that builds with `new ServiceProviderOptions { ValidateScopes = true, ValidateOnBuild = true }`, creates a scope, resolves each `IDbContextFactory<T>`, and creates a context. This catches scoped-from-root capture and recursive factory construction before host startup. Test both selected database providers when their registrations differ.

Keep schema and history-table configuration inside this central provider helper so runtime, migrator, tests, and design-time factories cannot drift. Every provider arm sets the history schema explicitly through `RelationalProviderSettings`, never relying on PostgreSQL `search_path`.

---

## DbContext OnModelCreating Order

**Source:** `Infrastructure.Data/{App}DbContextBase.cs`

The base context inherits from `DbContextBase<string, Guid?>` (from EF.Data). `OnModelCreating` must follow this exact call order. **Why:** Package metadata must exist before app configuration, while the provider-only and tenant-filter passes require the complete entity model; reordering can overwrite app choices or make final passes miss entities. Therefore preserve the sequence below.

```csharp
public abstract class {App}DbContextBase(DbContextOptions options)
    : DbContextBase<string, Guid?>(options)
{
    protected override void ConfigureConventions(ModelConfigurationBuilder cb)
    {
        base.ConfigureConventions(cb);

        // Typed IDs, value objects, decimal precision, UTC temporals:
        // ef-configuration-template.md section Model Conventions
    }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);                                      // 1. Base class config

        modelBuilder.HasDefaultSchema("{schemaName}");                           // 2. Default schema

        modelBuilder.ApplyConfigurationsFromAssembly(                            // 3. All IEntityTypeConfiguration<T>
            typeof({App}DbContextBase).Assembly);

        modelBuilder.ApplyOutboxModel("{schemaName}");                          // 4. [MESSAGING] EF.Data.Outbox tables
        modelBuilder.ApplyInboxModel("{schemaName}");

        ConfigurePostgreSqlModel(modelBuilder);                                  // 5. Forced provider-only types
        ApplyTenantQueryFilters<TenantId>(modelBuilder);                         // 6. Named, fail-closed tenant filter (EF.Data)
        modelBuilder.RegisterVersionConcurrencyTokens();                         // 7. Version token on every IVersionedEntity
    }
```

Type-level conventions run in `ConfigureConventions`, before EF discovers the model, and are owned by [../templates/ef-configuration-template.md](../templates/ef-configuration-template.md) section Model Conventions. `ConfigurePostgreSqlModel` is the only provider branch in the model: it returns unless `Database.ProviderName` is Npgsql and maps the types SQL Server cannot create (`jsonb`, `vector` and its extension), so the SQL Server migration snapshot never carries them. Omit it when the model has no provider-only type.

**Tenant query filter** -- `ApplyTenantQueryFilters<TenantId>` (EF.Data) applies the named filter `"Tenant"` to every root entity implementing `ITenantEntity<TenantId>`; generate no filter loop. It fails closed: a context with no tenant reads nothing unless the scoped factory's all-tenants rule marks it `AllTenants` ([../skills/multi-tenant.md](../skills/multi-tenant.md) section Automatic Query Filters).

Table names come from each configuration's `ToTable` ([../templates/ef-configuration-template.md](../templates/ef-configuration-template.md)); the base context runs no table-naming loop.

---

## Startup Tasks

`IStartupTask` (EF.Host) is the interface for tasks that run after `builder.Build()` but before the host accepts requests. The Bootstrapper's `app.RunStartupTasks()` registers the message handlers and calls EF.Host's `RunStartupTasksAsync`, which runs every registered task in registration order, one DI scope each ([../skills/bootstrapper.md](../skills/bootstrapper.md)).

### Registration

```csharp
public static partial class RegisterServices
{
    private static void AddStartupTasks(IServiceCollection services)
    {
        services.AddStartupTask<WarmupDependencies>();
        services.AddStartupTask<LoadCacheStartup>();
    }
}
```

Startup tasks are runtime warm-up only (cache preload, dependency warmup, local-dev seeding). Schema migrations never run here - the dedicated `{App}.DatabaseMigrator` host owns them (see [../support/data-persistence-advanced.md](../support/data-persistence-advanced.md) section Migration Ownership: Dedicated Migrator Host).

### Example: Cache Warming

```csharp
public class LoadCacheStartup(
    IConfiguration config,
    ILogger<LoadCacheStartup> logger,
    ITypedCache cache,
    IRepositoryQuery<{Entity}, {Entity}Id> repoQuery) : IStartupTask
{
    public async Task ExecuteAsync(CancellationToken cancellationToken)
    {
        logger.LogInformation("Startup LoadCache Start");
        // Use ITypedCache.SetAsync to preload hot data from repoQuery
        await Task.CompletedTask;
        logger.LogInformation("Startup LoadCache Finish");
    }
}
```

### Example: Seed Data (Local Development)

```csharp
public class SeedDataTask(
    IDbContextFactory<{App}DbContextTrxn> factory,
    IHostEnvironment env,
    ILogger<SeedDataTask> logger) : IStartupTask
{
    public async Task ExecuteAsync(CancellationToken ct)
    {
        if (!env.IsDevelopment()) return;

        using var db = await factory.CreateDbContextAsync(ct);
        db.AuditId = SeedConstants.DevUserId.ToString();
        db.AllTenants = true;   // the fail-closed tenant filter hides every row from a tenant-less context
        if (await db.Set<{Entity}>().AnyAsync(ct)) return; // already seeded

        // Seed the dev tenant FIRST (and the dev user, when the app models users as an entity with an
        // owner FK) so the write-identity seam and the Scaffold fixed principal - which carry SeedConstants.DevUserId
        // / DevTenantId as claims - resolve their FKs. Apps whose "owner" is just the audit-id string
        // (the IRequestContext<string, Guid?> default) need only the tenant.
        db.Add(Tenant.Create("Dev Tenant", SeedConstants.DevTenantId));
        db.Add(User.Create(SeedConstants.DevUserId, "Scaffold Principal", SeedConstants.DevTenantId)); // when a user entity exists
        db.Add({Entity}.Create("Sample {Entity}", SeedConstants.DevTenantId));
        await db.SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct);
        logger.LogInformation("Seed data applied for local development.");
    }
}
```

**Rules:**
- Guard with `AnyAsync` - idempotent, safe on repeat runs.
- Gate dev-only tasks with `IHostEnvironment.IsDevelopment()`.
- Use deterministic IDs for the dev tenant and dev user (`SeedConstants.DevTenantId`,
  `SeedConstants.DevUserId`) so the dev write-identity seam, the Scaffold fixed principal, and tests can all
  reference the same rows. See [../support/data-persistence-advanced.md](../support/data-persistence-advanced.md)
  section Startup Seeding and [api-host-wiring.md](api-host-wiring.md) section Dev-Mode Write Identity.

---

## Scaffold Migration Strategy

> **Greenfield only (GR-13):** This single-baseline strategy applies to a fresh `/scaffold` build. `/scaffold-adopt` and `/vertical-slice` run against an established app and MUST preserve existing migration history - add an additive migration (`dotnet ef migrations add <Change>`) instead. Do not run `migrations remove --force` in those flows.

**Rule (greenfield):** the schema is still evolving, so keep one clean `InitialCreate` baseline rather than accumulating incremental migrations:

```powershell
dotnet ef migrations add InitialCreate `
  --project src/Infrastructure/{Project}.Infrastructure.Data `
  --startup-project src/Host/{Host}.Api `
  --context {App}DbContextTrxn
```

> **Removing an existing baseline is gated, not routine.** `dotnet ef migrations remove --force` is destructive and is owned by [../support/execution-gates.md](../support/execution-gates.md) section 5a (Lifecycle guard, GR-13): run it **only** when `.scaffold/resource-implementation.yaml` declares `migrationLifecycle: unreleased-resettable` **and** every affected environment has passed the reset/backup guard. The canonical default is `preserved-append-only`, under which shared migrations are never removed - re-baselining a default greenfield scaffold means adding an additive migration instead. Take the command and its per-provider repetition rule from `execution-gates.md`; do not re-derive it here.

> **`--startup-project` must reference `Microsoft.EntityFrameworkCore.Design`.** The commands above point `--startup-project` at the API host - that only works if the API references the Design package. If the scaffold keeps the Design reference and a `DesignTimeDbContextFactory` in the **Data project only**, use the Data project as **both** `--project` and `--startup-project`:
>
> ```powershell
> dotnet ef migrations add InitialCreate `
>   --project src/Infrastructure/{Project}.Infrastructure.Data `
>   --startup-project src/Infrastructure/{Project}.Infrastructure.Data `
>   --context {App}DbContextTrxn
> ```
>
> Pointing `--startup-project` at a host that does not reference Design fails with "doesn't reference Microsoft.EntityFrameworkCore.Design". Pick one rooting consistently across `add`, `remove`, and the production bundle.

**When to run:**
- After Phase 5a (all entities + DbContext configured)
- After any entity/relationship change during scaffolding
- Before Phase 5e tests that need a database

**Post-scaffold:** Once the baseline is established and the project is in production, switch to incremental migrations with descriptive names.

**Mapping-foundation neutrality gate:** After refactoring how typed IDs or value objects are mapped, prove the change is schema-neutral before adding or regenerating migrations:

```powershell
dotnet ef migrations has-pending-model-changes `
  --project src/Infrastructure/{Project}.Infrastructure.Data `
  --startup-project src/Host/{Host}.Api `
  --context {App}DbContextTrxn
```

Use the same `--project` / `--startup-project` rooting that real migrations use. If the Data project itself carries the design-time factory and `Microsoft.EntityFrameworkCore.Design`, you may run with the Data project as startup instead. The command must report `No changes`. If it reports drift, a facet moved (max length, nullability, default, column type, or FK shape). Reconcile the runtime model configuration. Do not blind-regenerate a migration for a mapping-foundation refactor.

### Production migration execution

Schema is never applied by runtime hosts, in any environment. The dedicated `{App}.DatabaseMigrator` host applies every migration target - locally under Aspire (runtime hosts `WaitForCompletion`), and in Azure as a one-shot Container Apps Job run from the pipeline before runtime rollout. Canonical rules (target ordering, history tables, timeouts, identity split): [../support/data-persistence-advanced.md](../support/data-persistence-advanced.md) section Migration Ownership: Dedicated Migrator Host. Pipeline step: [../skills/cicd.md](../skills/cicd.md) section Production DB Migration (Migrator Job).
