# Data Persistence (EF Core)

> **When to read:** Phase 5a, when building EF Core DbContexts, entity configurations, repositories (Trxn/Query split), or updater helpers for PostgreSQL (default `NonAzure` lane) or SQL Server / Azure SQL (`Azure` lane).
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

`AuditInterceptor<string, Guid?>` (from `EF.Data.Interceptors`) intercepts `SaveChangesAsync` on the transactional DbContext and publishes `AuditEntry<string, Guid?>` entries via `IInternalMessageBus` onto the background task queue. Construct it with an explicit empty sink list, `new AuditInterceptor<string, Guid?>(bus, [])`: its optional `IEnumerable<IAuditLogRepository>` parameter otherwise receives every registered sink from DI and awaits each inside the save, and a relational sink on the same context recurses.

**Pipeline:** `EF SaveChanges` -> `AuditInterceptor` captures changed entities -> publishes to `IInternalMessageBus` (returns immediately) -> background `AuditHandler` dequeues -> `IAuditLogRepository.AppendAsync()` (EF.Audit.Contracts) -> the lane's backend (relational `AuditLog` table on the default `NonAzure` lane; Azure Table `{project}audit` on `Azure`).

**Key design points:**
- `EntityBase` does **not** define audit properties. An entity that exposes timestamps implements `ITimestampedEntity` (`CreatedAtUtc`, `ModifiedAtUtc`, private setters); `DbContextBase` stamps them and `Version` on every save from its `Clock`. Do NOT inherit `AuditableBase<T>` unless `CreatedBy` / `ModifiedBy` must live on the entity itself.
- Both sinks are package code ([../support/ef-packages-optional.md](../support/ef-packages-optional.md) section Durable Audit): `RelationalAuditLogRepository<{Project}DbContextTrxn>` (EF.Audit.Data, `AddRelationalAuditLog<{Project}DbContextTrxn>`) over the app's own context, whose model maps `AuditLogRecordConfiguration` so the `AuditLog` table shares the app migration set, and `AzureTableAuditLogRepository` (EF.Audit.AzureTable, `AddAzureTableAuditLog`). Both derive `RecordedUtc` and every key from the UUIDv7 entry id, so a replay writes the same row: relational is one idempotent upsert on the tenant-first key; Azure Table uses `PartitionKey` `{tenantId}|{yyyyMMdd}`. A null tenant maps to `AuditSettings.SystemTenantId` (`_system`).
- The Azure Table sink never creates its table on the write path; a startup task calls `AzureTableAuditLogRepository.EnsureTableAsync` once.
- Fields tracked: `EntityType`, `EntityKey`, `Action` (Insert/Update/Delete), `StartedAtUtc`, `RecordedUtc`, `Metadata` (serialized property changes, `[Mask]` and `IsSensitive()` values written as `***`).
- **Fallback:** an unprovisioned sink registers `NoOpAuditLogRepository` (discards entries).

**Source files:**
| File | Purpose |
|------|--------|
| `Bootstrapper/Registration/RegisterServices.Database.cs` | Registers `AuditInterceptor` on Trxn DbContext with an empty sink list |
| `Bootstrapper/Registration/RegisterServices.Audit.cs` | Selects the lane's package sink (`AddRelationalAuditLog<TContext>` or `AddAzureTableAuditLog`) |
| `Application.MessageHandlers/AuditHandler.cs` | Appends bus audit messages to `IAuditLogRepository` |
| `EF.Audit.Contracts.IAuditLogRepository` | Repository contract (package type; never redefine it in the app) |
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

        // IDs, value objects, decimal, UTC: ef-configuration-template section Model Conventions
    }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);
        modelBuilder.HasDefaultSchema("{project}");
        modelBuilder.ApplyConfigurationsFromAssembly(typeof({Project}DbContextBase).Assembly);
        modelBuilder.ApplyOutboxModel("{project}");          // [MESSAGING] EF.Data.Outbox
        modelBuilder.ApplyInboxModel("{project}");           // [MESSAGING]
        modelBuilder.ApplyConfiguration(new AuditLogRecordConfiguration()); // [RELATIONAL AUDIT] EF.Audit.Data
        ApplyTenantQueryFilters<TenantId>(modelBuilder);     // named, fail-closed (multi-tenant.md)
        modelBuilder.RegisterVersionConcurrencyTokens();     // last: Version on every IVersionedEntity
    }
}

