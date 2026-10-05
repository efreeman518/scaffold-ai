# TaskFlow Proof Map

Use this file when you need to prove that an instruction, pattern, or scaffolded output already exists in the TaskFlow reference app.

**Local sibling clone preferred:** if `../scaffold-proof/` exists relative to the target project's parent, read TaskFlow files via the Read tool - paths in the proof table below are relative to the TaskFlow repo root, so prefix with `../scaffold-proof/`. Fall back to GitHub MCP only when the local clone is absent: <https://github.com/efreeman518/scaffold-proof>

Load this file on demand. Keep it out of the default phase context.

> **TaskFlow is a multi-tenant application.** It demonstrates tenant boundary validation, tenant query filters, tenant-scoped services, and global-admin bypass. When scaffolding a single-tenant app, the multi-tenant patterns shown in TaskFlow do not apply - see `// [MULTI-TENANT]` markers in the service template.

---

## How to Use It

1. Find the current phase or concern.
2. Jump to the matching TaskFlow area.
3. Verify structure, wiring, and naming there before inventing a new pattern.
4. Generate code for the target project. Reference-application consultation rules (when to consult, local clone vs MCP fallback, do-not-copy-wholesale) live in [reference-app.md](reference-app.md).

---

## Phase Proof Map

| Phase / Concern | TaskFlow area to inspect | What it proves |
|---|---|---|
| Phase 1 shared language | `.scaffold/UBIQUITOUS-LANGUAGE.md`, `.scaffold/DESIGN-DECISIONS.md`, `.scaffold/domain-specification.yaml` | Shared terminology, rejected synonyms, and decision dependencies are explicit before code generation. |
| Phase 4 contract scaffolding | `src/Domain/TaskFlow.Domain.Model`, `src/Application/TaskFlow.Application.Contracts`, `src/Application/TaskFlow.Application.Models`, `tests/Test.Support` | Entity shells, contracts, DTOs, builders, and test infrastructure exist before TDD starts. |
| Phase 5a domain model | `src/Domain/TaskFlow.Domain.Model`, `src/Domain/TaskFlow.Domain.Model/TaskItem/TaskItem.cs`, `tests/Test.Unit/Domain/TaskItemStatusTransitionTests.cs` | `Create()` / `Update()` patterns, value objects, aggregate shape, and invariants owned by the root (`TaskItem.TransitionStatus` returns a `DomainResult` failure for an invalid transition; there is no separate rules folder). |
| Phase 5a domain shared | `src/Domain/TaskFlow.Domain.Shared` | Shared enums, typed IDs, constants, and domain-event contracts; value objects live in `Domain.Model/ValueObjects`. |
| Phase 5a data persistence | `src/Infrastructure/TaskFlow.Infrastructure.Data`, `src/Infrastructure/TaskFlow.Infrastructure.Repositories`, `src/Infrastructure/TaskFlow.Infrastructure.Data/Provider/TaskFlowDbProvider.cs`, `tests/Test.Unit/Infrastructure/MigrationModelContractTests.cs`, `tests/Test.Architecture/MigrationBaselineArchitectureTests.cs`, `tests/Test.Integration/StablePaginationIntegrationTests.cs` | Dual DbContext split, one SQL Server/PostgreSQL provider branch, per-provider single-baseline migrations/model checks, repository split, save/query separation, deterministic cursor tie-breakers, and real-database page-through proof. |
| Phase 5b application layer | `src/Application/TaskFlow.Application.Services`, `src/Application/TaskFlow.Application.Mappers`, `src/Application/TaskFlow.Application.Cqrs/Features` | Service shape, result flow, mapper conventions, CQRS feature-folder handler shape, validator placement, `BuildResponse` helper, `ErrorConstants` usage, `nameof(Entity)`, `[LoggerMessage]` source-gen logging. TaskFlow shares models and mappers between service and CQRS as a demo compromise; stricter CQRS slices can consolidate feature-specific models and mappers under the feature. Multi-tenant: EF.Tenancy boundary validation, `PreventTenantChange` in Update, `ConcurrencyGuard.Require` before a mutation. `src/Application/TaskFlow.Application.Contracts/InvalidRequestException.cs` is the one app client-input exception the host maps to 400; `Concurrency/SaveFailure.cs` classifies save failures. |
| Phase 5b message handlers | `src/Application/TaskFlow.Application.MessageHandlers`, `src/Application/TaskFlow.Application.Contracts/Messaging/TaskFlowOutboxEventMapper.cs`, `src/Host/TaskFlow.Bootstrapper/Registration/RegisterServices.Database.cs` (`AddOutbox`, `AddInbox`), `tests/Test.Integration/InboxStoreTests.cs`, `tests/Test.Integration/OutboxClaimTests.cs`, `tests/Test.Unit/Infrastructure/OutboxStagingTests.cs` | Staging interceptor, inbox and outbox stores, dispatcher and transports are EF.Data.Outbox / EF.Messaging packages; the app owns the mapper, consumers and payloads. | Same-transaction outbox staging. Two-state inbox: an in-progress claim with a 60 s lease the holder renews every third of it, completed with the effect; a redelivery waits at most one lease plus margin on a live claim, then throws to retry, and takes over an expired one. Outbox: the claim takes the worker attempt ceiling, excludes exhausted rows, and parks unsettled final attempts; the worker settles each message on its own bounded token (delete sent, dead-letter permanent, release transient with backoff); rows carry the staging `traceparent` so the consumer continues the request trace. |
| Phase 5b storage / external infrastructure | `src/Infrastructure/TaskFlow.Infrastructure.Storage`, `src/Host/TaskFlow.Bootstrapper/Registration/RegisterServices.DataProtection.cs`, `tests/Test.Integration/DataProtectionAzureBlobTests.cs` | Blob, Service Bus, and Cosmos repositories with no-op stubs for unconfigured states. Data Protection registration accepts an explicit key-file URL or derives one from the selected Blob connection/endpoint, keeps encryption independent, and has real-Blob proof for the Azure persistence arm. |
| Phase 5b API endpoints | `src/Host/TaskFlow.Api`, `tests/Test.Endpoints/GlobalExceptionHandlerTests.cs`, `tests/Test.Endpoints/ConcurrencyEndpointTests.cs` | Minimal API grouping, endpoint conventions, registration flow, If-Match/ETag concurrency, and EF.AspNetCore `AddEfProblemDetails` exception mapping: 499 only for a caller abort, 504 for a timeout-caused cancellation, 500 otherwise; only the app's `InvalidRequestException` and the other listed app types are 400; no exception text on 5xx outside Development. |
| Phase 5b runtime wiring | `src/Host/TaskFlow.Api/WebApplicationBuilderExtensions.cs`, `src/Host/TaskFlow.Bootstrapper`, `src/Host/TaskFlow.Bootstrapper/Registration/RegisterServices.RequestContext.cs`, `tests/Test.Unit/Hosting/SystemRequestContextTests.cs`, `tests/Test.Endpoints/TenantRateLimitEndpointTests.cs`, `src/Host/Aspire/AppHost`, `src/Shared/TaskFlow.Hosting/HostingLane.cs`, `src/Host/TaskFlow.Bootstrapper/Registration/ProviderSwitchAttribute.cs`, `src/Host/TaskFlow.Bootstrapper/StartupTasks/EnsureExternalResources.cs`, `tests/Test.Unit/Hosting/HostingLaneContractTests.cs` | Middleware order (`UseRateLimiter` after `UseAuthorization` so tenant budgets partition on the `tenant_id` claim), request context (authenticated claims, scaffold identity for unauthenticated HTTP, and an explicit tenantless system identity outside HTTP), NonAzure as the default lane, exact strict Azure/NonAzure profiles, same-lane opt-ins, cross-lane and Azure-service rejection from configuration/environment, safe search/AI defaults, one-release Portable and Relational aliases, one-time external resource provisioning, AppHost resources, runtime config, and lane-owned deployment shape. |
| Phase 5b Aspire service defaults | `src/Host/Aspire/ServiceDefaults`, `tests/Test.Unit/Hosting/OpenTelemetryMetricsRegistrationTests.cs` | OpenTelemetry log/trace export independent of the conditional metrics provider, `/healthz/live`, `/healthz/ready`, and `/healthz` contracts, shared host registration. |
| Phase 5b database migrator | `src/Host/TaskFlow.DatabaseMigrator`, `src/Infrastructure/TaskFlow.Infrastructure.Data/TaskFlowTickerQDbContext.cs`, `infra/modules/container-app-job.bicep`, `.github/workflows/deploy.yml`, `tests/Test.Unit/Infrastructure/MigrationModelContractTests.cs` | Sole migration owner: ordered `AddEfCoreMigrationTarget` registrations, migrator-only timeouts, per-context history tables, app-owned third-party (TickerQ) migration context, AppHost `WaitForCompletion`, one-shot Container Apps Job gating runtime rollout, and non-destructive pending-model checks for every TaskFlow DbContext. |
| Phase 5b gateway | `src/Host/TaskFlow.Gateway`, `tests/Test.Unit/Gateway/GatewayReverseProxyHardeningTests.cs`, `tests/Test.Unit/Gateway/GatewayAccessTokenCacheTests.cs`, `tests/Test.Endpoints/ForwardedClaimsRelayTests.cs` | YARP routing over EF.Gateway `AddDownstreamAuthTransforms`, EF.Auth `AccessTokenCache` token acquisition on no caller's token, claims relay honored only for an app-only gateway token (no `scp`) and rebuilt as a new user-only principal, CORS, one trusted forwarded hop, active/passive destination health, activity timeout, and validated edge rate-limit settings. |
| Phase 5b caching | API + Bootstrapper + cache registrations | FusionCache + Redis backplane patterns and cache-key conventions. |
| Multitenancy | Request context handling in API + service layer | Tenant extraction (EF.AspNetCore `AddHttpRequestContext`), EF.Tenancy boundary validation and its security logging, cross-tenant role bypass, the fail-closed tenant filter with the all-tenants rule, `PreventTenantChange`, `EntityDtoRules` delegation. |
| Phase 5c scheduler | `src/Host/TaskFlow.Scheduler`, `src/Host/TaskFlow.Scheduler/Jobs/TaskMaintenanceJobs.cs`, `src/Infrastructure/TaskFlow.Infrastructure.Data/Operational/BlobDeleteWork.cs`, `tests/Test.Integration/SchedulerJobIntegrationTests.cs`, `tests/Test.Integration/SchedulerCronSeedingTests.cs`, `tests/Test.Unit/Hosting/SchedulerHealthCheckTests.cs` | Cron declared on `[TickerFunction]` and seeded by TickerQ at start (no manual `AddAsync`, no duplicate per restart), staggered retention sweeps, real idempotent jobs, bounded workers, lease-based operational work, a health check that fails when the last execution is older than twice the shortest interval, App Configuration refresh in a host without requests, and fixed-`TimeProvider` recurrence proof. |
| Phase 5c functions | `src/Host/TaskFlow.Functions`, `src/Host/TaskFlow.Functions/HttpContextAccessorMiddleware.cs` | Function-project structure, trigger layout, placeholder-host patterns, and HTTP-trigger `HttpContext` publication so only non-HTTP triggers get the system request context. |
| Phase 5c Uno UI | `src/UI/TaskFlow.Uno` | UI project structure, feature grouping, and gateway-backed client flow. |
| Phase 5c Uno core | `src/UI/TaskFlow.Uno.Core/Client/TaskFlowApiJsonContext.cs`, `src/UI/TaskFlow.Uno.Core/Client/TaskFlowApiClient.cs`, `tests/Test.UI/Uno/TaskFlowApiJsonContextTests.cs` | Plain single-TFM client library with source-generated JSON metadata for every concrete HTTP payload and a reflection-disabled inventory contract. |
| Phase 5c Blazor host | `src/UI/TaskFlow.Blazor` | Blazor alternative to Uno UI; same Gateway-backed client flow. |
| Phase 5c React UI | `src/UI/TaskFlow.React` | React + TypeScript Vite SPA alternative; same Gateway-backed client flow, Vite proxy/Aspire JavaScript host wiring, dark-mode persistence, and full workflow parity. |
| Phase 4 Test infrastructure | `tests/Test.Support/WebApplicationFactoryBase.cs`, `tests/Test.Support/TestOutbox.cs`, `tests/Test.Endpoints/CustomApiFactory.cs`, `tests/Test.E2E/DbApiFactory.cs`, `tests/Test.Integration/Infrastructure/DbContainerFixture.cs` + `RabbitMqBrokerFixture.cs` + `SeaweedFsContainerFixture.cs` (`Azure` lane: `AzuriteContainerFixture.cs`) + `IntegrationTestSetup.cs`, `tests/Test.Aspire/AspireTestHost.cs` + `AspireMeshLifecycle.cs` | Shared WAF base constrained to `DbContextBase<string, Guid?>`; thin derived factories per harness; EF.Testing `DockerRuntimePreflight` shared by component and Aspire-backed tiers; component store fixtures remain standalone; the EF.IntegrationTesting.Aspire `AspireTestHostContext` deadline/wait/diagnostics/cleanup policy is consumed by lazy mesh and browser/WASM adapters. |
| Phase 5a integration tier | `tests/Test.Integration/MigrationAndRepositoryTests.cs` | EF migrations apply against real SQL; CRUD + child includes + M:N junction navigation + tenant query filter + polymorphic-attachment index checks against the migrated schema. |
| Phase 5b component tier | `tests/Test.Integration/RelationalAuditLogRepositoryTests.cs`, `tests/Test.Integration/DomainEventPipelineTests.cs` | Relational audit sink against the lane's standalone database Testcontainer (tenant-first key, no-tenant sentinel, batched retention sweep) over the EF.Audit.Data sink; the EF.Audit.AzureTable sink holds the `Azure` Table arm to the same contract. The projection pipeline reads through query-side repos and emits view documents against the same standalone database. |
| Phase 5b mesh tier | `tests/Test.Aspire/OutboxMeshTests.cs`, `tests/Test.Aspire/AppSurfaceAspireTests.cs` | Against the lazily-started Aspire AppHost graph (`AspireTestHost.EnsureStartedAsync`): HTTP create -> outbox row -> Scheduler dispatch -> broker (RabbitMQ by default) -> consumer inbox rows, with replay adding nothing and non-envelope bodies dead-lettered; Gateway -> API proxy hop. `ApiAuditPipelineTests` / `FunctionAuditPipelineTests` cover the `Azure` lane's Azurite audit read-back. |
| Phase 5b E2E tier | `tests/Test.E2E/DbApiFactory.cs`, `tests/Test.E2E/TaskItemCrudE2ETests.cs` | Static Testcontainers database lifecycle (PostgreSQL on the default `NonAzure` lane, SQL Server on `Azure`; `TASKFLOW_LANE` read through `TestHostingLane`) on the derived `DbApiFactory`; multi-endpoint workflows (CRUD round-trip, paged search across distinct pages, child-aggregate lifecycles) against a real database. |
| Mapper parity (consolidated) | `tests/Test.Unit/Mappers/MapperProjectionParityTests.cs` | Single class pinning compile-projection / `ToDto` agreement for every mapper + inlined-child parity for aggregate roots + owned-type flattening parity. |
| Phase 5d quality (.NET test projects) | `tests/Test.Unit`, `tests/Test.Integration`, `tests/Test.Aspire`, `tests/Test.Endpoints`, `tests/Test.E2E`, `tests/Test.Architecture`, `tests/Test.Load`, `tests/Test.Benchmarks`, `tests/Test.Mutation`, `tests/Test.Support`, `tests/Test.Load/TaskItemLoadTests.cs` | `dotnet test`-runnable test project layout, EF.Testing open-model `LoadRunner` scenarios, Stryker.NET mutation samples, and quality-gate coverage. |
| Phase 5d browser UI tests | `tests/Test.PlaywrightUI/PlaywrightAspireHost.cs`, `WasmAppHost.cs`, `WasmHostContractTests.cs`, `TypeScriptPlaywrightSuiteTests.cs`, `src/Host/TaskFlow.Uno.WasmHost` | C# MSTest adapter self-hosts Aspire, resolves dynamic resource URLs, shares one host lifecycle, waits on observable responses, and permits one DCP retry only for the exact all-`FailedToStart`, no-process, no-exit-code pre-launch state. It publishes Uno Release output from a clean target, validates staged assets and MIME types, distinguishes asset 404s from SPA routes, and runs browser projects under one startup budget. |
| Phase 5d deployment and rollback | `.github/workflows/deploy.yml`, `.github/workflows/deploy-vps.yml`, `deploy/compose/docker-compose.yml`, `infra/scripts/Test-ReleaseManifest.ps1`, `infra/scripts/Invoke-DeploymentSmoke.ps1`, `tests/Test.Unit/Infrastructure/DeploymentWorkflowContractTests.cs`, deployment Dockerfiles | Azure-owned Container Apps/Bicep and NonAzure-owned Compose lanes, validated green SHA, build-once immutable release manifests, digest-pinned images, artifact-backed deploy/rollback without rebuild, database-first and public readiness, ETag-aware CRUD smoke cleanup, queued deployments, BuildKit-only package credentials, and non-root chiseled runtime images. Deployed NonAzure also proves persistent OpenObserve configuration, least-privilege ingestion credentials, positive retention guards, and symmetric bounded health plus authenticated OTLP log/trace smoke in deploy and rollback workflows. The PostgreSQL volume mount root is not migration proof for an existing named volume. Compose owner: [compose-deployment.md](compose-deployment.md). |
| Phase 5d mobile UI tests | `tests/Test.Mobile`, `tests/Test.Mobile/run-mobile-tests.ps1`, `tests/Test.Mobile/MobileTestHost.cs`, `tests/TaskFlow.runsettings`, `src/UI/TaskFlow.Uno/TaskFlow.Uno.csproj` | MSTest + Appium Android smoke tests remain opt-in for ordinary CLI runs. The explicit runner owns SDK/device preflight and the full lane. The selected run-settings profile serializes UI hosts, enables mobile, resolves paths from repo root, builds the default Android package when absent, and owns loopback Appium startup/cleanup; 3 Android tests and the 8-test browser suite passed through CLI `--settings`. Visual Studio Test Explorer was not independently evidenced, and two 180-second method timeouts remain shorter than the 240-second startup allowance, so cold-start timeout acceptance is unresolved. |
| Phase 5e auth | `AuthConfiguration`, `src/Application/TaskFlow.Application.Contracts/ScaffoldPrincipal.cs` (EF.Auth `AddFixedPrincipal`), `tests/Test.Endpoints/ForwardedClaimsRelayTests.cs` | Scaffold fixed principal, Entra-ready wiring, and the EF.Auth claims relay. |
| Phase 5e AI | `src/Infrastructure/TaskFlow.Infrastructure.AI`, `src/Host/TaskFlow.Bootstrapper/Registration/RegisterServices.AiChatClient.cs`, `tests/Test.Aspire/AiFoundryLiveSmokeTests.cs`, `tests/Test.Aspire/AspireAiProviderSelectionTests.cs`, `tests/Test.Unit/AI/AiProviderSelectorTests.cs`, `tests/Test.Unit/AI/AiServiceRegistrationTests.cs` | Structural evidence for Azure Foundry, OpenAI-compatible, and no-op selection, `/api/v1/ai/status`, Azure HTTP mesh smoke, and no-op fallback. The AppHost still infers Azure Foundry from raw endpoint, deployment, or connection settings while runtime DI keeps explicit `Provider=None`, so this is not runnable proof until every surface uses explicit provider selection as the sole activation source. |

