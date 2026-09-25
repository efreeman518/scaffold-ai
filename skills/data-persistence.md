# Data Persistence (EF Core)

> **When to read:** Phase 5a, when building EF Core DbContexts, entity configurations, repositories (Trxn/Query split), or updater helpers for SQL Server / Azure SQL.
> **Skip if:** Cosmos/Table/Blob-only persistence (use `azure-data-storage.md` instead); pure domain work; phases 5b+ where data access is already wired.

## Repository Shape Ownership

[Repository Template](../templates/repository-template.md) owns generated bespoke Trxn/query classes and contracts. Start with [Generic Repository Pair](../templates/repository-template.md#generic-repository-pair-repositorycontractstyle-hybrid--generic-only). This skill owns `repositoryContractStyle` selection plus shared DbContext, audit, updater, concurrency, deletion, and persistence policy; keep implementation shapes in the template.

## Overview

Use EF Core with split read/write contexts, explicit entity configurations, repository abstractions, updater helpers for child synchronization, and concurrency-safe save paths.

Reference patterns: [../patterns/data-layer-wiring.md](../patterns/data-layer-wiring.md).
Base types (`DbContextBase`, `RepositoryBase`, `AuditInterceptor`, `SearchRequest`, `PagedResponse`): [../support/ef-packages-reference.md](../support/ef-packages-reference.md).

Load [../support/data-persistence-advanced.md](../support/data-persistence-advanced.md) only when the current task needs design-time factory setup, migrations, JSON column troubleshooting, startup seeding, or expand/contract guidance.

---

## Audit Strategy

`AuditInterceptor<string, Guid?>` (from `EF.Data.Interceptors`) intercepts `SaveChangesAsync` on the transactional DbContext and publishes audit records via `IInternalMessageBus` (fire-and-forget). The interceptor does **not** block the save - it enqueues an `AuditMessage` to a background `System.Threading.Channels` consumer.

**Pipeline:** `EF SaveChanges` -> `AuditInterceptor` captures changed entities -> publishes to `IInternalMessageBus` (returns immediately) -> background `AuditHandler` dequeues -> `IAuditLogRepository.AppendAsync()` -> Azure Table Storage (`{project}audit` table).

**Key design points:**
- `EntityBase` does **not** define audit properties (`CreatedAt`, `CreatedBy`, `UpdatedAt`, `UpdatedBy`). Do NOT inherit `AuditableBase<T>` unless audit fields must live on the entity itself.
- Audit metadata is stored externally in Azure Table Storage, keyed by `PartitionKey` = tenant ID (or `"_system"`) and `RowKey` = reverse-ticks (newest-first).
- Fields tracked: `EntityType`, `EntityKey`, `Action` (Insert/Update/Delete), `RecordedUtc`, `Metadata` (serialized property changes).
- **Fallback:** When Table Storage is unavailable (local dev without emulator), register `NoOpAuditLogRepository` - silently discards audit entries.

**Source files:**
| File | Purpose |
|------|--------|
| `Bootstrapper/Registration/RegisterServices.Database.cs` | Registers `AuditInterceptor` on Trxn DbContext |
| `Application.MessageHandlers/AuditHandler.cs` | Handles audit messages from internal bus |
| `Application.Contracts/Storage/IAuditLogRepository.cs` | Repository contract |
| `Infrastructure.Storage/AuditLogRepository.cs` | Azure Table Storage implementation |
| `Infrastructure.Storage/NoOpAuditLogRepository.cs` | No-op fallback |

---

## DbContext Design

### Split Pattern

```csharp
public abstract class {Project}DbContextBase(DbContextOptions options)
    : DbContextBase<string, Guid?>(options)
{
    protected override void ConfigureConventions(ModelConfigurationBuilder cb)
    {
        base.ConfigureConventions(cb);

        cb.RegisterDomainIdConversions(typeof(TenantId).Assembly);
        cb.Properties<Email>().HaveConversion<EmailValueConverter>().HaveMaxLength(320);
        cb.Properties<Locale>().HaveConversion<LocaleValueConverter>().HaveMaxLength(20);
    }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);
        modelBuilder.HasDefaultSchema("{project}");
        modelBuilder.ApplyConfigurationsFromAssembly(typeof({Project}DbContextBase).Assembly);
        ConfigureDefaultDataTypes(modelBuilder);
        SetTableNames(modelBuilder);
        ConfigureTenantQueryFilters(modelBuilder);
    }
}

public class {Project}DbContextTrxn(DbContextOptions<{Project}DbContextTrxn> options)
    : {Project}DbContextBase(options) { }

public class {Project}DbContextQuery(DbContextOptions<{Project}DbContextQuery> options)
    : {Project}DbContextBase(options) { }
```

Register query context with `NoTracking` behavior.

### Local Inspection Tools

For local-dev SQL inspection, use the **VS Code SQL extension** (`mssql`). When the Aspire AppHost is the SQL host, pin the host port to `38433` for non-test runs and connect via `Server=localhost,38433`.

See [aspire.md](aspire.md) -> *Local Explorer Tooling* for the canonical port matrix and the `isTesting` gate that keeps these ports out of test runs.

### Bootstrapper Alignment

Keep full registration details in [bootstrapper.md](bootstrapper.md):

- Pooled DbContext factories
- Audit interceptor on transactional context
- No-tracking and read optimizations on query context
- Retry and provider options

---

## Repository Pattern

See [repository-template.md](../templates/repository-template.md) for write/query repository implementations and interfaces.

Key rules:
- **A per-entity repository interface earns its place only when it adds logic beyond `RepositoryBase`/`IRepositoryBase`.** Under `repositoryContractStyle: hybrid`/`generic-only` (default `hybrid`), CRUD-only / append-only / join entities use the shared open-generic `IRepositoryTrxn<TEntity, TId>` / `IRepositoryQuery<TEntity, TId>` pair and get **no** per-entity repository - see [repository-template.md](../templates/repository-template.md) section Generic Repository Pair. Emit a bespoke per-aggregate repo only for multi-include loads, `UpdateFromDto` child sync, paged/projected `Search`, or polymorphic/hierarchy/multi-key queries.
- Write repo: `{Entity}RepositoryTrxn` with includes and `UpdateFromDto` delegation to DbContext extension.
- Query repo: `{Entity}RepositoryQuery` with paged search using EF-safe projector expressions; under `hybrid`/`generic-only` it extends `IRepositoryQuery<{Entity}, {Entity}Id>` so generic get/list stay inherited.
- Query predicates over converted columns compare the whole typed property to a typed constant built outside the expression (`e.TenantId == tenantId`, `u.Email == email`). Never use `.Value` or other member access on a value-converted property inside `Where`, `Any`, `ListAsync`, `QuerySpec`, or message-handler predicates.
- Use transactional repo for writes, query repo for read/projection.
- Repository code is library code; use `ConfigureAwait(ConfigureAwaitOptions.None)` on every awaited call.

### Updater Pattern

See [updater-template.md](../templates/updater-template.md) for full implementation.

> **Delegation pattern:** The updater is a **static extension method on `{Project}DbContextTrxn`** - this gives it access to `db.Delete()` for explicit EF change-tracker removal. Services call it through the repository: `DB.UpdateFromDto(entity, dto, relatedDeleteBehavior)` where `DB` is the DbContext property inherited from `RepositoryBase`.

Updater rules:

- Use railway `.Bind()` flow: `entity.Update(...).Bind(updatedEntity => DomainResult.Combine(...).Map(updatedEntity))` - parent update errors short-circuit child syncs.
- Centralize add/update/remove in one `SyncCollectionWithResult` call per child collection.
- Use `RelatedDeleteBehavior` parameter to gate deletion - `None` = no-op in removeFunc, otherwise `db.Delete(toRemove)` + collection remove.
- **Aggregate-parent `UpdateAsync` where the UI sends the full desired child list must pass `RelatedDeleteBehavior.RelationshipAndEntity`** - e.g. `repoTrxn.UpdateFromDto(entity, dto, RelatedDeleteBehavior.RelationshipAndEntity)`. The default `None` silently drops client-side removals and leaves orphaned rows. This is the canonical setting for the "edit page binds children to `_model.<Collection>` and saves in one call" UI pattern in [ui-blazor-forms.md](ui-blazor-forms.md) -> *Editing Parent Aggregates with Child Collections*.
- **GET endpoints that feed an aggregate edit page must `.Include()` the child navigations.** Without the includes, the edit page either shows empty children or falls back to per-collection search calls.
- **CRITICAL:** Call `db.Delete(toRemove)` in removeFunc, not just `collection.Remove()`. Without explicit EF delete, orphaned children remain in DB when relationship isn't cascade-delete.
- Null-coalesce DTO collections: `dto.Items ?? []` - null = no changes, empty = remove all.
- Keep collection diff logic out of services.

### SearchRequest Defaults (Critical)

See [troubleshooting.md](../support/troubleshooting.md) for the canonical paging defaults guidance and test/runtime failure patterns.

Aggregate counts (dashboard tiles, badge numbers) come from a count query over mapped columns, never from counting a fetched page - a 100-row page silently undercounts. When the natural filter property is `[NotMapped]`/computed and will not translate, filter on the underlying mapped columns instead of pulling rows into memory.

Clamp every caller-supplied page size on the server. Offset paging is acceptable for small/admin lists. High-cardinality or mutation-heavy feeds use keyset/cursor paging with a deterministic total order, including a unique ID tie-breaker, and fetch `limit + 1` rows to derive `HasMore` without a mandatory count query. Cursor payloads bind tenant, sort mode, sort key, and last ID; malformed, cross-tenant, or mismatched-sort cursors fail with 400 instead of silently restarting. Run the same page-through test against every configured database provider.

### Provider Branch and Concurrency Discipline

When `databaseProviders` contains more than one provider, keep one shared model and one provider-options branch. Provider selection, migrations assembly, history table, retry settings, and provider-only types belong in that branch; business repositories do not check the active provider. Generate a migration assembly and model-drift check per provider, then run the same integration/E2E behavior suite for every arm.

SQL Server `rowversion` and PostgreSQL `xmin` are acceptable provider-specific tokens for a single-provider app. A multi-provider API that exposes one aggregate ETag should prefer an app-managed `long Version` concurrency token stamped in `SaveChanges`, because its type and HTTP representation stay stable across providers. Record this choice explicitly; do not pretend two native tokens form one provider-neutral contract.

Externally mutable aggregates use fail-on-conflict semantics. Missing required `If-Match` returns 428; a stale value returns 412 with the current ETag. `ClientWins` is allowed only for an explicitly recorded last-write-wins path. A broad `catch (Exception)` must not swallow `DbUpdateConcurrencyException` before the exception handler maps it.

### Set-Based Writes and Query Shape

- `ExecuteUpdateAsync`/`ExecuteDeleteAsync` execute immediately in SQL and bypass the change tracker, `SaveChanges` interceptors (audit, outbox staging), domain methods, and the `RowVersion` check. Use them for set-based work where no invariant, audit record, or integration event is required: work and projection tables, retention purges, and system-owned columns on an aggregate table (a notification marker, a scheduler cursor). On an aggregate table the statement re-asserts its full candidate predicate in the `WHERE` so it acts as a compare-and-set against concurrent edits, and any side effect (deferred blob delete, outbox row) is staged in the same transaction. User-driven aggregate changes go through the root and `SaveChangesAsync`. Proof: TaskFlow `TaskItemSystemRepository`. When one must join a unit of work, open an explicit transaction and stage outbox rows explicitly ([messaging.md](messaging.md) section Transactional Producer: Outbox). Tenant query filters still apply because the statement is a LINQ query; prove it with a cross-tenant test per provider.
- `AsSplitQuery()` is a per-query choice for multiple collection includes with measured cartesian growth, never a global default. Each split is a separate round trip with no shared snapshot outside a snapshot-isolation transaction, and paged split queries need a deterministic order with a unique tie-breaker.
- Hot-path reads may use `EF.CompileAsyncQuery` or raw SQL after a benchmark. Raw SQL is parameterized through `FromSql`/`SqlQuery` interpolation; never concatenate values into `FromSqlRaw`.
- `readNoLock: true` (`ConnectionNoLockInterceptor`, `READ UNCOMMITTED`) is a dirty read that can skip or duplicate rows while pages split. Limit it to approximate reads such as dashboard tiles. Cursor-paged feeds and any read feeding a decision pass `readNoLock: false`; on SQL Server prefer `READ_COMMITTED_SNAPSHOT` (the Azure SQL default) to avoid reader blocking.

---

## Entity Configuration

Base configuration (CRITICAL -- must exist in every project):

```csharp
public abstract class EntityBaseConfiguration<TEntity, TId>(bool pkClusteredIndex = false)
    : IEntityTypeConfiguration<TEntity>
    where TEntity : EntityBase<TId>
    where TId : struct, IDomainId<TId>
{
    public virtual void Configure(EntityTypeBuilder<TEntity> builder)
    {
        builder.HasKey(e => e.Id).IsClustered(pkClusteredIndex);
        builder.Property(e => e.Id).ValueGeneratedNever();
        builder.Property(e => e.RowVersion).IsRowVersion();
    }
}
```

> **CRITICAL:** Every project must create this abstract base. ALL entity configurations MUST inherit from it (and call `base.Configure(builder)`). Without it, `RowVersion` won't function as a concurrency token, and `Id` may be auto-generated. The `ValueGeneratedNever()` line is also load-bearing for **aggregate child inserts**: it lets EF save a NEW child added to a tracked parent through a navigation collection (the `{Root}Updater` path) as an `INSERT` rather than misinferring it as `Modified` and throwing `DbUpdateConcurrencyException`. A child config that skips the base config silently reintroduces that bug for that entity. See [../templates/updater-template.md](../templates/updater-template.md) section New children and EF Added state.

See [ef-configuration-template.md](../templates/ef-configuration-template.md) for entity-specific configuration patterns.

### Configuration Rules

1. Keep PK non-clustered when clustered multi-tenant access index is used.
2. Use explicit table names (class-name aligned).
3. Set delete behavior explicitly (`Restrict` for references, `Cascade` for owned children).
4. Name indexes predictably (`IX_...` / `CIX_...`).
5. Set `HasMaxLength(N)` for strings (avoid `nvarchar(max)`).
6. Use default decimal precision; override only when domain requires it.
7. Use `datetime2` for `DateTime` columns.

---

## Advanced Topics

Load [../support/data-persistence-advanced.md](../support/data-persistence-advanced.md) when the current task needs:

- design-time factory setup,
- EF CLI prerequisites or migration commands,
- `ToJson()` / JSON column troubleshooting,
- startup seeding patterns,
- expand/contract guidance, or
- multi-store schema coordination.

---

## SaveChangesAsync Rules

`DbContextBase.SaveChangesAsync(CancellationToken)` **ALWAYS throws `NotImplementedException`** by design. The 1-param overload is intentionally blocked to force use of the concurrency-safe path.

```csharp
// CORRECT -- always use the 2-param overload; fail visibly on a concurrent write
await repoTrxn.SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct);

// WRONG -- throws NotImplementedException at runtime
await repoTrxn.SaveChangesAsync(ct);
```

The 2-param overload applies the selected concurrency policy. Use `Throw` for normal application writes so HTTP/application conflict handling remains reachable. Use client-wins or database-wins only when the design decision explicitly accepts one side overwriting the other.

> **Important:** `OptimisticConcurrencyWinner` is in `EF.Data.Contracts`. Add `global using EF.Data.Contracts;` to `Application.Services/GlobalUsings.cs`.

### Delete Pattern

`Delete(entity)` inherited from `RepositoryBase` marks the entity for deletion in the change tracker. **You MUST call it before `SaveChangesAsync`** -- simply loading an entity and saving will NOT delete it.

```csharp
var entity = await repoTrxn.Get{Entity}Async(id, false, ct);
if (entity == null) return Result.Success(); // idempotent
repoTrxn.Delete(entity);                     // marks for deletion
await repoTrxn.SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct);
```

## Verification

- [ ] Both `{App}DbContextTrxn` and `{App}DbContextQuery` exist
- [ ] Query context is configured for no-tracking reads
- [ ] Domain ID and stable value-object converters are registered in `ConfigureConventions`, not per-property and not from an `OnModelCreating` reflection loop
- [ ] Each entity has explicit `IEntityTypeConfiguration<T>` inheriting `EntityBaseConfiguration<TEntity, TId>`
- [ ] `EntityBaseConfiguration<TEntity, TId>` configures `HasKey`, `ValueGeneratedNever`, `IsRowVersion()`
- [ ] Repositories are split for write and read concerns
- [ ] Multi-provider apps have one provider-options branch, one migration assembly per provider, and the same real-database suite per arm
- [ ] Caller page size is clamped; high-cardinality cursor sorts include a unique tie-breaker
- [ ] `ExecuteUpdateAsync`/`ExecuteDeleteAsync` on an aggregate table touch only system-owned columns or retention, re-assert the predicate, and stage side effects in the same transaction; cursor feeds use `readNoLock: false`
- [ ] Externally mutable aggregates surface concurrency conflicts instead of silently applying `ClientWins`
- [ ] Read queries use projector expressions
- [ ] Update paths use updater sync pattern for child collections
- [ ] Design-time factory exists and uses `EFCORETOOLSDB` env var
- [ ] Migration name follows `YYYYMMDD_Description` format
- [ ] Each migration context pins `__EFMigrationsHistory` to its owned schema in the central provider-options helper; Npgsql never relies on `search_path`
- [ ] One migration per feature/slice -- no mega-migrations
- [ ] CLI commands use `--context {App}DbContextTrxn` (never query context)
- [ ] Data backfill uses background job (not inline migration SQL) for complex transforms
- [ ] Breaking schema changes use expand/contract across multiple deployments
- [ ] Production deployments use idempotent scripts
- [ ] No migration renamed after sharing
- [ ] Multi-store changes deploy code before SQL migration
- [ ] Mappings/repositories align with [entity-template.md](../templates/entity-template.md) and [repository-template.md](../templates/repository-template.md)

## Pitfalls

- Sharing one DbContext for transactional writes and query reads - defeats the Trxn/Query split, prevents no-tracking read configuration, and causes change-tracker pollution under load. Always emit both `{App}DbContextTrxn` and `{App}DbContextQuery` over the shared base.
- Skipping audit or tenant interceptors on a newly added DbContext - misses tenancy filtering and audit columns silently; the failure surfaces as cross-tenant data in tests months later.
- Updating aggregate roots with child collections without an `{Entity}Updater.cs` DbContext extension - client-side child removals silently drop because EF will not detach orphans without an explicit sync call. Use `CollectionUtility.SyncCollectionWithResult`.
- Inline backfill SQL inside an EF migration - blocks deployment on long-running data work and offers no retry handle. Use a background job for complex transforms; keep migrations idempotent and structural.
- Mega-migrations that bundle multiple features - hard to revert and obscures the diff. One migration per feature/slice, named `YYYYMMDD_Description`.
- Renaming a migration after it has been shared - every other developer's state diverges; never rename a migration once pushed.
- Npgsql GSS encryption default on chiseled/minimal images - Npgsql defaults `GssEncryptionMode` to Prefer and probes for Kerberos libs the image intentionally lacks, printing a `libgssapi_krb5.so.2` load error on every startup. Set `GssEncryptionMode.Disable` unconditionally for password-auth deployments in the central provider-options helper, and pin it with a test against the effective `DbConnection.ConnectionString`. Do not guard with `NpgsqlConnectionStringBuilder.ContainsKey` - it reports whether a keyword is *supported*, not *present*, so the guard never fires.
- Member access on a value-converted property inside an EF-translated predicate - compiles and passes model validation, then fails at runtime with `InvalidOperationException: The LINQ expression ... could not be translated`. Build typed IDs/value objects outside the expression and compare the whole property. Use `.Value` only in domain code or post-materialization LINQ-to-objects.

---

**TaskFlow proof (local):** `../scaffold-proof/src/Infrastructure/TaskFlow.Infrastructure.Repositories/TaskItemRepositoryTrxn.cs` + `TaskItemRepositoryQuery.cs`, plus `../scaffold-proof/src/Host/TaskFlow.Bootstrapper/Registration/RegisterServices.Database.cs`
**TaskFlow proof (remote fallback):** <https://github.com/efreeman518/scaffold-proof/blob/main/src/Infrastructure/TaskFlow.Infrastructure.Repositories/TaskItemRepositoryTrxn.cs>
