# Optional Shared Packages (capability-gated `EF.*`)

Companion to [ef-packages-reference.md](ef-packages-reference.md), which owns delivery (`packageStrategy`), the always-needed layers, app-level types, phase usage, and rules. Load this file only when the matching capability is in scope. `EF` is the canonical example prefix; substitute your `packagePrefix`.

## Capability Packages

### Authentication (EF.Auth)

Add when the app needs outbound auth (calling protected APIs) or role/scope-based authorization.

| Type | Package | Used For |
|---|---|---|
| `IOAuth2TokenProvider` | EF.Auth | Token acquisition contract |
| `OAuth2TokenProvider` | EF.Auth | Generic OAuth2 token provider |
| `OAuth2Options` | EF.Auth | OAuth2 configuration options |
| `Auth0TokenProvider` | EF.Auth | Auth0-specific token provider |
| `Auth0Options` | EF.Auth | Auth0 configuration |
| `AzureAdTokenProviderConfidentialClientApp` | EF.Auth | Azure AD MSAL confidential client token provider |
| `AzureADOptions` | EF.Auth | Azure AD configuration |
| `IAzureDefaultCredTokenProvider` | EF.Auth | Contract for DefaultAzureCredential token acquisition |
| `AzureDefaultCredTokenProvider` | EF.Auth | DefaultAzureCredential-based token provider |
| `BaseDefaultAzureCredsAuthMessageHandler` | EF.Auth | `DelegatingHandler` for outbound HTTP auth with Azure credentials |
| `RolesOrScopesAuthorizationHandler` | EF.Auth | Flexible role or scope-based ASP.NET Core authorization handler |
| `RolesOrScopesRequirement` | EF.Auth | Authorization requirement for role/scope check |

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
| `IntegrationEventEnvelope` / `EnvelopeSerializer` | EF.Messaging | Versioned integration envelope and its serializer |
| `MessagingActivitySource` / `MessagingTraceContext` | EF.Messaging (`EF.Messaging.Tracing`) | Producer/consumer activities and W3C trace context propagation |

### RabbitMQ (EF.Messaging.RabbitMq)

Framework-free RabbitMQ transport.

| Type | Package | Used For |
|---|---|---|
| `IRabbitMqPublisher` (`PublishAsync`, `PublishBatchAsync`), `RabbitMqMessage`, `RabbitMqPublishException` | EF.Messaging.RabbitMq | Confirmed publishing |
| `IRabbitMqMessageHandler` (`Task<ConsumeResult> HandleAsync(RabbitMqDelivery, ct)`), `ConsumeResult`, `ConsumeOutcome`, `RabbitMqConsumerHostedService<THandler>` | EF.Messaging.RabbitMq | Consumers |
| `RabbitMqTopology`, `RabbitMqExchange`, `RabbitMqQueue`, `RabbitMqBinding`, `IRabbitMqTopologyDeclarer` | EF.Messaging.RabbitMq | Topology declaration |
| `RabbitMqOptions`, `RabbitMqConsumerOptions` | EF.Messaging.RabbitMq | Connection and consumer options |
| `AddRabbitMqMessaging(config, "Messaging:RabbitMq")`, `AddRabbitMqConsumer<THandler>(...)`, `AddRabbitMqTopology(...)`, `AddRabbitMqHealthCheck(...)` | EF.Messaging.RabbitMq | Registration |

### Azure Storage (EF.Storage)

Add when the app needs Blob Storage access. Do not hand-roll blob logic - extend `BlobRepositoryBase`.

| Type | Package | Used For |
|---|---|---|
| `IBlobRepository` | EF.Storage | Blob-specific contract: container create/delete, blob paging and streaming lists, SAS URI generation, `UploadBlobStreamAsync`, `StartDownloadBlobStreamAsync`, `DeleteBlobAsync` (container and SAS URI overloads) |
| `BlobRepositoryBase` | EF.Storage | Abstract blob repository implementing `IBlobRepository` and `IObjectStorageRepository`; also `DistributedLockExecuteAsync` (blob lease). Extend with a project-specific class |
| `BlobRepositorySettingsBase` | EF.Storage | Settings base (requires `BlobServiceClientName`) |
| `ContainerInfo` | EF.Storage | Container configuration model |
| `ContainerPublicAccessType` | EF.Storage | Enum for container access level |

**Constructor constraint:** `BlobRepositoryBase(ILogger<BlobRepositoryBase>, IOptions<BlobRepositorySettingsBase>, IAzureClientFactory<BlobServiceClient>)` - the settings parameter uses the base type. Register via `services.Configure<BlobRepositorySettingsBase>(...)` or use covariant DI binding.

All members are implemented and non-virtual; a project repository derives only to bind its settings and add app-specific methods ([../skills/azure-blob-storage.md](../skills/azure-blob-storage.md) -> *Project Repository Wrapper*).

### Object Storage (EF.Storage.Contracts, EF.Storage.S3)