### Uno MVUX Presentation (proven)

MVUX presentation records live in the testable `src/UI/TaskFlow.Uno.Presentation/Presentation` library, separate from the `Uno.Sdk` head. Inspect that library to verify the shape:

- Every MVUX record sits in the one `TaskFlow.Uno.Presentation` assembly (avoids duplicate generated `BindableXxx` wrapper types); Kiota/client code stays in `TaskFlow.Uno.Core`; `Uno.Sdk` is only on `TaskFlow.Uno`.
- Static `App.*` model calls are replaced by injected abstractions such as `IAppShellActions` and `IThemePreferenceService`.
- Presentation tests live in `tests/Test.UI/Presentation` (see [../templates/test-templates-presentation.md](../templates/test-templates-presentation.md)).

---

## Direct Proof Links

Use these links first. If a branch or path has moved, search inside the same repository for the path suffix or type name; do not invent a new pattern.

| Concern | Direct link |
|---|---|
| Ubiquitous language | <https://github.com/efreeman518/scaffold-proof/blob/main/.scaffold/UBIQUITOUS-LANGUAGE.md> |
| Design decisions | <https://github.com/efreeman518/scaffold-proof/blob/main/.scaffold/DESIGN-DECISIONS.md> |
| Domain model | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Domain/TaskFlow.Domain.Model> |
| Domain shared | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Domain/TaskFlow.Domain.Shared> |
| Application contracts | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Application/TaskFlow.Application.Contracts> |
| Application models | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Application/TaskFlow.Application.Models> |
| Application services | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Application/TaskFlow.Application.Services> |
| Application mappers | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Application/TaskFlow.Application.Mappers> |
| Application CQRS features | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Application/TaskFlow.Application.Cqrs/Features> |
| Application message handlers | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Application/TaskFlow.Application.MessageHandlers> |
| Data infrastructure | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Infrastructure/TaskFlow.Infrastructure.Data> |
| Database migrator host | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Host/TaskFlow.DatabaseMigrator> |
| Repositories | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Infrastructure/TaskFlow.Infrastructure.Repositories> |
| Storage / external infrastructure | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Infrastructure/TaskFlow.Infrastructure.Storage> |
| AI infrastructure | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Infrastructure/TaskFlow.Infrastructure.AI> |
| API host | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Host/TaskFlow.Api> |
| Bootstrapper | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Host/TaskFlow.Bootstrapper> |
| Aspire AppHost | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Host/Aspire/AppHost> |
| Aspire service defaults | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Host/Aspire/ServiceDefaults> |
| Gateway | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Host/TaskFlow.Gateway> |
| Scheduler | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Host/TaskFlow.Scheduler> |
| Functions | <https://github.com/efreeman518/scaffold-proof/tree/main/src/Host/TaskFlow.Functions> |
| Uno UI | <https://github.com/efreeman518/scaffold-proof/tree/main/src/UI/TaskFlow.Uno> |
| Uno core (testable) | <https://github.com/efreeman518/scaffold-proof/tree/main/src/UI/TaskFlow.Uno.Core> |
| Blazor host | <https://github.com/efreeman518/scaffold-proof/tree/main/src/UI/TaskFlow.Blazor> |
| React UI | <https://github.com/efreeman518/scaffold-proof/tree/main/src/UI/TaskFlow.React> |
| Test support | <https://github.com/efreeman518/scaffold-proof/tree/main/tests/Test.Support> |
| Unit tests | <https://github.com/efreeman518/scaffold-proof/tree/main/tests/Test.Unit> |
| Architecture tests | <https://github.com/efreeman518/scaffold-proof/tree/main/tests/Test.Architecture> |
| Endpoint tests | <https://github.com/efreeman518/scaffold-proof/tree/main/tests/Test.Endpoints> |
| E2E tests | <https://github.com/efreeman518/scaffold-proof/tree/main/tests/Test.E2E> |
| Playwright UI tests (TaskFlow uses Node; scaffold may use Node or C# MSTest) | <https://github.com/efreeman518/scaffold-proof/tree/main/tests/Test.PlaywrightUI> |
| Mobile UI tests (MSTest + Appium) | <https://github.com/efreeman518/scaffold-proof/tree/main/tests/Test.Mobile> |

---

## High-Value Proof Checks

- **Current reference status:** authoritative counts, dates, capability classifications, and scaffold-compatibility evidence live only in the reference app's `.scaffold/REFERENCE-STATUS.md` (<https://github.com/efreeman518/scaffold-proof/blob/main/.scaffold/REFERENCE-STATUS.md>) - not restated here.

- **Multi-tenant proof:** TaskFlow demonstrates full multi-tenancy - `ITenantEntity<TenantId>` (typed domain ID), EF.Tenancy `ITenantBoundaryValidator`, the fail-closed tenant query filter (`tests/Test.Unit/Hosting/AllTenantsScopeTests.cs`), tenant stamping, and cross-tenant role bypass. Not all scaffolds require multi-tenancy.
- **Service pattern proof:** TaskFlow services use `BuildResponse` helper, `ErrorConstants.ERROR_ITEM_NOTFOUND`, `nameof(Entity)`, `[LoggerMessage]` source-gen logging, and `DefaultRequest<T>`/`DefaultResponse<T>` as `record` types.
- **Dual DbContext proof:** TaskFlow uses `TaskFlowDbContextTrxn` for writes and `TaskFlowDbContextQuery` for read-only/no-tracking access.
- **Repository proof:** TaskFlow splits repository contracts and implementations into transaction and query variants.
- **Middleware proof:** `src/Host/TaskFlow.Api/WebApplicationBuilderExtensions.cs` orders the API pipeline as forwarded headers -> security headers -> correlation ID -> exception handling -> CORS -> authentication (gateway claims relay runs as `IClaimsTransformation`) -> authorization -> rate limiting -> request timeouts -> endpoints.
- **Gateway proof:** The gateway calls the API with its own app-only token and relays the original user claims in an encoded header; the API honors the header only for that token.
- **Scheduler proof:** TickerQ cron jobs are declared on `[TickerFunction]` methods in one jobs class, not hidden inside hosted services or seeded by hand.
- **Deliberate CI divergence:** TaskFlow's CI runs no `dotnet format analyzers` step. The build step is the analyzer gate: `TreatWarningsAsErrors` fails it on any warning-severity diagnostic. The generation-time info-severity pass ([execution-gates.md](execution-gates.md) section Analyzer-Cleanliness Gate) is the only reason for a separate format pass, so a consuming repo's CI does not add one.
- **Scaffold-auth proof:** Local/dev completion does not require live cloud auth; scaffold auth supplies trusted claims until Phase 5e finalizes identity.

## Scalability and Hosting Proof

- **Provider and lane selectors:** `src/Shared/TaskFlow.Hosting/HostingLane.cs` owns the shared strict resolver. `tests/Test.Unit/Hosting/HostingLaneContractTests.cs` proves exact defaults, same-lane opt-ins, cross-lane rejection, zero-Azure NonAzure settings, and diagnostics. `tests/Test.Architecture/ProviderSwitchArchitectureTests.cs` proves default-arm DI resolution and cloud-SDK boundaries. `tests/Test.Aspire/AppHostLaneTopologyTests.cs` proves lane precedence, the deprecated Portable alias, PostgreSQL JSONB and MongoDB read-model arms, host environment, and Azure/NonAzure topology without requiring a running DCP graph.
- **Runtime profiles:** `src/Host/TaskFlow.Host.props` and `tests/Test.Architecture/HostRuntimeSettingsTests.cs` prove per-host GC/ReadyToRun/globalization decisions, including the SQLClient/ICU boundary.
- **Serialization:** `tests/Test.Architecture/JsonContextCompletenessTests.cs` pins source-generated metadata completeness. `tests/Test.Integration/ScaleFixtureExportTests.cs` proves resumable bounded-memory export behavior.
- **Health:** `tests/Test.Endpoints/HealthProbeContractTests.cs` proves `/healthz/live`, `/healthz/ready`, and `/healthz` semantics.
- **Problem correlation:** EF.AspNetCore `AddEfProblemDetails` and `tests/Test.Endpoints/GlobalExceptionHandlerTests.cs` prove distinct HTTP `requestId` and W3C `traceId`/`spanId` fields across error responses.
- **Telemetry signal gating:** `src/Host/Aspire/ServiceDefaults/Extensions.cs` and `tests/Test.Unit/Hosting/OpenTelemetryMetricsRegistrationTests.cs` prove metrics may be disabled without dropping logs, traces, OTLP, or signal-specific Azure Monitor exporters.
- **Broker trace continuity:** EF.Messaging and `tests/Test.Unit/Infrastructure/BrokerTracePropagationTests.cs` prove W3C producer-to-consumer parenting.
- **Read hedging:** EF.Http.Resilience `AddReadHedging` owns the standard hedging handler (a request clone per attempt) and the GET/HEAD-only guards; the package tests prove them.
- **NonAzure deployment:** `deploy/compose/docker-compose.yml`, `.github/workflows/deploy-vps.yml`, and `tests/Test.Unit/Infrastructure/DeploymentWorkflowContractTests.cs` prove configuration and workflow contracts for persistent OpenObserve, consumer-scoped ingestion credentials, retention, health, and authenticated OTLP log/trace smoke in both deploy and rollback paths. This remains `deployment-only`; contract tests and Compose rendering are not evidence that a live VPS, OpenObserve instance, or full Compose mesh completed successfully.

---

## When To Load This File

- A skill or template describes a pattern but the concrete shape is still ambiguous.
- You need to verify that the instruction set already has a working example.
- You want a fast pointer into TaskFlow without searching the whole repo.

## Application Style Proof

TaskFlow now proves both application styles:

- Service endpoints: existing `I{Entity}Service` route mapping.
- CQRS endpoints: equivalent routes mapped directly to command/query handlers.
- Shared contracts: Domain, Infrastructure, UI clients, DTOs, and route contracts remain stable.
- Route versioning: public domain API routes are `/api/v1/*`; operational/admin/health surfaces stay unversioned (`/health/*`, `/alive`, `/healthz`, `/api/flowengine/*`, Functions host health `/api/health`).
- Guardrails: avoid central request dispatchers, request buses, and generic `Send()` entrypoints; no CQRS-specific repository layer.
- Reason: endpoint -> request -> handler wiring stays explicit and can be checked by tests/code review.
