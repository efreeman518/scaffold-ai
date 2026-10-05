# Optional Shared Packages (capability-gated `EF.*`)

Companion to [ef-packages-reference.md](ef-packages-reference.md), which owns delivery (`packageStrategy`), the always-needed layers, app-level types, phase usage, and rules. Load this file only when the matching capability is in scope. `EF` is the canonical example prefix; substitute your `packagePrefix`.

## Capability Packages

### Authentication (EF.Auth)

Add for outbound service tokens, the trusted-gateway claims relay, role/scope authorization, or the scaffold fixed principal. Auth-mode policy: [../skills/identity-management.md](../skills/identity-management.md).

| Type | Package | Used For |
|---|---|---|
| `AccessTokenCache`, `AccessTokenCacheOptions` (`RefreshWindow`), `AddAccessTokenCache(credential)` | EF.Auth (`EF.Auth.Tokens`) | Single-flight token cache over one `TokenCredential` (the registered one, else one `DefaultAzureCredential`); failures are not cached, tokens never logged |
| `BearerTokenHandler`, `AddBearerToken(scopes)` | EF.Auth (`EF.Auth.Tokens`) | `Authorization: Bearer` on every outbound request of an `HttpClient` |
| `OAuth2ClientCredentialsCredential`, `AddOAuth2ClientCredentials(section)` | EF.Auth (`EF.Auth.Tokens`) | Client-credentials grant for non-Entra providers, behind the same cache |
| `ForwardedClaimsOptions` (section `ForwardedClaims`), `ForwardedClaimsCodec`, `AddForwardedClaimsTransformation(config)` | EF.Auth (`EF.Auth.Relay`) | API side of the gateway user-claims relay: honored only for an app-only token from a `TrustedCallerIds` caller with no delegated-scope claim; empty `TrustedCallerIds` disables it. `RequireHeaderFromTrustedCaller` (default true) fails a trusted caller closed without a valid header; `SigningKey` adds HMAC signing |
| `RolesOrScopesAuthorizationHandler`, `RolesOrScopesRequirement` | EF.Auth (`EF.Auth.Handlers`) | Policy met by any listed role or scope; splits space-separated `scp` |
| `AddFixedPrincipal(scheme, o => ...)`, `FixedPrincipalOptions` (`Claims`, `AllowedEnvironments`), `FixedClaim` | EF.Auth (`EF.Auth.Fixed`) | Every request authenticates as the configured claims; the host fails to start outside `AllowedEnvironments` (default `Development`, `Testing`) or with no claims |

### Gateway (EF.Gateway)

YARP helpers for the edge gateway. Trust-boundary policy: [../skills/gateway.md](../skills/gateway.md).

| Type | Package | Used For |
|---|---|---|
| `AddDownstreamAuthTransforms(config)`, `DownstreamAuthOptions` | EF.Gateway | Per-cluster `Metadata`: `TokenScope` sets a bearer token from `AccessTokenCache`; `RelayUserClaims` writes the relay header. Every route strips the inbound relay header |
| `DownstreamHealthCheck`, `AddDownstreamHealthCheck(name, o => ...)` | EF.Gateway | GET probe of a downstream health URL; a missing or relative `Url` fails startup |

### Rate Limiting (EF.RateLimiting, EF.RateLimiting.Redis)

Pipeline placement and budget policy: [../skills/security.md](../skills/security.md) section Rate Limiting.

| Type | Package | Used For |
|---|---|---|
| `AddTenantRateLimiting(config)`, `TenantRateLimitSettings` (section `RateLimiting:Tenants`), `RequireTenantBudget(name)`, `TenantBudgetMetadata` | EF.RateLimiting | Per-tenant partitions with tiers and named budgets, 429 with `Retry-After`; throws when `UseRateLimiter` runs before `UseAuthentication` |
| `UseEdgeLimiter(settings)`, `EdgeRateLimitSettings` (section `RateLimiting:Edge`), `AddPerClientIpFixedWindowPolicy`, `AddRetryAfter`, `ClientPartitionKey` | EF.RateLimiting | Gateway edge limiter: per-client token bucket plus a process concurrency cap |
| `FailOpenRateLimiter`, `FailOpenCircuit`, `FailOpenOptions` (`BackendTimeout`, `BreakDuration`), `RateLimitingTelemetry` (meter `EF.RateLimiting`: `ratelimit.rejected`, `ratelimit.backend_failure`) | EF.RateLimiting | Admits requests while a distributed backend fails or is slower than `BackendTimeout`, counts it, and probes with one request after `BreakDuration`; `AddRedisRateLimiting` wires it, app code does not construct it |
| `AddRedisRateLimiting(serviceKey)`, `RedisSlidingWindowRateLimiter` | EF.RateLimiting.Redis | One shared sliding window per budget in Redis over the EF.Cache `IConnectionMultiplexer` from DI |

### Messaging Contracts (EF.Messaging.Contracts)

Broker-free, AOT-compatible primitives that domain, application and consumer projects reference instead of `EF.Messaging`. Outbox, inbox and consumer policy: [../skills/messaging.md](../skills/messaging.md).