Provider-neutral object storage. `BlobRepositoryBase` (Azure) and `S3ObjectStorageRepositoryBase` (S3-compatible, MinIO or AWS) both implement the contract, so application code depends on `IObjectStorageRepository` only.

| Type | Package | Used For |
|---|---|---|
| `IObjectStorageRepository` | EF.Storage.Contracts | `UploadAsync(containerName, objectName, content, contentType, metadata, ct)`, `DownloadAsync`, `DeleteAsync`, `ExistsAsync`, `GetPresignedUrlAsync`, `ListAsync` |
| `ObjectStorageItem`, `ObjectStoragePage`, `ObjectStoragePermissions` | EF.Storage.Contracts | List results and presigned-URL permissions |
| `S3ObjectStorageRepositoryBase` / `S3ObjectStorageRepository` | EF.Storage.S3 | S3 implementation |
| `S3StorageSettings` (section `Storage:S3`), `IS3BucketProvisioner`, `AddS3ObjectStorage(settings)` | EF.Storage.S3 | Settings, bucket provisioning, registration |

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
| `ClientErrorInterceptor` / `ServiceErrorInterceptor` / `ErrorInterceptorSettings` | EF.Grpc | Consistent gRPC error handling on client and server |
| `AddGrpcClient2<TClient>(...)` | EF.Grpc | gRPC client registration with `AddStandardResilienceHandler` |

### AI (EF.AI)

Provider-agnostic chat and embeddings over Microsoft.Extensions.AI. Provider selection policy: [../skills/ai-integration.md](../skills/ai-integration.md).

| Type | Package | Used For |
|---|---|---|
| `AddEFChatClient()`, `AddEFChatClients()`, `AddEFChatClientFromAspire()`, `EFChatClientSettings`, `EFChatClientProvider` | EF.AI (`EF.AI.Chat`) | `IChatClient` registration; providers `Disabled`, `OpenAICompatible`, `GitHubModels`, `OpenAI`, `Foundry`, `AzureAIInference`, `OpenRouter`, `Ollama`, `VLlm` |
| `AddEFEmbeddingGenerator()`, `EFEmbeddingGeneratorSettings`, `EFEmbeddingGeneratorProvider` | EF.AI (`EF.AI.Embeddings`) | `IEmbeddingGenerator` registration |

### Microsoft Graph (EF.MSGraph)

Add when the app calls Microsoft Graph APIs.

| Type | Package | Used For |
|---|---|---|
| `IMSGraphServiceBase` / `MSGraphServiceBase` / `MSGraphServiceSettingsBase` | EF.MSGraph | Graph operations over an injected `GraphServiceClient` (no auth wiring) |
| `ExternalIdUserFlowService`, `GraphUserRequest` (`EF.MSGraph.Models`) | EF.MSGraph | External ID user-flow operations |

### Durable Audit (EF.Audit.Contracts, EF.Audit.Data, EF.Audit.AzureTable)

`AuditInterceptor` appends to every registered `IAuditLogRepository`; pick one backend. Both packaged backends key on the write clock, so the scaffold implements its sinks app-side ([../skills/data-persistence.md](../skills/data-persistence.md) section Audit Strategy).

| Type | Package | Used For |
|---|---|---|
| `IAuditLogRepository` (`AppendAsync`, `QueryAsync(AuditLogQuery, ct)`, `PurgeOlderThanAsync`) | EF.Audit.Contracts | Backend-neutral audit sink and query contract |
| `AuditRecord`, `AuditLogQuery`, `AuditLogPage`, `AuditLogSettingsBase`, `AuditSettings` | EF.Audit.Contracts | Query and settings models |
| `AuditDbContext`, `RelationalAuditLogRepository`, `RelationalAuditLogSettings`, `AddRelationalAuditLog()` | EF.Audit.Data | EF Core relational backend |
| `AzureTableAuditLogRepository`, `AzureTableAuditLogSettings`, `AddAzureTableAuditLog(configure)` | EF.Audit.AzureTable | Azure Table backend built on EF.Table |

### Other Packages

| Package | Types | Used For |
|---|---|---|
| EF.Utility.UI | `RefitCallHelperFull`, `RefitCallHelperSlim`, `ApiResult` / `ApiResult<T>`, `RefitExtensions`, `HttpClientBuilderExtensions` | Refit client call helpers for UI hosts |
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
| `IQueryClient` | EF.FlowEngine | Data query nodes (EF Core via `EF.FlowEngine.Clients.Sql`) |
| `IMessageClient` | EF.FlowEngine | Async messaging nodes (Service Bus via `EF.FlowEngine.Clients.ServiceBus`) |
| `IAgentClient` | EF.FlowEngine | AI/LLM agent invocation nodes (OpenAI via `EF.FlowEngine.Clients.OpenAI`) |
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
| `EF.FlowEngine.Clients.Sql` | EF Core client for `IQueryClient` |
| `EF.FlowEngine.Clients.ServiceBus` | Azure Service Bus client for `IMessageClient` |
| `EF.FlowEngine.Clients.OpenAI` | Azure OpenAI client for `IAgentClient` |
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
