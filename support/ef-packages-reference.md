# Shared Base-Type Reference (canonical example: `EF.*`)

The scaffolded project depends on a set of shared base-type contracts (entity bases, repository bases, request context, results, paged response, specifications, messaging interfaces, etc.). The tables below describe those contracts and apply equally to every `packageStrategy`.

How those contracts are delivered depends on `packageStrategy` in `.scaffold/resource-implementation.yaml`:

| `packageStrategy` | Delivery |
|---|---|
| `feed` | All layers consumed as NuGet packages `<packagePrefix>.<Layer>` from `customNugetFeeds`. |
| `local` | All layers generated as packable projects under `src/Packages/<packagePrefix>.<Layer>` and consumed via `<ProjectReference>`. |
| `hybrid` | Feed-supplied layers consumed as NuGet packages; layers listed in `localPackageLayers` generated under `src/Packages/<packagePrefix>.<Layer>` and consumed via `<ProjectReference>`. Same prefix in both cases. |

Throughout this file, `EF` is the **canonical example prefix** (used by the reference app TaskFlow and the [efreeman518/EF.Packages](https://github.com/efreeman518/EF.Packages) repo). Substitute your `packagePrefix` everywhere you see `EF.<Layer>` below. The type signatures themselves are identical regardless of prefix.

Do not regenerate these types into your application/domain/host layers - they live in `<packagePrefix>.*` only, whether package or project. Which project references which package: [../skills/package-dependencies.md](../skills/package-dependencies.md) section Package Map.

> **Pre-flight:** When `packageStrategy: feed` or `hybrid`, configure the private feed in `nuget.config` before Phase 4; local environments need package read access exposed through `NUGET_AUTH_TOKEN` or an equivalent credential provider. When `packageStrategy: local`, no feed configuration is needed for these layers (only `nuget.org` is required). Verify with `configure-ef-packages-feed.py --check-only` (exit 0) in Phase 3 and `dotnet restore` once the Phase 4 solution exists. See [execution-gates.md](execution-gates.md).

---

## Key Types by Layer

Capability-gated packages (CQRS, column encryption, auth and the gateway claims relay, rate limiting, messaging with the outbox and inbox, scheduling, storage, Key Vault, gRPC, AI, Graph, durable audit, UI client, client resilience, observability exporters and data protection, test infrastructure, utilities, and the Enterprise FlowEngine / FilterBuilder) live in [ef-packages-optional.md](ef-packages-optional.md); load it when the capability is in scope.

> **Verified against the EF.Packages source.** If a type is not listed here, it either does not exist in EF.Packages or has not been verified. Check the actual assemblies (or the source repo linked above) before assuming a type exists. Generated code never uses a member the package marks `[Obsolete]`: with warnings as errors it breaks the build.

### Domain Layer (EF.Domain, EF.Domain.Contracts)

| Type | Package | Used For |
|---|---|---|
| `EntityBase<TId>` (`where TId : struct, IDomainId<TId>`) / `EntityBase` (Guid) | EF.Domain | Base class for all domain entities: UUIDv7 `Id` and the `long Version` concurrency token (1 after insert, incremented on every modified save by `DbContextBase`). No audit or timestamp fields. |
| `AuditableBase<TAuditIdType>` | EF.Domain | Guid-keyed `EntityBase` plus `IAuditable<TAuditIdType>` with private setters, stamped on save |
| `DomainEventContainer` | EF.Domain | Per-aggregate event buffer behind `IHasDomainEvents` |
| `CollectionUtility.SyncCollectionWithResult` | EF.Domain | Desired-state child collection sync for updaters ([../templates/updater-template.md](../templates/updater-template.md)) |
| `DomainException` | EF.Domain (`EF.Domain.Exceptions`) | Domain exception base |
| `IDomainId<TSelf>` (`where TSelf : struct, IDomainId<TSelf>`), `DomainId.FromNullable<TId>(Guid?)` | EF.Domain.Contracts | Typed ID contract; nullable-Guid conversion |
| `IEntityBase<TKey>`, `IVersionedEntity` | EF.Domain.Contracts | Entity base interface; `long Version` concurrency contract |
| `ITenantEntity<TTenantIdType>` (`where TTenantIdType : struct`) | EF.Domain.Contracts | Tenant-scoped entity marker (`TenantId { get; init; }`); drives the tenant query filter and `TenantEntityTypeConfiguration` |
| `ITimestampedEntity` (`CreatedAtUtc`, `ModifiedAtUtc`) / `IAuditable<TAuditIdType>` (adds `CreatedBy`, `ModifiedBy`) | EF.Domain.Contracts | Save-time stamps: `DbContextBase` writes them through the change tracker, so the entity exposes getters with private setters |
| `IDomainEvent`, `IHasDomainEvents` | EF.Domain.Contracts | Events an aggregate raises; `EF.Data.Outbox` stages them in the same save |
| `MaskAttribute` | EF.Domain.Contracts | The one redaction attribute: audit payloads (Added and Modified) and `SerializeToJson` |
| `DomainGuard` | EF.Domain.Contracts | Argument guard helpers for domain code |
| `DomainResult<T>` | EF.Domain.Contracts | Railway-style result for domain operations. Properties: `Value`, `IsSuccess`, `IsFailure`, `IsNone`, `ErrorMessage` (aggregated string), `Errors` (`IReadOnlyList<DomainError>`). Static: `Success(T)`, `Failure(string error)`, `Failure(string code, string error)`, `Failure(IReadOnlyList<DomainError>)`, `Failure(Exception)`, `None()`. Instance: `Match` - the failure branch receives `IReadOnlyList<DomainError>`; the generic form adds a 3-branch overload with `onNone`. |
| `DomainResult` | EF.Domain.Contracts | Non-generic domain result. Same shape as `DomainResult<T>` minus `Value`/`IsNone`. |
| `DomainError` | EF.Domain.Contracts | Typed error. Properties: `Error` (the human message), `Code` (machine key), `Message` (alias for `Error`). Static factories: `Create(string error)` (no code key) and `Create(string error, string code)`. **Argument order trap (GR-14):** `Create` takes the human message FIRST, code second - the reverse of `DomainResult.Failure(string code, string error)`. Do not infer order from the names; verify against this row or a compiled call site. Never access `.Message` from `Exception` - use `.Error` or `.Message` (same). **Propagation pattern:** `if (r.IsFailure) return Result<T>.Failure(r.ErrorMessage!);` or `Result<T>.Failure(r.Errors)`. |

### Data Access Layer (EF.Data, EF.Data.Contracts)

| Type | Package | Used For |
|---|---|---|
| `DbContextBase<TAuditIdType, TTenantIdType>` | EF.Data | Save pipeline: stamps `ITimestampedEntity` / `IAuditable` and `Version` from `Clock`. Exposes `AuditId`, `TenantId`, `AllTenants`, `Clock`, `AuditSink`. `ApplyTenantQueryFilters<TTenantId>(modelBuilder)` puts the named, fail-closed filter `TenantQueryFilterName` (`"Tenant"`) on every `ITenantEntity` root; tenancy rules in [../skills/multi-tenant.md](../skills/multi-tenant.md) |
| `TenantEntityTypeConfiguration<TEntity, TId, TTenantId>` | EF.Data (`EF.Data.Configurations`) | Tenant-first key `(TenantId, Id)`, `Id` never store-generated, `TenantId` required. Derive per tenant entity and call `base.Configure(builder)` first |
| `RepositoryBase<TDbContext, TAuditIdType, TTenantIdType>` | EF.Data | Generic repository with CRUD, paging, search. Members: Create, Delete, DeleteAsync, ExistsAsync, GetEntityAsync, GetEntityByKeysAsync, GetEntityProjectionAsync, GetStream, PrepareForUpdate, QueryPageAsync, QueryPageProjectionAsync, SaveChangesAsync, UpdateFull, UpsertAsync. **All members are generic over the entity** (`Create<T>(ref T)`, `GetEntityAsync<T>(...)`, ...), so one instance serves any entity. |
| `RepositoryTrxn<TEntity, TId, TDbContext>` / `RepositoryQuery<TEntity, TId, TDbContext>` | EF.Data | Typed-ID generic repositories over `RepositoryBase<TDbContext, string, Guid?>` for entities with no bespoke logic: `GetAsync` (filters on a parameterized `Id`, so tenant-first keys and the tenant filter work), plus `ListAsync` on the query side. Guid-keyed two-parameter forms also exist. See [repository-template.md](../templates/repository-template.md) -> Generic Repository Pair. |
| `IRepositoryBase` | EF.Data.Contracts | Non-generic repository interface over the generic-method CRUD/query surface |
| `IRepositoryTrxn<TEntity, TId>` / `IRepositoryQuery<TEntity, TId>` | EF.Data.Contracts | Typed-ID open-generic repository contracts (extend `IRepositoryBase`) for generic-coverable entities (join / append-only / simple CRUD). A bespoke `I{Entity}RepositoryQuery` extends `IRepositoryQuery<TEntity, TId>` to add `Search`. Drives `repositoryContractStyle: hybrid`/`generic-only`. |
| `AuditInterceptor<TAuditIdType, TTenantIdType>` | EF.Data (`EF.Data.Interceptors`) | EF SaveChanges interceptor. Ctor `(IInternalMessageBus msgBus, IEnumerable<IAuditLogRepository>? auditSinks = null)`; publishes audit entries through `IInternalMessageBus` after the save, then awaits every sink it was given (a sink failure propagates). Masks `[Mask]` and `IsSensitive()` properties; per-save state is per context, so one instance serves pooled contexts |
| `RegisterDomainIdConversions(params Assembly[])` / `RegisterUtcTemporalConversions()` / `RegisterVersionConcurrencyTokens()` | EF.Data | `ConfigureConventions`: typed-ID converters, and UTC for every `DateTimeOffset` / `DateTime` (`UtcDateTimeOffsetConverter`, `UtcDateTimeConverter` in `EF.Data.Converters`). End of `OnModelCreating`: `Version` as the concurrency token |
| `DbContextScopedFactory<TContext, TAuditIdType, TTenantIdType>` | EF.Data | Scoped lease over `IDbContextFactory<T>`. Ctor `(factory, requestContext, TimeProvider? clock, Func<IRequestContext<,>, bool>? allowAllTenants)`: stamps `AuditId`, `TenantId` and `Clock`; when `allowAllTenants` returns true it sets `AllTenants` and clears `TenantId` |
| `ConcurrencyGuard` (`Require`, `IsConcurrencyFailure`) | EF.Data.Contracts | Require-then-save: `Require(expectedVersion, entity.Version, entityType, id)` throws `PreconditionFailedException` on an `If-Match` mismatch |
| `OptimisticConcurrencyWinner` | EF.Data.Contracts | `SaveChangesAsync(winner, ct)` conflict strategy: `Throw`, `ClientWins`, `DBWins`; an unresolved conflict throws `PreconditionFailedException` |
| `ReadIsolation` | EF.Data.Contracts | `Default` or `ReadUncommitted` on the repository paging overloads; `READ UNCOMMITTED` runs on one held session (SQL Server only; other providers ignore it) |
| `RelationalProviderSettings` | EF.Data.Contracts | Retry, history table, migrations assembly, command timeout for `UsePostgreSqlProvider` / `UseSqlServerProvider` |
| `CursorCodec`, `CursorPosition`, `KeysetCursor` (`Scope`), `SortSpec`, `InvalidCursorException` | EF.Data.Contracts | Keyset paging: `KeysetPageAsync<T, TKey, TTie>` / `KeysetPageProjectionAsync`, `StreamKeysetPagesAsync` for whole walks in jobs (`after:` resumes one). Every decode failure throws `InvalidCursorException`, which the app maps to 400 |
| `AuditChangeAttribute`, `RelatedDeleteBehavior`, `IsSensitive()` | EF.Data.Contracts | Audit change tracking, related delete behavior, masking for shadow or converted columns |
| `DatabaseMigrationRunner` | EF.Data (`EF.Data.Migrations`) | Ordered, fail-fast migration runner hosted by `{App}.DatabaseMigrator`. `RunAsync()` executes registered targets in order; first failure exits nonzero and later targets do not run. |
| `AddDatabaseMigrationRunner()` / `AddEfCoreMigrationTarget<TContext>(name, order)` | EF.Data (`EF.Data.Migrations`) | DI registration for the runner and its EF Core targets. One target per migration-owning context (app Trxn, FlowEngine, third-party stores), deterministic `order`. See [data-persistence-advanced.md](data-persistence-advanced.md) -> Migration Ownership: Dedicated Migrator Host. |
| `AddDatabaseMigrationStep<TContext, TStep>()` / `AddSqlDatabaseMigrationStep<TContext>(...)` | EF.Data (`EF.Data.Migrations`) | Ordered non-EF steps around a target (`IDatabaseMigrationStep<TContext>`, `DatabaseMigrationStepPhase`) |
| `GetMissingTablesAsync()` | EF.Data (`EF.Data.Migrations`) | Mapped tables the database lacks; a runtime host that is not the migration owner checks schema presence with it |
| `ResilientTransaction` | EF.Data | `ResilientTransaction.New(db).ExecuteAsync(ct => work(ct), ct)` under the execution strategy; the work must be re-runnable |

### Relational Providers (EF.Data.PostgreSql, EF.Data.SqlServer)

`EF.Data` references no database provider. Reference `EF.Data.PostgreSql` for the PostgreSQL arm (the `NonAzure` default) and `EF.Data.SqlServer` for a SQL Server / Azure SQL arm; both surface duplicate keys as `UniqueConstraintException` (EntityFrameworkCore.Exceptions). Read-uncommitted interceptors and Always Encrypted migration DDL: [ef-packages-optional.md](ef-packages-optional.md) section SQL Server Extras.

| Type | Package | Used For |
|---|---|---|
| `UsePostgreSqlProvider(RelationalProviderSettings, PgBouncerMode, configure)` | EF.Data.PostgreSql | Npgsql with retry, history table, command timeout; Npgsql plugins (`UseVector()`) through `configure` |
| `PgBouncerMode`, `ApplyPgBouncerTransactionMode` | EF.Data.PostgreSql | Transaction-mode pooler flags (`No Reset On Close`, `Max Auto Prepare=0`); parse the setting with `StrictEnum` |
| `UseSqlServerProvider(RelationalProviderSettings, compatibilityLevel, SqlServerFlavor, configure, configureAzureSql)` | EF.Data.SqlServer | SQL Server provider; Azure SQL flavor picked by the data-source host suffix |

### Common Infrastructure (EF.Common, EF.Common.Contracts)

| Type | Package | Used For |
|---|---|---|
| `IRequestContext<out TAuditIdType, out TTenantIdType>` | EF.Common.Contracts | Scoped request context: `string CorrelationId`, `TAuditIdType AuditId`, `TTenantIdType? TenantId`, `List<string> Roles`, `bool RoleExists(string)` |
| `RequestContext<TAuditIdType, TTenantIdType>` | EF.Common.Contracts | Default implementation of IRequestContext. Constructor order: `(correlationId, auditId, tenantId, roles)` |
| `Result<T>` | EF.Common.Contracts | Application-layer result wrapper. Members: IsSuccess, IsFailure, IsNone, Value, ErrorMessage, Errors, Match / MatchAsync (failure branch receives `IReadOnlyList<DomainError>`; the 3-branch overload adds `onNone`), Map, Bind, BindOrContinue, OnSuccess, OnFailure, Tap. Static: `Success(T)`, `None()`, `Failure(string error)`, `Failure(string code, string error)`, `Failure(IReadOnlyList<DomainError>)`, `Failure(Exception)`. **Not JSON-deserializable** - lacks parameterless constructor; use `JsonDocument` parsing in tests. When passed to `Results.Ok(result)` in endpoints, serializes to just the `Value` payload (not the full Result wrapper). |
| `Result` | EF.Common.Contracts | Non-generic result. Static: `Success()`, `Failure(string error)`, `Failure(string code, string error)`, `Failure(IReadOnlyList<DomainError>)`, `Failure(Exception)`, `Combine(Result[])`. `Match` is 2-branch (success, failure `IReadOnlyList<DomainError>`). |
| `PagedResponse<T>` | EF.Common.Contracts | Paged response with Data, Total, PageSize, PageIndex |
| `SearchRequest<TFilter>` | EF.Common.Contracts | Paged search request with PageSize, PageIndex, Sorts, Filter |
| `IEntityBaseDto<TKey>` / `IEntityBaseDto` | EF.Common.Contracts | Base DTO contract. Generic `IEntityBaseDto<TKey>` (`TKey : struct`) exposes `TKey? Id` (null on Create, required on Update); non-generic `IEntityBaseDto : IEntityBaseDto<Guid>` is the Guid alias most DTOs bind to. App-level `EntityBaseDto` implements the alias - see [data-mapping-template.md](../templates/data-mapping-template.md). Non-Guid-key apps derive `EntityBaseDto<TKey>`. |
| `ITenantEntityDto` / `ITenantEntityDto<TTenantId>`, `EntityDtoRules` (`ValidateCreate`, `ValidateUpdate`) | EF.Common.Contracts | DTO tenant marker and the shared DTO structure rules (codes `dto.required`, `tenant.required`, `id.required`); per-entity validators add their own rules on top |
| `IETagVersioned` | EF.Common.Contracts | Response model exposing `ETagVersion`; `WithETag()` writes the strong ETag from it |
| `NotFoundException`, `ConflictException`, `PreconditionFailedException` (`EntityType`, `EntityId`, `Expected`, `Current`), `PreconditionRequiredException` | EF.Common.Contracts | App-facing exceptions the `ExceptionClassifier` maps by default (404, 409, 412, 428) |
| `UuidV7` (`IsV7`, `TimestampOf`, `ValidateCallerId`) | EF.Common.Contracts | Caller-supplied id validation (`id.not_uuidv7`) and timestamp extraction |
| `Sort` | EF.Common.Contracts | Sort descriptor (PropertyName, SortOrder) |
| `SortOrder` | EF.Common.Contracts | Enum: Ascending=0, Descending=1 |
| `IMessage` | EF.Common.Contracts | Marker interface for internal-bus messages |
| `ISpecification<T>` / `Specification<T>` | EF.Common.Contracts | Specification pattern base |
| `StaticItem<TId, TValue>` | EF.Common.Contracts | Lookup item for dropdowns: positional `record StaticItem<TId, TValue>(TId? Id, string? Name, TValue? Value = default)` |
| `StaticList<T>` | EF.Common.Contracts | Positional `record StaticList<T>(IReadOnlyList<T> Items)`; construct with `new StaticList<T>(items)` |
| `IDistributedLock`, `AcquireWithinAsync` | EF.Common.Contracts | `ValueTask<IAsyncDisposable?> TryAcquireAsync(key, ttl, ct)` and a bounded-wait acquire; implementations `InProcessDistributedLock` (EF.Common) and `RedisDistributedLock` (EF.Cache) |
| `CursorPage<T>` / `CursorSearchRequest<TFilter, TSortMode>` / `PageSizeLimits` | EF.Common.Contracts | Cursor paging contracts and page-size clamps |
| `AuditEntry<TAuditIdType, TTenantIdType>` (`StartedAtUtc`), `AuditStatus` | EF.Common.Contracts | Audit entry carrying audit identity, tenant identity and the start instant |
| `ExceptionClassifier`, `ExceptionCategory`, `ExceptionClassifierOptions`, `AddExceptionClassifier(o => o.Map<T>(category))` | EF.Common (`EF.Common.Exceptions`) | The one exception taxonomy behind HTTP (`AddEfProblemDetails`) and gRPC (`ServiceErrorInterceptor`). `ArgumentException`, `FormatException` and `InvalidOperationException` are unmapped (500) by default; mapping rules in [../templates/exception-handler-template.md](../templates/exception-handler-template.md) |
| `ValidationException` | EF.Common (`EF.Common.Exceptions`) | Validation failure; classified as 400 |
| `StrictEnum.Parse` / `ParseOrDefault`, `GetRequiredEnum` / `GetEnum` | EF.Common | Enum settings by defined name only; numeric or undefined values fail at startup |
| `StaticLogging`, `PredicateBuilder` | EF.Common | Pre-host logger factory, dynamic LINQ predicates |
| `IValidator<T>`, `ValidationResult`, `ValidationUtility` | EF.Common | Validation contract consumed by `ValidationFilter<T>` |
| `InProcessDistributedLock`, `DeterministicGuid`, `ResultExtensions.ToResult()` | EF.Common | Single-process `IDistributedLock`, deterministic GUIDs from stable input, `DomainResult` to `Result` conversion |

### Background Services (EF.BackgroundServices)

| Type | Package | Used For |
|---|---|---|
| `IInternalMessageBus` | EF.BackgroundServices | In-process message bus for domain event dispatch; `AutoRegisterHandlers(params Assembly[])` |
| `InternalMessageBus` | EF.BackgroundServices | Default implementation of IInternalMessageBus; ctor `(ILogger, IServiceProvider, IBackgroundTaskQueue, IOptions<InternalMessageBusSettings>)`; dispatches through `IBackgroundTaskQueue`, not inline |
| `IMessageHandler<T>` | EF.BackgroundServices | Handler interface for messages (where T : IMessage) |
| `InternalMessageBusProcessMode` | EF.BackgroundServices | Dispatch mode: `Queue = 1`, `Topic` |
| `CronBackgroundService<T>`, `ICronJobHandler<T>`, `CronJobSettings` (`TimeZoneId`, default `UTC`) | EF.BackgroundServices | Cron-scheduled background service |
| `IBackgroundTaskQueue` / `ChannelBackgroundTaskQueue` | EF.BackgroundServices (`EF.BackgroundServices.Work`) | Queue for background task processing; `AddChannelBackgroundTaskQueue()` registers it with its hosted service |
| `ScopedBackgroundService` | EF.BackgroundServices | Base class for scoped background services |
| `LeasedWorkerBase<TOptions>` / `LeasedWorkerOptions` / `RetryBackoff` | EF.BackgroundServices (`EF.BackgroundServices.Leased`) | Polling worker over leased work rows: `ProcessBatchAsync(CancellationToken)`, `MaxAttempts` 5, `RetryBaseDelay`, `RetryMaxDelay`, `SettlementTimeout`; `AddLeasedWorkerService<TWorker, TOptions>()` validates options at host start |
| `IScheduledJobHandler`, `ScheduledJobTelemetry` | EF.BackgroundServices (`EF.BackgroundServices.Scheduling`) | Scheduled job handler contract and `scheduler.job.*` metrics; the TickerQ runner is in [ef-packages-optional.md](ef-packages-optional.md) section Scheduling |

#### Critical Wiring Notes

- `AuditInterceptor` publishes `AuditEntry<...>` messages through `IInternalMessageBus` after `SaveChangesAsync` succeeds, then awaits each `IAuditLogRepository` sink it was constructed with (EF.Audit.*); a sink failure propagates to the caller.
- `InternalMessageBus.Publish(...)` is a synchronous fire-and-forget API over the channel queue. Do not invent `PublishAsync` or single-message overloads.
- `InternalMessageBus` depends on the channel-based `IBackgroundTaskQueue`; if the queue/hosted service is missing, `Publish(...)` succeeds but handlers never run.
- `AutoRegisterHandlers(assemblies)` runs after host build and throws at that call for a discovered handler that is not registered in DI. Every dispatch resolves the handler in a new DI scope, so each handler runs once per message and scoped dependencies never outlive it.

### Application Host (EF.Host, EF.AspNetCore)

| Type | Package | Used For |
|---|---|---|
| `AddEfAzureAppConfiguration(configure)` / `AzureAppConfigurationRefreshService` | EF.Host | Azure App Configuration with label layering, feature flags and background refresh (section `AppConfig`); no-op without an endpoint |
| `AzureCredentialFactory.Create` / `AddAzureTokenCredential`, `AzureCredentialSettings` | EF.Host | One `TokenCredential` honoring `ManagedIdentityClientId` / `AzureTenantId` |
| `ResolveConnection(name, alternateKeys)`, `ConnectionValue` | EF.Host | Connection string, then alternate keys; a real value wins over a storage-emulator value |
| `AddHostLifecycle()`, `HostLifecycleSettings` (section `Hosting`) | EF.Host | Readiness turns unhealthy before any hosted service stops, drain wait, shutdown budget |
| `IStartupTask`, `AddStartupTask<TTask>()`, `RunStartupTasksAsync()` | EF.Host | Post-build tasks in registration order, one DI scope per task, cancellation token passed |
| `AddProxyForwarding()` / `UseProxyForwarding()`, `ProxyForwardingSettings` (section `Proxy`) | EF.AspNetCore (`EF.AspNetCore.Proxy`) | Forwarded headers from trusted proxies and path base, validated at registration; first in the pipeline |
| `MapEfHealthEndpoints()`, `AddSelfCheck()`, `HealthEndpointOptions` | EF.AspNetCore (`EF.AspNetCore.HealthChecks`) | `/healthz`, `/healthz/live` (tag `live`), `/healthz/ready` (tag `ready`); anonymous and exempt from rate limiting |
| `AddMemoryHealthCheck()`, `HealthCheckHelper`, `HealthLoggingPublisher` | EF.AspNetCore (`EF.AspNetCore.HealthChecks`) | Memory check reporting the registration's failure status; tag-filtered options; health logging |
| `AddCorrelationId()` / `AddCorrelationIdPropagation()` / `UseCorrelationId()` | EF.AspNetCore (`EF.AspNetCore.Correlation`) | Validated inbound `X-Correlation-Id` becomes `TraceIdentifier`; outbound calls send it, and outside a request the handler sends nothing and never throws |
| `AddEfProblemDetails()`, `ExceptionHandlingOptions`, `ProblemDetailsExceptionHandler` | EF.AspNetCore (`EF.AspNetCore.ExceptionHandling`) | The host `IExceptionHandler`: status from `ExceptionClassifier`, caller cancellation 499 with no body, no 5xx detail outside Development, `requestId`/`traceId` on every problem |
| `ProblemDetailsHelper` | EF.AspNetCore | Endpoint problems: `Create(status, detail, title)` and `FromErrors(errors, status = 400)`, which emits `extensions.errors` as an ordered `{code, message}` array - pass the `Match` failure branch straight through |
| `IfMatch`, `RequireIfMatch()`, `WithETag()`, `IfMatchOptions`, `AddConcurrencyOpenApiContract()` | EF.AspNetCore (`EF.AspNetCore.Concurrency`) | Bind `IfMatch` and pass `ifMatch.ExpectedVersion`; the filter answers 428 missing, 400 malformed, 412 with `ETag` from `PreconditionFailedException.Current`; `WithETag()` writes the strong ETag from `IETagVersioned` and answers 304 |
| `AddCorsPolicyFromConfiguration(policyName, section)`, `CorsPolicySettings` | EF.AspNetCore (`EF.AspNetCore.Cors`) | Origins validated at registration (no empty list, trailing `/`, path, or `*` with credentials) |
| `AddHttpRequestContext<TTenantId>(parseTenant, configure)`, `HttpRequestContextOptions` | EF.AspNetCore (`EF.AspNetCore.RequestContext`) | Claims-based scoped `IRequestContext<string, TTenantId>`; no HTTP request gives the system context (`SystemAuditId`, every role in `SystemRoles`, default `system`), and every `SystemRoles` entry is stripped from a token |
| `SecurityHeadersMiddleware` / `UseBasicSecurityHeaders()` | EF.AspNetCore (`EF.AspNetCore.Security`) | Baseline security response headers |
| `ValidationFilter<T>` | EF.AspNetCore (`EF.AspNetCore.Filters`) | Endpoint filter over `EF.Common.IValidator<T>` (no FluentValidation) |
| `AddEfVersionedOpenApi()`, `MapVersionedApiGroup()`, `BuildApiVersionSet()` | EF.AspNetCore (`EF.AspNetCore.Versioning`) | Versioned OpenAPI documents and route groups |

### Caching (EF.Cache)

| Type | Package | Used For |
|---|---|---|
| `CacheSettings` | EF.Cache | Config model bound from the `CacheSettings[]` array |
| `ITypedCache` / `TypedCache` / `CacheKey` | EF.Cache | Typed FusionCache access with namespaced keys. `AddTypedCache(config, configure: ...)` registers every instance, the shared `IConnectionMultiplexer` per Redis-backed instance (keyed by `Name`, the default one also unkeyed; `AbortOnConnectFail` forced false) and the matching `IDistributedLock` |
| `RedisDistributedLock(IConnectionMultiplexer, keyPrefix)` | EF.Cache | Redis `IDistributedLock` over the shared connection |
| `RedisHealthCheck` / `AddRedisHealthCheck(name, tags)` | EF.Cache | Ping over the shared multiplexer, Degraded by default |
| `CacheProfileOptions`, `CacheDegradedEventArgs`, `CacheTelemetry`, `RedisConfiguration` | EF.Cache | Cache profiles, degraded-mode event, meter names, Redis connection settings |

Every other Redis consumer (rate limiting, Data Protection, a host's own client) resolves the shared `IConnectionMultiplexer` from DI instead of connecting itself.

## App-Level Types (NOT in EF.Packages)

These types appear in the service and endpoint templates but are **not provided by EF.Packages**. They must be created in the target project. `DefaultRequest<T>` / `DefaultResponse<T>` are generated at Phase 4 - the contract interfaces reference them; shape and member name (`Item`) are owned by [../ai/contract-scaffolding.md](../ai/contract-scaffolding.md). Generate the rest during Phase 5b.

| Type | Where to Create | Used For |
|---|---|---|
| `DefaultRequest<T>` | Application.Models | Request wrapper for Create/Update service methods |
| `DefaultResponse<T>` | Application.Models | Response wrapper for Get/Create/Update service methods |
| `ApplicationStyle` / `ApplicationStyleResolver` | Application.Contracts | Runtime `Service` / `Cqrs` selector for `applicationStyle: switch`; reads `Application:Style` plus `<APP>_APPLICATION_STYLE` |
| `AppConstants` | Application.Contracts | Role names (ROLE_GLOBAL_ADMIN, ROLE_SYSTEM), the system context user id (SYSTEM_USER_ID), cache names (DEFAULT_CACHE) |
| `{Entity}StructureValidator` | Application.Services (and `Application.Cqrs/Features/{Entity}`) | Per-entity DTO rules over `EntityDtoRules` - shape in [../templates/structure-validator-template.md](../templates/structure-validator-template.md) |

Services cache through EF.Cache `ITypedCache` directly ([../skills/caching.md](../skills/caching.md)); generate no app cache-provider abstraction.

---

## Phase Usage

- **5a:** EF.Common, EF.Domain, EF.Domain.Contracts, EF.Data, EF.Data.Contracts, EF.Common.Contracts; EF.Data.PostgreSql / EF.Data.SqlServer per provider arm; EF.Data.Encryption when columns are encrypted
- **5b:** EF.AspNetCore, EF.Host, EF.OpenTelemetry, EF.AspNetCore.DataProtection, EF.Cache, EF.Tenancy when multi-tenant, EF.CQRS when `applicationStyle` is `cqrs` or `switch`, EF.Auth (fixed principal, claims relay), EF.RateLimiting / EF.RateLimiting.Redis and EF.Gateway when enabled, EF.FilterBuilder, optional Key Vault
- **5c:** messaging (EF.Messaging.Contracts, EF.Data.Outbox, EF.Messaging, EF.Messaging.RabbitMq, EF.Messaging.Functions), scheduling (EF.BackgroundServices.TickerQ), storage (EF.Storage, EF.Storage.S3, EF.Table, EF.CosmosDb), durable audit (EF.Audit.*), and UI client (EF.UI.Client, EF.UI.Refit, EF.Http.Resilience) packages when enabled
- **4 (test infrastructure):** EF.Testing, EF.IntegrationTesting plus the provider packages (`Test.Support` WAF adapter and database fixture), EF.IntegrationTesting.Aspire for `Test.Aspire`
- **5d:** EF.Testing.Architecture for `Test.Architecture`; `LoadRunner` from EF.Testing for `Test.Load`
- **5e:** EF.Auth and optional EF.MSGraph; EF.AI and EF.AI.Testing (when AI in scope)

Extend `Directory.Packages.props` with the sub-phase's packages at the START of that sub-phase - the 5a base set alone does not build 5b concerns (`AddEfProblemDetails`, `ValidationFilter`, and `UseCorrelationId` need EF.AspNetCore, `CacheSettings` needs EF.Cache). EF.Data references EF.BackgroundServices and EF.Audit.Contracts, so `AuditInterceptor`'s `IInternalMessageBus` dependency resolves from the 5a set; the host still registers the bus and its background task queue before the interceptor runs.

---

## Rules

- **Never regenerate types that exist in EF.Packages.** Check this reference before creating base classes, result types, repository interfaces, host plumbing, or test helpers.
- All EF.Packages target the latest stable .NET TFM. Match the target app's TFM to the EF.Packages release in use.
- Packages use **central package management** - pin versions only in `Directory.Packages.props`.
- Private feed must be in `nuget.config` with `<packageSourceMapping>` entries for `EF.*` packages.
- Project files must not put `Version="..."` on `EF.*` `<PackageReference>` entries.
- Local definitions of package types (base classes, result and paging types, request context, bus, entity configuration base, UTC converters, tenant validator, `IStartupTask`, exception handler, ETag filters, inbox/outbox stores, consumer base, fixed-principal handler, rate limiter, load runner, container fixtures, AI fakes) are replaced by the package types above or in [ef-packages-optional.md](ef-packages-optional.md).