| Type | Package | Used For |
|---|---|---|
| `IntegrationEventEnvelope`, `EnvelopeSerializer` | EF.Messaging.Contracts (`EF.Messaging`) | Versioned wire frame (`Id`, `Type`, `Version`, `OccurredAtUtc`, `CorrelationId`, `Payload`) and its serializer; trimmed apps pass their source-generated context options |
| `MessagingActivitySource`, `MessagingTraceContext` | EF.Messaging.Contracts (`EF.Messaging.Tracing`) | `send {destination}` / `process {destination}` spans and W3C `traceparent` inject, extract and parse |
| `MessagingMetrics` | EF.Messaging.Contracts (`EF.Messaging`) | Meter `EF.Messaging`: `ef.outbox.*`, `ef.work.*`, `ef.inbox.*`, `ef.consumer.duration` |
| `IOutboxTransport`, `OutboxItem`, `OutboxSendResult`, `OutboxSendFailure`, `OutboxHeaders`, `OutboxBodyBuffer` | EF.Messaging.Contracts (`EF.Messaging.Outbox`) | The broker port the dispatcher sends through; packaged for Service Bus and RabbitMQ |
| `OutboxEntry`, `IOutboxEventMapper`, `IOutboxStaging` | EF.Messaging.Contracts (`EF.Messaging.Outbox`) | Domain event to outbox row mapping, and explicit staging for events no aggregate raises |
| `IInboxStore`, `InboxClaim`, `InboxClaimStatus`, `InboxClaimOptions` (section `Messaging:Inbox`) | EF.Messaging.Contracts (`EF.Messaging`) | Two-state consumer inbox contract and its lease timings; `MaxClaimDuration` caps renewal |
| `IntegrationEnvelopeReader`, `IntegrationEnvelopeReaderOptions` | EF.Messaging.Contracts (`EF.Messaging`) | Transport-independent body parse with dead-letter reasons (`MalformedEnvelope`, `UnsupportedEventType`) |
| `IntegrationEventConsumerBase`, `ConsumeDisposition` | EF.Messaging.Contracts (`EF.Messaging`) | Idempotent consumer: `ConsumerName`, `Handles(eventType)`, `ConsumeAsync(envelope, ct)`; claim, renewal, bounded wait and completion live in the base |

### Outbox and Inbox Stores (EF.Data.Outbox)

Provider-neutral EF Core (PostgreSQL and SQL Server); does not reference `EF.Data`.

| Type | Package | Used For |
|---|---|---|
| `AddOutbox<TContext>(o => ...)`, `OutboxOptions` (`DefaultDestination`, `SerializerOptions`), `OutboxStagingInterceptor`, `OutboxMessage`, `DefaultOutboxEventMapper` | EF.Data.Outbox | Stages every `IHasDomainEvents` event as an `OutboxMessage` row in the same `SaveChanges`; register the interceptor on the write context |
| `AddOutboxDispatcher()`, `OutboxDispatcherService`, `OutboxDispatcherOptions` (`SendTimeout`) | EF.Data.Outbox | Leased dispatcher on every replica with a transport; host start fails unless `LeaseDuration > SendTimeout + SettlementTimeout` |
| `AddInbox<TContext>()`, `InboxStore<TContext>`, `InboxEntry` | EF.Data.Outbox | `IInboxStore` on table `ConsumerInbox`; needs `IDbContextFactory<TContext>` for lease renewal |
| `ApplyOutboxModel(schema)`, `ApplyInboxModel(schema)` | EF.Data.Outbox | Model mappings for the two tables, called from `OnModelCreating` |
| `LeasedWorkItem`, `LeasedWorkConfiguration<TWork>`, `LeasedWorkTableWorker<TWork, TOptions>`, `WorkBatchResult`, `AddLeasedWorkStore<TContext>()` | EF.Data.Outbox | App work tables claimed with a lease, retried with backoff, parked after `MaxAttempts` |
| `AddLeasedWorkBacklogCheck<TWork>(name, configure, tags)` | EF.Data.Outbox | Backlog health check per work table (lag and pending thresholds) |
| `OutboxActivitySource` | EF.Data.Outbox | `{WorkType} drain` spans; add `OutboxActivitySource.Name` to tracing |

### Messaging (EF.Messaging)

Add when the app publishes or consumes Azure Service Bus, Event Grid, or Event Hub messages.

| Type | Package | Used For |
|---|---|---|
| `IServiceBusSender` | EF.Messaging | Contract for publishing to Service Bus |
| `ServiceBusSenderBase` | EF.Messaging | Abstract Service Bus sender (derive per-project) |
| `ServiceBusSenderSettingsBase` | EF.Messaging | Settings base for sender configuration |
| `ServiceBusProcessorBase` | EF.Messaging | Abstract Service Bus message processor (implement `IServiceBusReceiver`) |
| `ServiceBusProcessorSettingsBase` | EF.Messaging | Settings base for processor configuration |
| `IEventGridPublisher` | EF.Messaging | Contract for publishing Event Grid events |
| `EventGridPublisherBase` | EF.Messaging | Abstract Event Grid publisher (derive per-project) |
| `EventGridPublisherSettingsBase` | EF.Messaging | Settings base for publisher configuration |
| `EventGridEvent` | EF.Messaging | Event Grid event model |
| `IEventHubProducer` | EF.Messaging | Contract for sending to Event Hub |
| `EventHubProducerBase` | EF.Messaging | Abstract Event Hub producer |
| `EventHubProducerSettingsBase` | EF.Messaging | Settings base for producer configuration |
| `IEventHubProcessor` | EF.Messaging | Contract for consuming from Event Hub |
| `EventHubProcessorBase` | EF.Messaging | Abstract Event Hub processor |
| `EventHubProcessorSettingsBase` | EF.Messaging | Settings base for processor configuration |
| `IServiceBusReceiver`, `ServiceBusSenderPool` | EF.Messaging | Receiver contract for `ServiceBusProcessorBase`; pooled senders per entity |
| `AddServiceBusOutboxTransport(o => ...)`, `ServiceBusOutboxOptions` | EF.Messaging (`EF.Messaging.ServiceBus`) | Service Bus `IOutboxTransport` for the dispatcher |
| `AddServiceBusHealthCheck(clientName, entityPath, name, tags)` | EF.Messaging (`EF.Messaging.ServiceBus`) | Service Bus entity health check |

The envelope, tracing and metrics types are in EF.Messaging.Contracts (same namespaces).

