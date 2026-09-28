# Shared Base-Type Reference (canonical example: `EF.*`)

The scaffolded project depends on a set of shared base-type contracts (entity bases, repository bases, request context, results, paged response, specifications, messaging interfaces, etc.). The tables below describe those contracts and apply equally to every `packageStrategy`.

How those contracts are delivered depends on `packageStrategy` in `.scaffold/resource-implementation.yaml`:

| `packageStrategy` | Delivery |
|---|---|
| `feed` | All layers consumed as NuGet packages `<packagePrefix>.<Layer>` from `customNugetFeeds`. |
| `local` | All layers generated as packable projects under `src/Packages/<packagePrefix>.<Layer>` and consumed via `<ProjectReference>`. |
| `hybrid` | Feed-supplied layers consumed as NuGet packages; layers listed in `localPackageLayers` generated under `src/Packages/<packagePrefix>.<Layer>` and consumed via `<ProjectReference>`. Same prefix in both cases. |

Throughout this file, `EF` is the **canonical example prefix** (used by the reference app TaskFlow and the [efreeman518/EF.Packages](https://github.com/efreeman518/EF.Packages) repo). Substitute your `packagePrefix` everywhere you see `EF.<Layer>` below. The type signatures themselves are identical regardless of prefix.

Do not regenerate these types into your application/domain/host layers - they live in `<packagePrefix>.*` only, whether package or project.

> **Pre-flight:** When `packageStrategy: feed` or `hybrid`, configure the private feed in `nuget.config` before Phase 4; local environments need package read access exposed through `NUGET_AUTH_TOKEN` or an equivalent credential provider. When `packageStrategy: local`, no feed configuration is needed for these layers (only `nuget.org` is required). Verify with `configure-ef-packages-feed.py --check-only` (exit 0) in Phase 3 and `dotnet restore` once the Phase 4 solution exists. See [execution-gates.md](execution-gates.md).

---

## Key Types by Layer

These types are consumed throughout scaffolded code. Know where they come from so you don't recreate them.

Capability-gated packages (auth, messaging, storage, Key Vault, gRPC, AI, Graph, durable audit, utilities, and the Enterprise FlowEngine / FilterBuilder) live in [ef-packages-optional.md](ef-packages-optional.md); load it when the capability is in scope.

> **Verified against the EF.Packages source.** If a type is not listed here, it either does not exist in EF.Packages or has not been verified. Check the actual assemblies (or the source repo linked above) before assuming a type exists. Generated code never uses a member the package marks `[Obsolete]`: with warnings as errors it breaks the build.

### Domain Layer (EF.Domain, EF.Domain.Contracts)

| Type | Package | Used For |
|---|---|---|
| `EntityBase<TId>` (`where TId : struct, IDomainId<TId>`) / `EntityBase` (Guid) | EF.Domain | Base class for all domain entities: UUIDv7 `Id` and the `long Version` concurrency token, incremented by `DbContextBase.SaveChangesAsync`. `RowVersion` is `[Obsolete]`; use `Version`. No audit fields. |
| `AuditableBase<TAuditIdType>` | EF.Domain | Guid-keyed `EntityBase` plus `IAuditable<TAuditIdType>` fields |
| `CollectionUtility` | EF.Domain | Utility for collection operations |
| `DomainException` | EF.Domain (`EF.Domain.Exceptions`) | Domain exception base |
| `MaskAttribute` | EF.Domain (`EF.Domain.Attributes`) | Audit redaction of modified entries; sensitive properties also carry the EF.Common one ([data-persistence-advanced.md](data-persistence-advanced.md) section Testing expectations) |
| `IDomainId<TSelf>` (`where TSelf : struct, IDomainId<TSelf>`) | EF.Domain.Contracts | Typed ID contract |
| `IEntityBase<TKey>` | EF.Domain.Contracts | Entity base interface |
| `IVersionedEntity` | EF.Domain.Contracts | `long Version` concurrency contract |
| `ITenantEntity<TTenantIdType>` (`where TTenantIdType : struct`) | EF.Domain.Contracts | Tenant-scoped entity marker (`TenantId { get; init; }`); enables global query filters |
| `IAuditable<TAuditIdType>` | EF.Domain.Contracts | Audit trail interface: `CreatedDate`, `CreatedBy`, `UpdatedDate`, `UpdatedBy` |
| `DomainGuard` | EF.Domain.Contracts | Argument guard helpers for domain code |
| `DomainResult<T>` | EF.Domain.Contracts | Railway-style result for domain operations. Properties: `Value`, `IsSuccess`, `IsFailure`, `IsNone`, `ErrorMessage` (aggregated string), `Errors` (`IReadOnlyList<DomainError>`). Static: `Success(T)`, `Failure(string error)`, `Failure(string code, string error)`, `Failure(IReadOnlyList<DomainError>)`, `Failure(Exception)`, `None()`. Instance: `Match` - the failure branch receives `IReadOnlyList<DomainError>`; the generic form adds a 3-branch overload with `onNone`. |
| `DomainResult` | EF.Domain.Contracts | Non-generic domain result. Same shape as `DomainResult<T>` minus `Value`/`IsNone`. |
| `DomainError` | EF.Domain.Contracts | Typed error. Properties: `Error` (the human message), `Code` (machine key), `Message` (alias for `Error`). Static factories: `Create(string error)` (no code key) and `Create(string error, string code)`. **Argument order trap (GR-14):** `Create` takes the human message FIRST, code second - the reverse of `DomainResult.Failure(string code, string error)`. Do not infer order from the names; verify against this row or a compiled call site. Never access `.Message` from `Exception` - use `.Error` or `.Message` (same). **Propagation pattern:** `if (r.IsFailure) return Result<T>.Failure(r.ErrorMessage!);` or `Result<T>.Failure(r.Errors)`. |

### Data Access Layer (EF.Data, EF.Data.Contracts)

| Type | Package | Used For |
|---|---|---|
| `DbContextBase<TAuditIdType, TTenantIdType>` | EF.Data | Base DbContext: `BuildTenantFilter`, `IAuditable` field population and the `Version` increment in `SaveChangesAsync`, optional `AuditSink` |
| `RepositoryBase<TDbContext, TAuditIdType, TTenantIdType>` | EF.Data | Generic repository with CRUD, paging, search. Members: Create, Delete, DeleteAsync, ExistsAsync, GetEntityAsync, GetEntityByKeysAsync, GetEntityProjectionAsync, PrepareForUpdate, QueryPageAsync, QueryPageProjectionAsync, SaveChangesAsync, UpdateFull, UpsertAsync. **All members are generic over the entity** (`Create<T>(ref T)`, `GetEntityAsync<T>(...)`, ...), so one instance serves any entity. |
| `RepositoryTrxn<TEntity, TId, TDbContext>` / `RepositoryQuery<TEntity, TId, TDbContext>` | EF.Data | Typed-ID generic per-entity repository impls over `RepositoryBase<TDbContext, string, Guid?>` (`where TEntity : class, IEntityBase<TId>`) for entities with no bespoke logic: `RepositoryTrxn` adds `GetAsync`, `RepositoryQuery` adds `GetAsync` and `ListAsync`, both over the inherited generic CRUD. Guid-keyed `RepositoryTrxn<TEntity, TDbContext>` / `RepositoryQuery<TEntity, TDbContext>` also exist. Register open-generic via a closed-over-context subclass. See [repository-template.md](../templates/repository-template.md) -> Generic Repository Pair. |
| `IRepositoryBase` | EF.Data.Contracts | Base repository interface (non-generic). Exposes the generic-method CRUD/query surface (`Create<T>`, `Delete<T>`, `GetEntityAsync<T>`, `QueryPageProjectionAsync<T,TProject>`, `SaveChangesAsync`, ...). |
| `IRepositoryTrxn<TEntity, TId>` / `IRepositoryQuery<TEntity, TId>` | EF.Data.Contracts | Typed-ID open-generic repository contracts (extend `IRepositoryBase`) for generic-coverable entities (join / append-only / simple CRUD). A bespoke `I{Entity}RepositoryQuery` extends `IRepositoryQuery<TEntity, TId>` to add `Search`. Drives `repositoryContractStyle: hybrid`/`generic-only`. |
| `AuditInterceptor<TAuditIdType, TTenantIdType>` | EF.Data (`EF.Data.Interceptors`) | EF SaveChanges interceptor. Ctor `(IInternalMessageBus msgBus, IEnumerable<IAuditLogRepository>? auditSinks = null)`; on `SavedChangesAsync` it publishes collected audit entries through `IInternalMessageBus`, then awaits every registered `IAuditLogRepository` sink (a sink failure propagates) |
| `RegisterDomainIdConversions(params Assembly[])` / `RegisterVersionConcurrencyTokens()` | EF.Data | `ModelConfigurationBuilder` typed-ID converters; `ModelBuilder` convention making `Version` the concurrency token (call at the end of `OnModelCreating`) |
| `EFExtensions` | EF.Data | `DbContext` helpers such as `db.Delete` and `GetByKeyAsync` |
| `DbContextScopedFactory<TContext, TAuditIdType, TTenantIdType>` | EF.Data | Scoped wrapper around `IDbContextFactory<T>` for DI resolution |
| `OptimisticConcurrencyWinner` | EF.Data.Contracts | SaveChangesAsync conflict strategy: `ClientWins`, `DBWins`, `Throw` |
| `ReadIsolation` | EF.Data.Contracts | `Default` or `ReadUncommitted`; the repository paging overloads take it (the `bool readNoLock` overloads are `[Obsolete]`) |
| `SplitQueryThresholdOptions`, `BatchedExecute` | EF.Data.Contracts | Split-query threshold and batched execution helpers |
| `CursorCodec`, `CursorPosition`, `KeysetCursor`, `SortSpec` | EF.Data.Contracts | Keyset paging; `IQueryableExtensions.KeysetPageAsync` / `KeysetPageProjectionAsync` |
| `IQueryableExtensions` | EF.Data.Contracts | Extension methods for IQueryable (`ComposeIQueryable`, paging, keyset paging) |
| `AuditChangeAttribute` | EF.Data.Contracts | Attribute for audit change tracking |
| `RelatedDeleteBehavior` | EF.Data.Contracts | Enum for related entity delete behavior |
| `DatabaseMigrationRunner` | EF.Data (`EF.Data.Migrations`) | Ordered, fail-fast migration runner hosted by `{App}.DatabaseMigrator`. `RunAsync()` executes registered targets in order; first failure exits nonzero and later targets do not run. |
| `AddDatabaseMigrationRunner()` / `AddEfCoreMigrationTarget<TContext>(name, order)` | EF.Data (`EF.Data.Migrations`) | DI registration for the runner and its EF Core targets. One target per migration-owning context (app Trxn, FlowEngine, third-party stores), deterministic `order`. See [data-persistence-advanced.md](data-persistence-advanced.md) -> Migration Ownership: Dedicated Migrator Host. |
| `AddDatabaseMigrationStep<TContext, TStep>()` / `AddSqlDatabaseMigrationStep<TContext>(...)` | EF.Data (`EF.Data.Migrations`) | Ordered non-EF steps around a target (`IDatabaseMigrationStep<TContext>`, `DatabaseMigrationStepPhase`) |
| `ResilientTransaction` | EF.Data | Resilient transaction wrapper |

### SQL Server (EF.Data.SqlServer)

Add when a SQL Server provider arm exists. The EF.Data copies of these types are `[Obsolete]`; reference this package.

| Type | Package | Used For |
|---|---|---|
| `ConnectionNoLockInterceptor` / `ReadUncommittedInterceptor` | EF.Data.SqlServer (`EF.Data.SqlServer.Interceptors`) | `READ UNCOMMITTED` isolation for query contexts |
| `DatabaseFacadeExtensions` | EF.Data.SqlServer | `SetNoLockAsync()` / `SetLockAsync()` on `DatabaseFacade` |
| `MigrationSupport` | EF.Data.SqlServer | Raw-SQL helper for SQL Always Encrypted inside a migration (EF has no fluent mapping). Ctor `(MigrationBuilder, DefaultAzureCredential)`; `CreateColumnMasterKey(cmkUrl, cmkName)`, `CreateColumnEncryptionKey(cmkUrl, cmkName, cekName)`, `AlterColumnEncryption(cekName, "[schema].[Table]", "[Col] varbinary(200)", collate, encType)` where `encType` defaults to `DETERMINISTIC` (queryable); `RANDOMIZED` is the alternative. See [data-persistence-advanced.md](data-persistence-advanced.md) -> Always Encrypted. |

### Column Encryption (EF.Data.Encryption)

Provider-neutral application-layer column encryption.

| Type | Package | Used For |
|---|---|---|
| `IColumnEncryptor` / `AesGcmColumnEncryptor` / `PlaintextColumnEncryptor` | EF.Data.Encryption | Encrypt and decrypt column values |
| `BlindIndex` / `BlindIndexInterceptor` | EF.Data.Encryption | Deterministic lookup index over an encrypted value |
| `ColumnEncryptionOptions`, `ColumnEncryptionKeys`, `KeyVaultDekProvider` | EF.Data.Encryption | Key material and Key Vault DEK unwrap |
| `UseColumnEncryption()`, `AddColumnEncryption()`, `GetColumnEncryptor()` | EF.Data.Encryption | Options-builder, DI, and `DbContext` wiring |

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
| `Sort` | EF.Common.Contracts | Sort descriptor (PropertyName, SortOrder) |
| `SortOrder` | EF.Common.Contracts | Enum: Ascending=0, Descending=1 |
| `IMessage` | EF.Common.Contracts | Marker interface for domain events/messages |
| `ISpecification<T>` / `Specification<T>` | EF.Common.Contracts | Specification pattern base |
| `StaticItem<TId, TValue>` | EF.Common.Contracts | Lookup item for dropdowns: positional `record StaticItem<TId, TValue>(TId? Id, string? Name, TValue? Value = default)` |
| `StaticList<T>` | EF.Common.Contracts | Positional `record StaticList<T>(IReadOnlyList<T> Items)`; construct with `new StaticList<T>(items)` |
| `IDistributedLock` | EF.Common.Contracts | `ValueTask<IAsyncDisposable?> TryAcquireAsync(key, ttl, ct)`; implementations `InProcessDistributedLock` (EF.Common) and `RedisDistributedLock` (EF.Cache) |
| `CursorPage<T>` / `CursorSearchRequest<TFilter, TSortMode>` / `PageSizeLimits` | EF.Common.Contracts | Cursor paging contracts and page-size clamps |
| `StaticData` | EF.Common.Contracts | Static data container |
| `AuditEntry<TAuditIdType, TTenantIdType>` | EF.Common.Contracts | Audit entry record carrying both audit identity and tenant identity |
| `AuditStatus` | EF.Common.Contracts | Audit status enum |
| `StaticLogging` | EF.Common | Pre-host logger factory for startup/shutdown logging |
| `PredicateBuilder` | EF.Common | Dynamic LINQ predicate builder |
| `NotFoundException`, `ConflictException`, `ValidationException`, `PreconditionFailedException`, `PreconditionRequiredException` | EF.Common (`EF.Common.Exceptions`) | App-facing exception types an exception handler may map to 4xx |
| `MaskAttribute` | EF.Common (`EF.Common.Attributes`) | Redaction honored by `SerializeToJson` (`EF.Common.Extensions`), including audit entries for added entities |
| `IValidator<T>`, `ValidationResult`, `ValidationUtility` | EF.Common | Validation contract consumed by `ValidationFilter<T>` |
| `InProcessDistributedLock`, `DeterministicGuid`, `ResultExtensions.ToResult()` | EF.Common | Single-process `IDistributedLock`, deterministic GUIDs from stable input, `DomainResult` to `Result` conversion |

### CQRS (EF.CQRS)

Add when `applicationStyle` is `cqrs` or `switch`. In local mode, generate this as `src/Packages/<packagePrefix>.CQRS` and consume it through `<ProjectReference>`.

| Type | Package | Used For |
|---|---|---|
| `ICommand<TResponse>` | EF.CQRS (`EF.CQRS.Abstractions`) | Write request marker |
| `IQuery<TResponse>` | EF.CQRS (`EF.CQRS.Abstractions`) | Read request marker |
| `IRequestHandler<in TRequest,TResponse>` | EF.CQRS (`EF.CQRS.Abstractions`) | Single request handler contract |
| `IRequestValidator<TRequest>` | EF.CQRS | Optional request validator contract |
| `RequestValidationResult` | EF.CQRS | Validator result with one or more errors |
| `IValidationFailureResponseFactory<out TResponse>` | EF.CQRS | `CreateFailure(IReadOnlyCollection<DomainError>)` converts validation errors to the app response shape |
| `StaticFailureValidationResponseFactory<TResponse>` | EF.CQRS | Reflection-based factory for common static `Failure(...)` result shapes |
| `ValidationRequestHandlerDecorator<TRequest,TResponse>` / `LoggingRequestHandlerDecorator<TRequest,TResponse>` | EF.CQRS | Validation and logging decorators around handlers |
| `AddDecoratedRequestHandler<TRequest,TResponse,THandler>(ServiceLifetime lifetime = Scoped, Action<DecoratedRequestHandlerOptions>? configure = null)` | EF.CQRS | Registers the concrete handler and the interface wrapped in validation and logging decorators (`DecoratedRequestHandlerOptions.EnableValidation` / `EnableLogging`, both default true). Also `AddDecoratedRequestHandlers`, `AddRequestHandler`, `AddRequestValidator` |

**Dispatch rule:** EF.CQRS has no MediatR dependency, dispatcher, request bus, or generic `Send` method. Minimal API endpoints inject the exact `IRequestHandler<TRequest,TResponse>` they call. Scaffold request records, handlers, validators, and per-feature registration fragments under `Application.Cqrs/Features/{Entity}`.

### Background Services (EF.BackgroundServices)

| Type | Package | Used For |
|---|---|---|
| `IInternalMessageBus` | EF.BackgroundServices | In-process message bus for domain event dispatch |
| `InternalMessageBus` | EF.BackgroundServices | Default implementation of IInternalMessageBus; ctor `(ILogger, IServiceProvider, IBackgroundTaskQueue, IOptions<InternalMessageBusSettings>)`; dispatches through `IBackgroundTaskQueue`, not inline |
| `IMessageHandler<T>` | EF.BackgroundServices | Handler interface for messages (where T : IMessage) |
| `ScopedMessageHandlerAttribute` | EF.BackgroundServices | Attribute for scoped message handler discovery |
| `InternalMessageBusProcessMode` | EF.BackgroundServices | Dispatch mode: `Queue = 1`, `Topic` |
| `CronBackgroundService<T>` | EF.BackgroundServices | Cron-scheduled background service |
| `ICronJobHandler<T>` | EF.BackgroundServices | Handler interface for cron jobs |
| `IBackgroundTaskQueue` / `ChannelBackgroundTaskQueue` | EF.BackgroundServices (`EF.BackgroundServices.Work`) | Queue for background task processing; `AddChannelBackgroundTaskQueue()` registers it with its hosted service |
| `ScopedBackgroundService` | EF.BackgroundServices | Base class for scoped background services |
| `LeasedWorkerBase<TOptions>` / `LeasedWorkerOptions` | EF.BackgroundServices (`EF.BackgroundServices.Leased`) | Polling worker over leased work rows; `AddLeasedWorkerService<TWorker, TOptions>()` |

#### Critical Wiring Notes

- `AuditInterceptor` publishes `AuditEntry<...>` messages through `IInternalMessageBus` after `SaveChangesAsync` succeeds, then awaits each registered `IAuditLogRepository` sink (EF.Audit.*); a sink failure propagates to the caller.
- `InternalMessageBus.Publish(...)` is a synchronous fire-and-forget API over the channel queue. Do not invent `PublishAsync` or single-message overloads.
- `InternalMessageBus` depends on the channel-based `IBackgroundTaskQueue`; if the queue/hosted service is missing, `Publish(...)` succeeds but handlers never run.
- `[ScopedMessageHandler]` controls handler scope during dispatch only. Handlers still must be registered in DI and then wired into the bus after host build.

### Application Host (EF.Host, EF.AspNetCore)

| Type | Package | Used For |
|---|---|---|
| `IConfigurationBuilderExtensions` / `IHostApplicationBuilderExtensions` | EF.Host | `AddAzureAppConfiguration(...)` on the configuration and host builders; nothing else ships in EF.Host |
| `CorrelationIdStartupFilter` | EF.AspNetCore (`EF.AspNetCore.Filters`) | Startup filter that propagates/generates correlation IDs |
| `CorrelationIdMiddleware` / `UseCorrelationId()` / `AddCorrelationHeaderPropagation()` | EF.AspNetCore (`EF.AspNetCore.Correlation`) | Correlation middleware and header propagation registration |
| `ETagEndpointFilter<TResult>` / `IfMatchEndpointFilter<TArg>` | EF.AspNetCore (`EF.AspNetCore.Filters`) | Response ETag and `If-Match` precondition endpoint filters |
| `SecurityHeadersMiddleware` / `UseBasicSecurityHeaders()` | EF.AspNetCore (`EF.AspNetCore.Security`) | Baseline security response headers |
| `ValidationFilter<T>` | EF.AspNetCore | Endpoint filter over `EF.Common.IValidator<T>` (no FluentValidation) |
| `ProblemDetailsHelper` | EF.AspNetCore | ProblemDetails response builders. `BuildProblemDetailsResponseMultiple(title, IReadOnlyList<DomainError> errors, ...)` - pass the `Match` failure branch straight through (named arg `errors:`); emits `Extensions["errors"]` as an ordered `{code, message}` array and joins messages into `Detail`. Singular variant: `BuildProblemDetailsResponse(title, message, ...)`. |
| `HealthCheckHelper` | EF.AspNetCore | `BuildHealthCheckOptions(string tag)` for tag-filtered health endpoints |
| `MemoryHealthCheck` / `AddMemoryHealthCheck()` | EF.AspNetCore | Memory usage health check and its registration |
| `HealthLoggingPublisher` | EF.AspNetCore | IHealthCheckPublisher that logs health status |
| `ChaosManager` / `IChaosManager` | EF.AspNetCore | Chaos engineering fault injection |
| `FilterActivityProcessor` / `AddOpenTelemetryWithConfig()` | EF.AspNetCore | OpenTelemetry Activity processor with filter support and config-driven registration |
| `AddEfVersionedOpenApi()`, `MapVersionedApiGroup()`, `BuildApiVersionSet()` | EF.AspNetCore (`EF.AspNetCore.Versioning`) | Versioned OpenAPI documents and route groups |

> **Note:** `DefaultExceptionHandler` is **not** in EF.AspNetCore. Scaffold it per-project as a concrete `IExceptionHandler` implementation. See reference app `TaskFlow.Api/Middleware/GlobalExceptionHandler.cs`.

### Caching (EF.Cache)

| Type | Package | Used For |
|---|---|---|
| `CacheSettings` | EF.Cache | Config model bound from `CacheSettings[]` in appsettings |
| `ITypedCache` / `TypedCache` / `CacheKey` | EF.Cache | Typed FusionCache access with namespaced keys; `AddTypedCache(config, "CacheSettings")` |
| `RedisDistributedLock` / `AddDistributedLock(...)` | EF.Cache | Redis `IDistributedLock` implementation |
| `CacheProfileOptions`, `CacheDegradedEventArgs`, `RedisConfiguration` | EF.Cache | Cache profiles, degraded-mode event, Redis connection settings |

### Testing (EF.IntegrationTesting)

One package, five namespaces:

| Type | Namespace | Used For |
|---|---|---|
| `EF.IntegrationTesting.AspNetCore.EfWebApplicationFactoryBase<TProgram, TTrxnContext, TQueryContext>` | `EF.IntegrationTesting.AspNetCore` | Host-replacement WebApplicationFactory base; apps derive a thin adapter in `Test.Support` - behavior and shape in [../templates/test-templates-endpoint.md](../templates/test-templates-endpoint.md) |
| `PostgreSqlContainerFixture`, `MsSqlContainerFixture` | `EF.IntegrationTesting.Testcontainers` | Database container lifecycle behind `TestDatabaseContainer` (`Test.Integration` fixtures, `Test.E2E` `DbApiFactory`) |
| `AspireTestingHelpers` (`WaitForResourceHealthyAsync`, `GetRequiredConnectionStringAsync`) | `EF.IntegrationTesting.Aspire` | `Test.Aspire` mesh fixtures; the app-level `AspireTestHost` wraps them - see [../templates/test-templates-aspire.md](../templates/test-templates-aspire.md) |
| `DbContextOptionsFactory` (`BuildSqlServerOptions`, `BuildNpgsqlOptions`, `BuildInMemoryOptions`), `EfTestDbContextFactory<T>` | `EF.IntegrationTesting.EntityFramework` / `EF.IntegrationTesting.AspNetCore` | Test context options and factories |
| `EnvironmentVariableScope`, `FunctionsCoreToolsDiscovery` | `EF.IntegrationTesting.Environment` | Environment scoping + Functions Core Tools discovery for mesh tests |

`Test.Unit` needs no EF test package - plain MSTest plus `Test.Support` builders.

---

## App-Level Types (NOT in EF.Packages)

These types appear in the service and endpoint templates but are **not provided by EF.Packages**. They must be created in the target project. `DefaultRequest<T>` / `DefaultResponse<T>` are generated at Phase 4 - the contract interfaces reference them; shape and member name (`Item`) are owned by [../ai/contract-scaffolding.md](../ai/contract-scaffolding.md). Generate the rest during Phase 5b.

| Type | Where to Create | Used For |
|---|---|---|
| `DefaultRequest<T>` | Application.Models | Request wrapper for Create/Update service methods |
| `DefaultResponse<T>` | Application.Models | Response wrapper for Get/Create/Update service methods |
| `ApplicationStyle` / `ApplicationStyleResolver` | Application.Contracts | Runtime `Service` / `Cqrs` selector for `applicationStyle: switch`; reads `Application:Style` plus `<APP>_APPLICATION_STYLE` |
| `AppConstants` | Application.Contracts | Role names (ROLE_GLOBAL_ADMIN, ROLE_SYSTEM), the system context user id (SYSTEM_USER_ID), cache names (DEFAULT_CACHE) |
| `ITenantBoundaryValidator` | Application.Contracts | Tenant boundary enforcement interface |
| `TenantBoundaryValidator` | Application.Services | Default implementation - GlobalAdmin bypass + tenant matching |
| `IEntityCacheProvider` | Application.Contracts | Abstraction for entity-level caching |
| `NoOpEntityCacheProvider` | Application.Services | No-op stub used until Phase 5c wires FusionCache |
| `IStartupTask` / `RunStartupTasks()` | Bootstrapper | Post-build startup tasks (warmup, dev seeding) - shape in [../skills/bootstrapper.md](../skills/bootstrapper.md) |

`IEntityCacheProvider` / `NoOpEntityCacheProvider` are optional: generate them only when a service consumes entity-level caching. Host-only FusionCache wiring (L1+L2+backplane at the host) needs neither, and the Phase 4 `I{Entity}Service` contract carries no cache dependency.

> **Do not search EF.Packages for these types.** They are intentionally app-level to keep the shared library thin. The service template references them because every scaffolded project needs them.

---

## Phase Usage

- **5a:** EF.Common, EF.Domain, EF.Domain.Contracts, EF.Data, EF.Data.Contracts, EF.Common.Contracts; EF.Data.SqlServer for a SQL Server arm; EF.Data.Encryption when columns are encrypted
- **5b:** EF.AspNetCore, EF.Host, EF.FilterBuilder, EF.Cache, EF.CQRS when `applicationStyle` is `cqrs` or `switch`, optional auth/key vault packages
- **5c:** messaging (EF.Messaging, EF.Messaging.RabbitMq), storage (EF.Storage, EF.Storage.S3, EF.Table, EF.CosmosDb), and durable audit (EF.Audit.*) packages when enabled
- **4 (test infrastructure):** EF.IntegrationTesting (`Test.Support` WAF adapter + Testcontainers/Aspire fixture shells reference it)
- **5d:** the test tiers exercise EF.IntegrationTesting (already pinned since Phase 4)
- **5e:** EF.Auth and optional EF.MSGraph; EF.AI (when AI in scope)

Extend `Directory.Packages.props` with the sub-phase's packages at the START of that sub-phase - the 5a base set alone does not build 5b concerns (ProblemDetailsHelper/ValidationFilter/CorrelationIdStartupFilter need EF.AspNetCore, CacheSettings needs EF.Cache). EF.Data references EF.BackgroundServices and EF.Audit.Contracts, so `AuditInterceptor`'s `IInternalMessageBus` dependency resolves from the 5a set; the host still registers the bus and its background task queue before the interceptor runs.

---

## Rules

- **Never regenerate types that exist in EF.Packages.** Check this reference before creating base classes, result types, or repository interfaces.
- All EF.Packages target the latest stable .NET TFM. Match the target app's TFM to the EF.Packages release in use.
- Packages use **central package management** - pin versions only in `Directory.Packages.props`.
- Private feed must be in `nuget.config` with `<packageSourceMapping>` entries for `EF.*` packages.
- Project files must not put `Version="..."` on `EF.*` `<PackageReference>` entries.
- If source contains local definitions for `EntityBase`, `RepositoryBase`, `DbContextBase`, `Result`, `PagedResponse`, `SearchRequest`, `IRequestContext`, `IInternalMessageBus`, or `IMessageHandler`, stop and replace them with package references.