public class {Project}DbContextTrxn(DbContextOptions<{Project}DbContextTrxn> options)
    : {Project}DbContextBase(options) { }

public class {Project}DbContextQuery(DbContextOptions<{Project}DbContextQuery> options)
    : {Project}DbContextBase(options) { }
```

Register query context with `NoTracking` behavior. Both contexts are leased through `DbContextScopedFactory` with the explicit all-tenants rule ([multi-tenant.md](multi-tenant.md) section Automatic Query Filters). Provider options come from `UsePostgreSqlProvider` / `UseSqlServerProvider` over `RelationalProviderSettings` (retry, history table, command timeout, typed constraint exceptions such as `UniqueConstraintException`); with retry enabled, a user transaction runs inside `ResilientTransaction.New(db).ExecuteAsync(ct => work(ct), ct)`.

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

The concurrency token is the package `EntityBase.Version` (`long`), mapped by `RegisterVersionConcurrencyTokens()` and written by `DbContextBase` on save (1 after insert, incremented on each modified save), so its type and ETag representation are the same on every provider. Do not map provider tokens (SQL Server `rowversion`, PostgreSQL `xmin`).

Externally mutable aggregates use fail-on-conflict semantics. Missing required `If-Match` returns 428; a stale value returns 412 with the current ETag: the service calls `ConcurrencyGuard.Require(expectedVersion, entity.Version, ...)` after the load, which throws `PreconditionFailedException`, and the EF.AspNetCore `RequireIfMatch()` filter answers 412 with `ETag: "{current}"`. `SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct)` turns a lost update between load and save into `PreconditionFailedException` too; the policy-free save's raw `DbUpdateConcurrencyException` maps to 412 without an ETag in the exception handler, because `ExceptionHandlerMiddleware` clears response headers. `ClientWins` is allowed only for an explicitly recorded last-write-wins path. A broad `catch (Exception)` must not swallow `DbUpdateConcurrencyException` before the exception handler maps it.

A write whose outcome depends on what it read (a status guard, a filtered set such as "the open runs", a value computed from the stored one, a child add's replay-or-insert decision) and whose caller stated no version - a cancel racing a background update, a child add, an `If-Match: *` edit, not a user edit form - runs inside `repoTrxn.RetryOnConcurrencyAsync(async ct => { read; decide; await repoTrxn.SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct); return result; })`. Each attempt clears the change tracker, so read everything you change inside `work`: entities loaded before the call are detached, and pending changes make the call throw. `work` makes exactly one save and nothing else with an effect outside the database (no direct message publish, HTTP call or second save); stage events through the outbox in that save, and evict caches, delete blobs and build the response after the call returns. An HTTP caller that sent no version gets 409 (`ConflictException`) when the attempts run out, never 412. Never use `ClientWins` for such a write: `ClientWins` is last-write-wins per changed column, so it replays the stale decision. Do not hand-write version rewinds before a retried save; EF.Data's stamp is idempotent across failed and rolled-back saves.

A concrete `If-Match` edit or delete runs its read, `ConcurrencyGuard.Require` and one `Throw` save once, with no retry: the client's stale version is the conflict to report, as 412. `If-Match: *` is the trusted-automation override (a workflow node, an operator script): `ifMatch.ExpectedVersion` is `null`, the guard passes, and the same read, apply and one `Throw` save run inside the retry above, so a write landing between read and save makes it re-read and apply again; a wildcard write never answers 412. A wildcard PUT is a full replacement of the aggregate as re-read, so a child added concurrently and absent from the payload is deleted; a wildcard PATCH changes only the fields it carries. A wildcard delete whose retry finds the row gone after an earlier attempt sent its save counts as deleted for its after-save effects (cache eviction, blob delete); a first attempt that finds nothing stays not found. One app helper (`Application.Contracts`) owns both shapes; services and handlers call it, then evict caches:

```csharp
public static class ConcurrencyRetry
{
    public static async Task<T> RunAsync<T>(IRepositoryBase repo, long? expectedVersion,
        Func<CancellationToken, Task<T>> work, CancellationToken ct)
    {
        if (expectedVersion is not null) return await work(ct);   // concrete If-Match: once, 412 on a lost race
        try { return await repo.RetryOnConcurrencyAsync(work, 3, ct); }
        catch (Exception ex) when (ConcurrencyGuard.IsConcurrencyFailure(ex))
        {
            throw new ConflictException("The resource kept changing; retry the request.", ex);
        }
    }
    // Child adds (no If-Match) use an overload without expectedVersion that always retries.
}
```

A save with `acceptAllChangesOnSuccess: false` whose transaction committed is followed by `ChangeTracker.AcceptAllChanges()`; without it the next save checks the loaded version and fails with a concurrency conflict. `RetryOnConcurrencyAsync` is an `IRepositoryBase` member, so a hand-written fake of `IRepositoryBase`, `IRepositoryTrxn` or `IRepositoryQuery` implements it (mocking libraries need nothing).

### Idempotent Create

When the domain specification makes a create idempotent by caller id, the create accepts an optional caller-supplied UUIDv7 `Id` (`UuidV7.ValidateCallerId`) and the entity row is the idempotency record; no response-replay table exists. A create whose `Id` is stored replays: an equivalent payload returns 200 with the stored entity and its ETag, a divergent one is 409 (`ConflictException`), and a create that loses the insert race re-reads and decides the same way. Equivalence compares scalar fields (ignoring `Id`, `Version`, `TenantId` and children) of the request as the create would store it, defaults included and values at stored precision (the domain rounds decimals to their column scale and truncates timestamps to microseconds), so an identical resend replays. A child add replays by its child id inside the retry above.

A caller that cannot mint a UUIDv7 (a workflow engine, a retrying client) sends `Idempotency-Key`. An app endpoint filter on each create and child-add route (`.WithIdempotencyKey<TDto>(http => scope)`), when the body `Id` is null or `Guid.Empty`, maps (authoritative tenant, scope, key) to a stored UUIDv7: it reads the `IdempotencyKey` row (`TenantId`, `Scope`, `Key` max 200, `EntityId`, `CreatedUtc`; unique `TenantId`+`Scope`+`Key`) or inserts one with `Guid.CreateVersion7()` in its own `Throw` save, committed before the create; a failed insert is decided by an existence read, so a concurrent duplicate reuses the winner's id. The filter sets the body `Id` and the unchanged create runs, so the caller-`Id` replay deduplicates every retry, including one after a crash between the mapping commit and the create. A non-empty body `Id` wins and the header is ignored. The header must be one non-empty value of at most 200 characters, else 400 ProblemDetails. The scope names the route and its parent (`{entity}.create`, `{entity}.{child}.add:{parentId}` with the parsed parent id formatted `"D"`, never the raw route text), so one key used on two parents maps to two children. A child-add key is stored only after a tenant-filtered read finds the parent; otherwise the route answers its usual 404 and stores nothing. On SQL Server the `Key` and `Scope` columns use a binary collation (`Latin1_General_100_BIN2`), so keys that differ only by case stay distinct. A retention sweep purges mappings older than a configured window in bounded batches; a resend after it creates a new row. Never hash the key into the id: a UUIDv5 fails the UUIDv7 rule.

### Set-Based Writes and Query Shape

- `ExecuteUpdateAsync`/`ExecuteDeleteAsync` execute immediately in SQL and bypass the change tracker, `SaveChanges` interceptors (audit, outbox staging), domain methods, and the `Version` concurrency check. Use them for set-based work where no invariant, audit record, or integration event is required: work and projection tables, retention purges, and system-owned columns on an aggregate table (a notification marker, a scheduler cursor). A set-based write to a versioned row (`ExecuteUpdate`, an upsert, raw SQL) stamps it as the save pipeline would, through one shared helper on the setter chain (`.StampModified(now)`: `Version + 1` and the modified timestamp from the context clock; an inserted row stores `Version = 1` and created = modified = `now`). Otherwise a client's stale ETag still passes, and a stale PUT restores the value the statement removed. On an aggregate table the statement re-asserts its full candidate predicate in the `WHERE` so it acts as a compare-and-set against concurrent edits, and any side effect (deferred blob delete, outbox row) is staged in the same transaction (blob-backed rows: [azure-blob-storage.md](azure-blob-storage.md) section Attachment Rules). User-driven aggregate changes go through the root and `SaveChangesAsync`. Proof: TaskFlow `TaskItemSystemRepository`. When one must join a unit of work, open an explicit transaction and stage outbox rows explicitly ([messaging.md](messaging.md) section Transactional Producer: Outbox). Tenant query filters still apply because the statement is a LINQ query; prove it with a cross-tenant test per provider.
- A multi-statement job step (read, guard, stage) runs under `ResilientTransaction`, whose execution strategy re-runs the whole step, so each attempt starts from a clean change tracker and re-runs its reads, guards and staging against the rolled-back rows. Saves inside keep `acceptAllChangesOnSuccess: true` (deferring it leaves the first attempt's rows tracked as Added, and re-staged rows collide with them). The step returns the committed attempt's result; the job adds counts and runs side effects only after the call returns. A retry after a commit that landed is a no-op through the same guards. Stage a deterministic outbox or work id only for a row the step's own guarded write affected: one guarded `ExecuteUpdate`, insert-if-absent or `ExecuteDelete` per row, never staging every row of a set after a count-only guard (a row another replica affected first is staged twice and fails on the primary key).

  ```csharp
  public async Task<T> ExecuteInTransactionAsync<T>(Func<CancellationToken, Task<T>> work, CancellationToken ct)
  {
      DB.ChangeTracker.DetectChanges();
      if (DB.ChangeTracker.HasChanges()) throw new InvalidOperationException("Save or discard pending changes first.");
      T result = default!;
      await ResilientTransaction.New(DB).ExecuteAsync(async token =>
      {
          DB.ChangeTracker.Clear();   // every attempt re-reads, re-guards and re-stages
          result = await work(token).ConfigureAwait(ConfigureAwaitOptions.None);
      }, ct).ConfigureAwait(ConfigureAwaitOptions.None);
      return result;                  // the committed attempt's result; the caller counts it
  }
  ```
- `AsSplitQuery()` is a per-query choice for multiple collection includes with measured cartesian growth, never a global default. Each split is a separate round trip with no shared snapshot outside a snapshot-isolation transaction, and paged split queries need a deterministic order with a unique tie-breaker.
- Hot-path reads may use `EF.CompileAsyncQuery` or raw SQL after a benchmark. Raw SQL is parameterized through `FromSql`/`SqlQuery` interpolation; never concatenate values into `FromSqlRaw`.
- `ReadIsolation.ReadUncommitted` (`READ UNCOMMITTED` on one held session; `ReadUncommittedInterceptor` / `WithReadUncommittedAsync` from EF.Data.SqlServer) is a dirty read that can skip or duplicate rows while pages split. Limit it to approximate reads such as dashboard tiles. Search, cursor-paged feeds, and any read feeding a decision pass `ReadIsolation.Default`; on SQL Server prefer `READ_COMMITTED_SNAPSHOT` (the Azure SQL default) to avoid reader blocking.

---

## Entity Configuration

Key, `Id` value generation and `TenantId` come from the package `TenantEntityTypeConfiguration<TEntity, TId, TTenantId>`; `Version` from `RegisterVersionConcurrencyTokens()`. Generate no app base configuration. Shapes and the `ValueGeneratedNever()` aggregate-child rule: [ef-configuration-template.md](../templates/ef-configuration-template.md) section Key and Concurrency Mapping (package).

### Configuration Rules

1. Tenant-owned entities use the tenant-first key `(TenantId, Id)`; foreign keys to them are composite.
2. Every configuration calls `ToTable` (class-name aligned).
3. Set delete behavior explicitly (`Restrict` for references, `Cascade` for owned children).
4. Name indexes predictably (`IX_...` / `CIX_...`).
5. Set `HasMaxLength(N)` for strings; leave one unbounded only for genuinely large text.
6. Decimal precision and UTC temporals are provider-neutral conventions; name no provider column type ([ef-configuration-template.md](../templates/ef-configuration-template.md) section Model Conventions).

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

`DbContextBase.SaveChangesAsync(CancellationToken)` saves with no conflict strategy (audit fields and the `Version` increment still apply). Generated code always names the conflict strategy with the winner overload, so every write's concurrency choice is explicit in review.

```csharp
// CORRECT -- always use the 2-param overload; fail visibly on a concurrent write
await repoTrxn.SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct);