### Service Bus Triggers (EF.Messaging.Functions)

| Type | Package | Used For |
|---|---|---|
| `ServiceBusIntegrationEventDispatcher.DispatchAsync(message, actions, consumer, readerOptions, logger, ct)` | EF.Messaging.Functions | One-line Functions isolated-worker trigger body: reads the envelope, runs the `IntegrationEventConsumerBase`, settles (dead-letter unreadable, complete, abandon on in-progress, rethrow on failure) with `CancellationToken.None`. The host turns auto-complete off |

### RabbitMQ (EF.Messaging.RabbitMq)

Framework-free RabbitMQ transport.

| Type | Package | Used For |
|---|---|---|
| `IRabbitMqPublisher` (`PublishAsync`, `PublishBatchAsync`), `RabbitMqMessage`, `RabbitMqPublishException` | EF.Messaging.RabbitMq | Confirmed publishing |
| `IRabbitMqMessageHandler` (`Task<ConsumeResult> HandleAsync(RabbitMqDelivery, ct)`), `ConsumeResult`, `ConsumeOutcome`, `RabbitMqConsumerHostedService<THandler>` | EF.Messaging.RabbitMq | Consumers |
| `RabbitMqIntegrationEventHandler<TConsumer>` | EF.Messaging.RabbitMq | Adapter from a delivery to an `IntegrationEventConsumerBase`: unreadable dead-letters, consumed or duplicate acks, in-progress retries |
| `AddRabbitMqOutboxTransport(o => o.DefaultExchange = ...)`, `RabbitMqOutboxOptions` | EF.Messaging.RabbitMq | RabbitMQ `IOutboxTransport`; only unconfirmed indices fail |
| `RabbitMqTopology`, `RabbitMqExchange`, `RabbitMqQueue`, `RabbitMqBinding`, `IRabbitMqTopologyDeclarer` | EF.Messaging.RabbitMq | Topology declaration |
| `RabbitMqOptions`, `RabbitMqConsumerOptions` (section `Messaging:RabbitMq:Consumers:<queue>`: `RetryBaseDelay`, `RetryMaxDelay`, `AttemptTrackingWindow`) | EF.Messaging.RabbitMq | Connection and consumer options; a failed delivery waits its retry delay before the requeue |
| `AddRabbitMqMessaging(config, "Messaging:RabbitMq")`, `AddRabbitMqConsumer<THandler>(...)`, `AddRabbitMqTopology(...)`, `AddRabbitMqHealthCheck(...)` | EF.Messaging.RabbitMq | Registration |

### Scheduling (EF.BackgroundServices.TickerQ)

TickerQ over the scheduler's operational store. Cron declaration and health policy: [../skills/background-services.md](../skills/background-services.md).

| Type | Package | Used For |
|---|---|---|
| `AddEFTickerQ<TDbContext>(config, configureDbContext, schema, configure)` / `AddEFTickerQ(config, configure)`, `TickerQSchedulerSettings` (section `Scheduling`) | EF.BackgroundServices.TickerQ | Registration with UTC, `{MachineName}:{ProcessId}` node identity and a distributed lock around cron seeding; the in-memory overload suits one replica and tests |
| `ScheduledJobRunner.RunAsync<THandler>(context, ct)` | EF.BackgroundServices.TickerQ | Runs an `IScheduledJobHandler` in TickerQ's execution scope with one span, `scheduler.job.*` metrics and TickerQ's cancellation contract |
| `TickerQSchemaValidator.ValidateAsync<TDbContext>(services)` | EF.BackgroundServices.TickerQ | Names every missing TickerQ table; never creates schema |
| `TickerQOccurrenceRetentionHandler<TDbContext>`, `TickerQRetentionSettings` (section `Scheduling:Retention`) | EF.BackgroundServices.TickerQ | Deletes finished occurrences past retention |
| `AddSchedulerHealthCheck<TDbContext>(tags)`, `SchedulerHealthSettings` (section `Scheduling:Health`, `StallThreshold` required) | EF.BackgroundServices.TickerQ | Stall check on the latest cron execution |

### Azure Storage (EF.Storage)

Add when the app needs Blob Storage access. Do not hand-roll blob logic - extend `BlobRepositoryBase`.

| Type | Package | Used For |
|---|---|---|
| `IBlobRepository` | EF.Storage | Blob-specific contract: container create/delete, blob paging and streaming lists, SAS URI generation, `UploadBlobStreamAsync`, `StartDownloadBlobStreamAsync`, `DeleteBlobAsync` (container and SAS URI overloads) |
| `BlobRepositoryBase` | EF.Storage | Abstract blob repository implementing `IBlobRepository` and `IObjectStorageRepository`; also `DistributedLockExecuteAsync` (blob lease). Extend with a project-specific class |
| `BlobRepositorySettingsBase` | EF.Storage | Settings base (requires `BlobServiceClientName`) |
| `ContainerInfo` | EF.Storage | Container configuration model |
| `ContainerPublicAccessType` | EF.Storage | Enum for container access level |
| `BlobContainerHealthCheck`, `AddBlobContainerHealthCheck(name, clientName, containerName, tags)` | EF.Storage | Existence check of the container the app uses (least privilege) |

**Constructor constraint:** `BlobRepositoryBase(ILogger<BlobRepositoryBase>, IOptions<BlobRepositorySettingsBase>, IAzureClientFactory<BlobServiceClient>)` - the settings parameter uses the base type. Register via `services.Configure<BlobRepositorySettingsBase>(...)` or use covariant DI binding.

All members are implemented and non-virtual; a project repository derives only to bind its settings and add app-specific methods ([../skills/azure-blob-storage.md](../skills/azure-blob-storage.md) -> *Project Repository Wrapper*).

### Object Storage (EF.Storage.Contracts, EF.Storage.S3)

Provider-neutral object storage. `BlobRepositoryBase` (Azure) and `S3ObjectStorageRepositoryBase` (S3-compatible, MinIO or AWS) both implement the contract, so application code depends on `IObjectStorageRepository` only.

| Type | Package | Used For |
|---|---|---|
| `IObjectStorageRepository` | EF.Storage.Contracts | `UploadAsync(containerName, objectName, content, contentType, metadata, ct)`, `DownloadAsync`, `DeleteAsync`, `ExistsAsync`, `GetPresignedUrlAsync`, `ListAsync` |
| `ObjectStorageItem`, `ObjectStoragePage`, `ObjectStoragePermissions` | EF.Storage.Contracts | List results and presigned-URL permissions |
| `S3ObjectStorageRepositoryBase` / `S3ObjectStorageRepository` | EF.Storage.S3 | S3 implementation |
| `S3StorageSettings` (section `Storage:S3`), `IS3BucketProvisioner` (`CheckBucketAsync`, `EnsureBucketExistsAsync`), `AddS3ObjectStorage(settings)` | EF.Storage.S3 | Settings, bucket provisioning, registration |
| `S3BucketHealthCheck`, `AddS3BucketHealthCheck(name, bucketName, tags)` | EF.Storage.S3 | Scoped `HeadBucket` check of the bucket the app uses |

### Azure Table Storage (EF.Table)

Add when the app needs Table Storage. Do not hand-roll table logic - extend `TableRepositoryBase`.

| Type | Package | Used For |
|---|---|---|
| `ITableRepository` | EF.Table | Table storage contract (get, create, upsert, delete, page query, stream) |
| `TableRepositoryBase` | EF.Table | Abstract table repository; extend with a project-specific class |
| `TableRepositorySettingsBase` | EF.Table | Settings base (requires `TableServiceClientName`) |
| `TableUpdateMode` | EF.Table | Enum: `Merge` (partial update) or `Replace` (full overwrite) |

**Constructor constraint:** `TableRepositoryBase(ILogger<TableRepositoryBase>, IOptions<TableRepositorySettingsBase>, IAzureClientFactory<TableServiceClient>)` - same base-type settings pattern as `BlobRepositoryBase`.

### Azure Cosmos DB (EF.CosmosDb)

Add when the app needs Cosmos DB document storage.

| Type | Package | Used For |
|---|---|---|
| `ICosmosDbRepository` | EF.CosmosDb | Cosmos DB contract (save, get, delete, paged query, projection query) |
| `CosmosDbRepositoryBase` | EF.CosmosDb | Abstract Cosmos DB repository |
| `CosmosDbRepositorySettingsBase` | EF.CosmosDb | Settings base (requires `CosmosClient` and `CosmosDbId`); ctor `CosmosDbRepositoryBase(ILogger<CosmosDbRepositoryBase>, IOptions<CosmosDbRepositorySettingsBase>)` |
| `CosmosDbEntity` | EF.CosmosDb | Base entity with `PartitionKey` property and `id` alias |
| `CosmosClientSettings` (`PreferredRegions`, `HedgingEnabled`, `HedgingThresholdMs`, `HedgingThresholdStepMs`), `CosmosClientOptionsFactory.Create` | EF.CosmosDb | Client options with cross-region read hedging when enabled |
| `CosmosDbHealthCheck`, `AddCosmosDbHealthCheck(name, tags)` | EF.CosmosDb | Account check through the registered client |

### Azure Key Vault (EF.KeyVault)

Add when the app retrieves secrets, keys, or certificates from Key Vault.

| Type | Package | Used For |
|---|---|---|
| `IKeyVaultManager` | EF.KeyVault | Secrets, keys, and certificates operations |
| `KeyVaultManagerBase` / `KeyVaultManagerSettingsBase` | EF.KeyVault | Abstract `IKeyVaultManager` implementation and its settings |
| `IKeyVaultCryptoUtility` / `KeyVaultCryptoUtility` | EF.KeyVault | Encrypt/decrypt helpers via Key Vault |

### gRPC (EF.Grpc)

Add when the app exposes or consumes gRPC services.