// WRONG -- no named strategy; a conflict surfaces as a raw DbUpdateConcurrencyException
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
- [ ] Domain ID, stable value-object, decimal-precision, and UTC temporal conventions are registered in `ConfigureConventions`, not per-property and not from an `OnModelCreating` reflection loop
- [ ] Each tenant entity has an explicit configuration deriving from `TenantEntityTypeConfiguration<TEntity, TId, TenantId>` and calling `base.Configure(builder)`
- [ ] `OnModelCreating` ends with `ApplyTenantQueryFilters<TenantId>` and `RegisterVersionConcurrencyTokens()`; `ConfigureConventions` calls `RegisterUtcTemporalConversions()`
- [ ] Repositories are split for write and read concerns
- [ ] Multi-provider apps have one provider-options branch, one migration assembly per provider, and the same real-database suite per arm
- [ ] Caller page size is clamped; high-cardinality cursor sorts include a unique tie-breaker
- [ ] `ExecuteUpdateAsync`/`ExecuteDeleteAsync` on an aggregate table touch only system-owned columns or retention, re-assert the predicate, and stage side effects in the same transaction; cursor feeds use `ReadIsolation.Default`
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
- Npgsql GSS encryption default on chiseled/minimal images - Npgsql defaults `GssEncryptionMode` to Prefer and probes for Kerberos libs the image intentionally lacks, printing a `libgssapi_krb5.so.2` load error on every startup. Set `GssEncryptionMode.Disable` unconditionally for password-auth deployments in the central provider-options helper, and pin it with a test against the effective `DbConnection.ConnectionString`. Do not guard with `NpgsqlConnectionStringBuilder.ContainsKey` - it reports whether a keyword is *supported*, not *present*, so the guard never fires.
- Member access on a value-converted property inside an EF-translated predicate - compiles and passes model validation, then fails at runtime with `InvalidOperationException: The LINQ expression ... could not be translated`. Build typed IDs/value objects outside the expression and compare the whole property. Use `.Value` only in domain code or post-materialization LINQ-to-objects.

---

**TaskFlow proof (local):** `../scaffold-proof/src/Infrastructure/TaskFlow.Infrastructure.Repositories/TaskItemRepositoryTrxn.cs` + `TaskItemRepositoryQuery.cs`, plus `../scaffold-proof/src/Host/TaskFlow.Bootstrapper/Registration/RegisterServices.Database.cs`
**TaskFlow proof (remote fallback):** <https://github.com/efreeman518/scaffold-proof/blob/main/src/Infrastructure/TaskFlow.Infrastructure.Repositories/TaskItemRepositoryTrxn.cs>