| Type | Package | Used For |
|---|---|---|
| `ServiceErrorInterceptor`, `ErrorInterceptorSettings` (`IncludeExceptionMessageInResponse`, default false) | EF.Grpc | Server interceptor for unary and streaming calls: rethrows a service's own `RpcException`, maps everything else through `ExceptionClassifier` with the category name as detail |
| `ClientErrorInterceptor` | EF.Grpc | Client-side error logging |
| `GrpcStatusCodes.For(ExceptionCategory)` | EF.Grpc | Category to `StatusCode` table |
| `AddEFGrpcClient<TClient>(settings, bearerTokenProvider, serverCertificateValidation)`, `GrpcClientSettings` | EF.Grpc | Client registration over `SocketsHttpHandler` (multiple HTTP/2 connections), per-call bearer token, optional mTLS (base64 PKCS#12) |

### AI (EF.AI)

Provider-agnostic chat and embeddings over Microsoft.Extensions.AI. Provider selection policy: [../skills/ai-integration.md](../skills/ai-integration.md).

| Type | Package | Used For |
|---|---|---|
| `AddEFChatClient()`, `AddEFChatClients()`, `AddEFChatClientFromAspire()`, `EFChatClientSettings`, `EFChatClientProvider` | EF.AI (`EF.AI.Chat`) | `IChatClient` registration; providers `Disabled`, `OpenAICompatible`, `GitHubModels`, `OpenAI`, `Foundry`, `AzureAIInference`, `OpenRouter`, `Ollama`, `VLlm` |
| `AddEFEmbeddingGenerator()`, `EFEmbeddingGeneratorSettings`, `EFEmbeddingGeneratorProvider` | EF.AI (`EF.AI.Embeddings`) | `IEmbeddingGenerator` registration |
| `EFAIDisabledException`, `IsDisabled()` | EF.AI | Every call on a `Disabled` client throws `EFAIDisabledException`; hosts map it with `Map<EFAIDisabledException>(ExceptionCategory.Unavailable)` (503) |

Test doubles for both interfaces are in EF.AI.Testing (section Testing (EF.Testing, EF.Testing.Architecture, EF.AI.Testing, EF.IntegrationTesting.*) below).

### Microsoft Graph (EF.MSGraph)

Add when the app calls Microsoft Graph APIs.

| Type | Package | Used For |
|---|---|---|
| `IMSGraphServiceBase` / `MSGraphServiceBase` / `MSGraphServiceSettingsBase` | EF.MSGraph | Graph operations over an injected `GraphServiceClient` (no auth wiring) |
| `ExternalIdUserFlowService`, `GraphUserRequest` (`EF.MSGraph.Models`) | EF.MSGraph | External ID user-flow operations |

### Durable Audit (EF.Audit.Contracts, EF.Audit.Data, EF.Audit.AzureTable)

`AuditInterceptor` appends to the `IAuditLogRepository` sinks it is given; the scaffold persists through the internal bus instead ([../skills/data-persistence.md](../skills/data-persistence.md) section Audit Strategy). Both packaged backends derive `RecordedUtc` and every key from the UUIDv7 timestamp of the entry id, so a replayed entry writes the same row.

| Type | Package | Used For |
|---|---|---|
| `IAuditLogRepository` (`AppendAsync`, `QueryAsync(AuditLogQuery, ct)`, `PurgeOlderThanAsync`) | EF.Audit.Contracts | Backend-neutral audit sink and query contract; `QueryAsync` accepts page sizes 1 to `AuditLogQuery.MaxPageSize` (1000) |
| `AuditRecord` (`StartedAtUtc`), `AuditLogQuery`, `AuditLogPage`, `AuditLogSettingsBase`, `AuditSettings` | EF.Audit.Contracts | Query and settings models |
| `RelationalAuditLogRepository<TContext>`, `AddRelationalAuditLog<TContext>(configure)`, `AuditLogRecordConfiguration(tableName, schema)`, `RelationalAuditLogSettings` | EF.Audit.Data | Relational backend over the app's own context: map the row with `AuditLogRecordConfiguration` so it shares the app migration set; append is one idempotent upsert, continuation tokens are keyset tokens |
| `AzureTableAuditLogRepository` (`EnsureTableAsync`), `AzureTableAuditLogSettings`, `AddAzureTableAuditLog(configure)` | EF.Audit.AzureTable | Azure Table backend built on EF.Table, a singleton; appends never create the table, so a startup task calls `EnsureTableAsync` |

### Client Resilience (EF.Http.Resilience)

No ASP.NET Core dependency, so UI and console clients use it too. Hedging policy: [../skills/resilience.md](../skills/resilience.md) section Hedging.

| Type | Package | Used For |
|---|---|---|
| `AddReadHedging(config, sectionName)`, `ReadHedgingSettings` (section `Resilience:Hedging`) | EF.Http.Resilience | GET/HEAD-only hedging on a dedicated read client; each hedged attempt sends its own request snapshot |
| `AddCustomResilience(excludedStatusCodes, retryUnsafeMethods, configure)` | EF.Http.Resilience | Standard resilience handler that never retries unsafe methods unless asked |

### UI Client (EF.UI.Client, EF.UI.Refit)

UI-framework-neutral, AOT-compatible client plumbing (Uno, Blazor, MAUI). Uno wiring: [../templates/uno-ui-client-layer.md](../templates/uno-ui-client-layer.md).

| Type | Package | Used For |
|---|---|---|
| `IUiDispatcher` (`HasThreadAccess`, `Post`, `Inline`), `AddUiClient(configure)` | EF.UI.Client | Registers `IBusyTracker` and `INotificationService`; the app registers its platform `IUiDispatcher` (a missing one fails at resolution) |
| `IBusyTracker` / `BusyTracker`, `INotificationService` / `NotificationService`, `Notification`, `NotificationOptions` | EF.UI.Client (`EF.UI.Client.Notifications`) | Reference-counted busy indicator; notification queue with per-severity auto-dismiss, `DedupeKey`, `ShowProblem` |
| `AddBusyTracking()`, `AddProblemDetailsNotifications(configure)`, `BusyDelegatingHandler`, `ProblemDetailsDelegatingHandler`, `ProblemDetailsPayload`, `ProblemDetailsException` | EF.UI.Client (`EF.UI.Client.Http`) | `HttpClient` handlers: busy scope per send, problem+json translated once into a notification; register both before any resilience handler |
| `EntityTags` (`ForVersion`, `Parse`), `IfMatchHttpClientExtensions` (`PutAsJsonAsync`, `DeleteAsync`) | EF.UI.Client (`EF.UI.Client.Http`) | Strong `If-Match` writes from hand-written clients |
| `RuntimeClientConfiguration` (`LoadBaseUrlAsync`, `ParseBaseUrl`) | EF.UI.Client (`EF.UI.Client.Configuration`) | Validated `/app-config.json` runtime base URL for static-hosted clients |
| `RefitCallHelper` (`TryApiCallAsync`, `TryApiCallIfAsync`, `TryApiCallWithMetaAsync`), `RefitCallOptions`, `ApiResult` / `ApiResult<T>`, `RefitExtensions` | EF.UI.Refit | Refit call wrapper mapping every failure to a `ProblemDetails` result; `OnAuthError` is per call |

### Column Encryption (EF.Data.Encryption)

Provider-neutral application-layer column encryption.

| Type | Package | Used For |
|---|---|---|
| `IColumnEncryptor` / `AesGcmColumnEncryptor` / `PlaintextColumnEncryptor` | EF.Data.Encryption | Encrypt and decrypt column values |
| `BlindIndex` / `BlindIndexInterceptor` | EF.Data.Encryption | Deterministic lookup index over an encrypted value |
| `ColumnEncryptionOptions`, `ColumnEncryptionKeys`, `KeyVaultDekProvider` | EF.Data.Encryption | Key material and Key Vault DEK unwrap |
| `UseColumnEncryption()`, `AddColumnEncryption()`, `GetColumnEncryptor()` | EF.Data.Encryption | Options-builder, DI, and `DbContext` wiring |

### Observability and Data Protection (EF.OpenTelemetry, EF.AspNetCore.DataProtection)

| Type | Package | Used For |
|---|---|---|
| `AddEfOpenTelemetry(o => ...)`, `OpenTelemetrySettings` (section `OpenTelemetry`) | EF.OpenTelemetry | Logs, traces and metrics; OTLP / Azure Monitor exporter matrix from configuration; validated `Tracing:SampleRatio`; `SuppressAspNetCoreInstrumentation`; the app adds its `MeterNames` and `ActivitySourceNames` |
| `FilterActivityProcessor` | EF.OpenTelemetry | Drops matching activities from export |
| `AddEfDataProtection(settings, credential)`, `DataProtectionSettings` (section `DataProtection`), `DataProtectionPersistence` (`None`, `AzureBlob`, `Redis`) | EF.AspNetCore.DataProtection | Persisted key ring, optional Key Vault key encryption; Redis resolves the shared `IConnectionMultiplexer` when no connection string is set |

### Testing (EF.Testing, EF.Testing.Architecture, EF.AI.Testing, EF.IntegrationTesting.*)

No package references a test framework: the test decides skip or fail.

| Package | Types | Used By |
|---|---|---|
| EF.Testing | `EF.Testing.Load`: `LoadRunner`, `LoadResult`. `EF.Testing.Environment`: `EnvironmentVariableScope`, `TestEnvironment`, `RepositoryRoot`, `FunctionsCoreToolsDiscovery`. `EF.Testing.Processes`: `ProcessRunner`, `DockerRuntimePreflight`. `EF.Testing.Http`: `StubHttpMessageHandler`, `HttpReadiness`, `ConcurrencyHttpExtensions`. `EF.Testing.Json`: `JsonNodeDiff` | `Test.Support` (every tier), `Test.Load`, `Test.UI`, `Test.Mobile` |
| EF.Testing.Architecture | `DependencyRules`, `ConstructorRules`, `MethodCallRules`, `SourceFiles` / `SourceRules`, `JsonContextRules`, `ConventionRules`, all returning `ArchitectureRuleResult` | `Test.Architecture` |
| EF.AI.Testing | `FakeChatClient`, `FakeChatCall`, `FakeEmbeddingGenerator` | Tests over `IChatClient` / `IEmbeddingGenerator` |
| EF.IntegrationTesting | `EF.IntegrationTesting.AspNetCore`: `EfWebApplicationFactoryBase<TProgram, TTrxnContext, TQueryContext>`, `EfTestDbContextFactory<T>`, `RouteInventory`. `EF.IntegrationTesting.EntityFramework`: `DbContextOptionsFactory.BuildInMemoryOptions`, `RecordingCommandInterceptor`, `InsertInBatchesAsync`. `EF.IntegrationTesting.Testcontainers`: `ContainerFixture<TContainer>` | `Test.Support` WAF adapter ([../templates/test-templates-endpoint.md](../templates/test-templates-endpoint.md)), `Test.Integration`, `Test.E2E` |
| EF.IntegrationTesting.PostgreSql | `PostgreSqlContainerFixture` (`CreateDatabaseAsync`), `PostgreSqlTestDbContextOptions.Build<T>` | `TestDatabaseContainer` |
| EF.IntegrationTesting.SqlServer | `MsSqlContainerFixture` (`CreateDatabaseAsync`), `SqlServerTestDbContextOptions.Build<T>` | `TestDatabaseContainer` on a SQL Server arm |
| EF.IntegrationTesting.Aspire | `AspireTestHostContext`, `AspireTestHostOptions`, `AspireTestingHelpers` | `Test.Aspire` mesh fixtures ([../templates/test-templates-aspire.md](../templates/test-templates-aspire.md)) |

---

### CQRS (EF.CQRS)

Add when `applicationStyle` is `cqrs` or `switch`. In local mode, generate this as `src/Packages/<packagePrefix>.CQRS` and consume it through `<ProjectReference>`.

| Type | Package | Used For |
|---|---|---|
| `ICommand<TResponse>` | EF.CQRS (`EF.CQRS.Abstractions`) | Write request marker |
| `IQuery<TResponse>` | EF.CQRS (`EF.CQRS.Abstractions`) | Read request marker |
| `IRequestHandler<in TRequest,TResponse>` | EF.CQRS (`EF.CQRS.Abstractions`) | Single request handler contract |
| `IRequestValidator<TRequest>` | EF.CQRS | Optional request validator contract |
| `RequestValidationResult` | EF.CQRS | Validator result with one or more errors; `Failure` with no non-blank error throws `ArgumentException` |
| `IValidationFailureResponseFactory<out TResponse>` | EF.CQRS | `CreateFailure(IReadOnlyCollection<DomainError>)` converts validation errors to the app response shape |
| `StaticFailureValidationResponseFactory<TResponse>` | EF.CQRS | Reflection-based factory for common static `Failure(...)` result shapes |
| `ValidationRequestHandlerDecorator<TRequest,TResponse>` / `LoggingRequestHandlerDecorator<TRequest,TResponse>` | EF.CQRS | Validation and logging decorators around handlers |
| `AddDecoratedRequestHandler<TRequest,TResponse,THandler>(ServiceLifetime lifetime = Scoped, Action<DecoratedRequestHandlerOptions>? configure = null)` | EF.CQRS | Registers the concrete handler and the interface wrapped in validation and logging decorators (`DecoratedRequestHandlerOptions.EnableValidation` / `EnableLogging`, both default true). Also `AddDecoratedRequestHandlers`, `AddRequestHandler`, `AddRequestValidator` |

**Dispatch rule:** EF.CQRS has no MediatR dependency, dispatcher, request bus, or generic `Send` method. Minimal API endpoints inject the exact `IRequestHandler<TRequest,TResponse>` they call. Scaffold request records, handlers, validators, and per-feature registration fragments under `Application.Cqrs/Features/{Entity}`.

### Tenancy (EF.Tenancy)

Add when the domain is multi-tenant. Policy (who may cross the boundary, the system identity): [../skills/multi-tenant.md](../skills/multi-tenant.md).

| Type | Package | Used For |
|---|---|---|
| `ITenantBoundaryValidator` / `TenantBoundaryValidator` | EF.Tenancy | Singleton: `EnsureTenantBoundary(callerTenantId, callerRoles, entityTenantId, operation, entityName, entityId)`, `EnsureCrossTenantRole(callerRoles, operation)`, `PreventTenantChange(existing, incoming, entityName, entityId)`, `EnforceTenantFilter(filter, callerTenantId, callerRoles, operation)`; each returns `Result` (or the forced filter) and logs security events 4100-4104 |
| `ITenantScopedFilter` | EF.Tenancy | `Guid? TenantId` on the app's search filter, forced by `EnforceTenantFilter` |
| `AddTenancy(o => o.CrossTenantRoles = [...])`, `TenancyOptions`, `TenantBoundaryErrorCodes` (`tenant.forbidden`, `tenant.change`) | EF.Tenancy | Registration; only a role in `CrossTenantRoles` (default `GlobalAdmin`) passes the boundary |

### SQL Server Extras (EF.Data.SqlServer)

| Type | Package | Used For |
|---|---|---|
| `ConnectionNoLockInterceptor` / `ReadUncommittedInterceptor` | EF.Data.SqlServer (`EF.Data.SqlServer.Interceptors`) | `READ UNCOMMITTED` isolation for query contexts |
| `WithReadUncommittedAsync(read, ct)` | EF.Data.SqlServer | One dirty read on `DatabaseFacade` outside a repository |
| `MigrationSupport` | EF.Data.SqlServer | Always Encrypted DDL inside a migration: ctor `(MigrationBuilder, DefaultAzureCredential)`, `CreateColumnMasterKey`, `CreateColumnEncryptionKey`, `AlterColumnEncryption` - see [data-persistence-advanced.md](data-persistence-advanced.md) -> Always Encrypted |

### Other Packages

| Package | Types | Used For |
|---|---|---|
| EF.Utility | `Scraper`, `ScrapedData` (`EF.Utility.Webscraper`) | Web scraping |
| EF.BlandAI | `IBlandAIRestClient`, `BlandAIRestClient`, `BlandAISettings` | Bland AI voice API |
| EF.Cosmic | `ICosmicService`, `CosmicService`, `CosmicServiceSettings` | Swiss Ephemeris calculations |

---

## EF.Packages.Enterprise

**Feed:** `https://nuget.pkg.github.com/efreeman518/index.json` (same GitHub Packages feed, `EF.*` pattern mapping applies).

Enterprise packages are opt-in. Add them only when the project requires durable workflow orchestration or runtime filter expression building.

### Workflow Engine (EF.FlowEngine)

JSON-defined, durable workflow orchestration engine with pluggable backends (state store, locks, human tasks, outbox, circuit breaker).

**Core interfaces:**

| Type | Package | Used For |
|---|---|---|
| `IFlowEngine` | EF.FlowEngine | Main orchestration API: start, signal, resume, terminate, get status |
| `IWorkflowRegistry` | EF.FlowEngine | Workflow definition CRUD and status transitions |
| `IFlowClient` | EF.FlowEngine | Base contract for all execution clients |
| `IRequestResponseClient` | EF.FlowEngine | Synchronous HTTP/gRPC call nodes |
| `IQueryClient` | EF.FlowEngine | Data query nodes (EF Core via `EF.FlowEngine.Clients.Sql`; ad hoc SQL Server via `EF.FlowEngine.Clients.SqlServer`) |
| `IMessageClient` | EF.FlowEngine | Async messaging nodes (Service Bus via `EF.FlowEngine.Clients.ServiceBus`) |
| `IAgentClient` | EF.FlowEngine | AI/LLM agent invocation nodes (any `IChatClient` via `EF.FlowEngine.Clients.AI`) |
| `IFlowEngineClient` | EF.FlowEngine | Cross-engine orchestration nodes |
| `IDistributedLockProvider` | EF.FlowEngine | Distributed locking (pluggable: SQL, Redis, Cosmos, Blob, InMemory) |
| `IExecutionStateStore` | EF.FlowEngine | Execution state persistence (pluggable: SQL, Redis, Cosmos, File) |
| `IHumanTaskStore` | EF.FlowEngine | Human task/approval management (pluggable: SQL, Redis, Cosmos) |
| `IOutboxStore` | EF.FlowEngine | Transactional outbox (pluggable: SQL) |
| `ICircuitBreakerStore` | EF.FlowEngine | Circuit breaker state (pluggable: SQL, Redis) |

**Key model types:**

| Type | Used For |
|---|---|
| `WorkflowDefinition` | Workflow schema (nodes + edges) |
| `NodeConfig` (and subtypes) | Per-node configuration: Decision, Fetch, Filter, Human, Loop, Parallel, Timer, Transform, Wait, Message, Agent, Document, etc. |
| `HumanTask` / `HumanTaskStatus` | Human approval/review task model |
| `OutboxEntry` / `OutboxEntryType` | Transactional outbox entry |
| `ExecStatus` | Execution status enum: Pending, Running, Completed, Failed, Suspended, Terminated |
| `DefinitionStatus` | Workflow definition status: Draft, Active, Archived |
| `FilterSet` / `SearchRequest` | Used by `IQueryClient` for declarative data queries |

**Built-in implementations (for testing/dev):**

| Type | Used For |
|---|---|
| `InMemoryWorkflowRegistry` | In-memory registry (unit tests / local dev) |
| `JsonFileWorkflowRegistry` | File-backed registry (local dev without DB) |
| `InMemoryDistributedLockProvider` | Single-process locking (unit tests) |
| `LoggerFlowEngineTelemetry` | Logging-based telemetry adapter |

**Pluggable backend packages:**

| Package | Purpose |
|---|---|
| `EF.FlowEngine.StateStore.Sql` | SQL-based execution state |
| `EF.FlowEngine.StateStore.Redis` | Redis-based execution state |
| `EF.FlowEngine.Locks.Sql` | SQL-based distributed locking |
| `EF.FlowEngine.Locks.Redis` | Redis-based distributed locking |
| `EF.FlowEngine.WorkflowRegistry.Sql` | SQL-backed workflow registry |
| `EF.FlowEngine.HumanTaskStore.Sql` | SQL-backed human task store |
| `EF.FlowEngine.Outbox.Sql` | SQL transactional outbox |
| `EF.FlowEngine.CircuitBreaker.Sql` | SQL circuit breaker state |
| `EF.FlowEngine.Clients.Http` | HTTP/REST client for `IRequestResponseClient` |
| `EF.FlowEngine.Clients.Sql` | EF Core client for `IQueryClient` (any EF Core provider) |
| `EF.FlowEngine.Clients.SqlServer` | Parameterized ad hoc SQL Server client for `IQueryClient` (connection string) |
| `EF.FlowEngine.Clients.ServiceBus` | Azure Service Bus client for `IMessageClient` |
| `EF.FlowEngine.Clients.AI` | Microsoft.Extensions.AI `IChatClient` binding for `IAgentClient` (OpenAI-compatible endpoints, Azure OpenAI helper) |
| `EF.FlowEngine.AdminApi` | REST management endpoints for workflow monitoring |
| `EF.FlowEngine.Testing` | Test helpers and fixtures |

### FlowEngine Data-Layout Variants

When `includeFlowEngine: true`, the integrator picks a `flowEngineDbStrategy`. The choice is **load-bearing** because FE's atomic-outbox guarantee depends on FE state + outbox living in the same DbContext / transaction scope.

| Variant | `flowEngineDbStrategy` | DB / Schema | Outbox guarantee | When to choose |
|---|---|---|---|---|
| **A** (default) | `same-db-separate-schema` | App DB, FE schema (`flowengine`), separate `__EFMigrationsHistory_FlowEngine` | **Atomic.** State save and outbox publish commit in one transaction. `message`/`integration`/`agent` nodes are exactly-effected once the workflow advances. | Default for any new scaffold. Operational simplicity wins. |
| **B** | `separate-db` | Dedicated FE database, FE schema | **Best-effort.** State and outbox are in the same FE DB so FE-internal atomicity holds - but cross-DB failure modes between FE and the app DB are no longer transactional from the app's perspective. | Compliance separation, independent scaling, or per-tenant FE isolation. |
| **C** | `separate-db` + cross-publisher relay | Dedicated FE database; FE `message` nodes routed through the app's existing at-least-once publisher | **Best-effort + relay** - degrades the same way as B, but the integrator wires FE outbox events to the app's transactional publisher to recover atomicity at the app boundary. | Variant B is required but cross-publisher relay is acceptable. |

**Failure mode in B/C.** A crash between FE state-save and FE outbox-publish is the same window FE closes for Variant A - but FE's atomic guarantee no longer extends across the app's boundary. Loss surface: `message`, `integration`, and `agent` node side effects. Not state.

**What the scaffold emits per variant.**

- Variant A: dedicated FE DbContext via interface composition (see [../skills/flowengine.md](../skills/flowengine.md)), FE schema constant, FE migration-history table constant, single connection string.
- Variant B/C: same DbContext shape, **separate connection string** (e.g., `ConnectionStrings:FlowEngine`), Aspire resource entry for the FE DB, and a warning entry in `HANDOFF.md` naming the outbox degradation. Variant C additionally requires the integrator to wire FE message nodes to the app's existing publisher - the scaffold emits a `// TODO: [CONFIGURE]` stub in `RegisterServices.FlowEngine.cs` where the relay would attach.

Record the choice (and, for B/C, the relay plan) in `.scaffold/DESIGN-DECISIONS.md`.

### Runtime Filter Builder (EF.FilterBuilder)

Translates declarative `FilterSet` JSON/objects into LINQ `Expression<Func<T, bool>>` at runtime. Use when API consumers or workflow steps need to specify query filters without server-side code changes.

| Type | Package | Used For |
|---|---|---|
| `FilterBuilder<T>` | EF.FilterBuilder | Converts `FilterSet` -> `Expression<Func<T, bool>>` |
| `FilterSet` | EF.FilterBuilder | Filter definition (recursive: Simple, Expression, Group) |
| `FilterSetType` | EF.FilterBuilder | Enum for filter node type |
| `SearchRequest` | EF.FilterBuilder | Paged search request with filters, sorts, and page settings |
| `SearchResponse<T>` | EF.FilterBuilder | Paginated search results |
| `Sort` | EF.FilterBuilder | Sort specification (property + direction) |
| `QueryableExtensions` | EF.FilterBuilder | `IQueryable<T>` extension methods for filter application |
