# Package Dependencies (Shared Base Types)

> **When to read:** Phase 3, and any time you add, upgrade, or resolve a package - the `packageStrategy` layout, the shared `EF.*` base-type contracts, version resolution (`Latest, Not Pinned`), and feed/central-management wiring.
> **Skip if:** the package set is already resolved and the task adds no dependency; pure domain, endpoint, or UI logic against types already referenced.

Use this file as a compact contract map for shared base-type packages/projects. The contracts described here are sourced one of three ways depending on `packageStrategy` (set in `.scaffold/resource-implementation.yaml`):

| `packageStrategy` | How layers are consumed |
|---|---|
| `feed` | All base contracts come from a private NuGet feed (e.g., `EF.*` from GitHub Packages). Project files use `<PackageReference Include="<packagePrefix>.<Layer>">`. |
| `local` | All base contracts are generated as packable projects under `src/Packages/<packagePrefix>.*` and consumed via `<ProjectReference>`. No private feed configured. |
| `hybrid` | Feed-supplied layers use `<PackageReference>`; layers listed in `localPackageLayers` use `<ProjectReference>` against `src/Packages/<packagePrefix>.<Layer>`. Same prefix in both cases. |

`EF` is the canonical example prefix used throughout these instructions, not a hard-coded default. Substitute your `packagePrefix` everywhere `EF.*` appears below.

## Sources

- Reference implementation (core): <https://github.com/efreeman518/EF.Packages>
- Reference implementation (enterprise): <https://github.com/efreeman518/EF.Packages.Enterprise>
- See [../patterns/expected-output-index.md](../patterns/expected-output-index.md).

These two repos define the canonical contract surface for all modes. In `local` or `hybrid` mode, the locally-generated `src/Packages/<packagePrefix>.*` projects must match the contracts in [`../support/ef-packages-reference.md`](../support/ef-packages-reference.md) (derived from these repos).

> **AI lookup rule:** This file provides a compact contract map. When you need full API signatures, constructor parameters, or method overloads for any base type (e.g., `TableRepositoryBase`, `IBlobRepository`, `ICosmosDbRepository`, `IKeyVaultManager`), use the GitHub MCP server to read the source from [EF.Packages](https://github.com/efreeman518/EF.Packages) or [EF.Packages.Enterprise](https://github.com/efreeman518/EF.Packages.Enterprise) - they remain the canonical contract definition regardless of consumption mode.

## Latest, Not Pinned (Global Rule)

**All SDKs, packages, and components default to latest stable.** Never pin a specific version in instruction examples or templates. Resolve the latest stable version at scaffold time and write that into `Directory.Packages.props` / `global.json` / `Sdk="...@<version>"`.

In instruction docs:

- Use the `<latest-stable>` placeholder in xml/json snippets (e.g., `Sdk="Aspire.AppHost.Sdk/<latest-stable>"`, `<TargetFramework>$(LatestStableTfm)</TargetFramework>`).
- Do **not** write a hard-coded `Version="<copied-version>"` or target framework into a template - it goes stale silently and contradicts this rule on every PR diff.
- Do **not** cite dependency versions in prose either. Describe current behavior as present truth - the baseline tracks latest, so the current API is the only one that matters.
- Do **not** add version-history or backwards-compat framing ("resolved in X", "pre-X bug", "obsolete in X", "verified <date>", "regression guard for the old behavior"). State what the API does now; drop how it got there. ("Legacy" is fine only when it names a non-version concept - the `.sln` format, the `datetime` SQL type - never a package version.)

**Temporary documented exceptions only.** A version below latest stable is permitted only for a specific issue. Record four items beside the pin: issue or failing behavior, reason the selected version resolves it, removal condition, and validating test. Any pin without all four is a bug - replace it with the latest stable release. Vulnerable transitives get the commented direct-pin lift - canonical pattern in [../support/execution-gates.md](../support/execution-gates.md) section Vulnerable Transitive Lift.

SDK upgrade discipline:

- Resolve the latest stable SDK during generation and consult the vendor's current official upgrade guide when its API or project shape changed.
- Do not hold a prior major by policy. If the latest stable SDK is temporarily blocked, use the four-part exception record above and keep the validating test in CI until removal.
- Treat tightly coupled runtime/tooling families as one refresh unit. For EF Core, keep the runtime/provider packages, `Microsoft.EntityFrameworkCore.Design`, `Microsoft.EntityFrameworkCore.Tools` when referenced, and repo-local `dotnet-ef` on one compatible patch. A green application build does not prove the design-time tool graph.
- Refresh every referenced `Testcontainers.*` package together and compile each consuming test project. Do not infer that unrelated package families share a version: package names under one feature, such as FusionCache core and provider integrations, may legitimately resolve at different versions. Update nearby rationale when the supported package combination changes.
- After a toolchain refresh, run `dotnet tool restore`, compile the affected solution and workload-specific projects, and run the transitive vulnerability audit. Search adjacent comments, generated-client plans, examples, and version rationale for stale copied values before declaring the refresh complete.

Package adoption and replacement discipline:

- Prove a published member from the package reference before deleting an app-local implementation. A shadow copy can make restore/build pass without proving the package supplies the contract.
- When a package supersedes local code, remove the duplicate and update design decisions, resource manifests, terminology, tests, generated clients, and proof maps in the same change.
- Treat an upgrade as a wire-contract change when it touches serialized members, cursors/tokens, persisted envelopes, generated clients, or provider-translated expressions. Keep literal previous-version payload/token tests where compatibility matters, regenerate affected clients, and exercise the real provider rather than only LINQ-to-Objects.
- A shipped member may be rejected when it is not correct for the app. Record the concrete defect, retained implementation, package acceptance criteria, and removal condition instead of wrapping or silently forking both paths.

## Minimize Third-Party Dependencies (Mandatory)

**Default: do not add a new third-party package.** Prefer the BCL, `Microsoft.Extensions.*`, ASP.NET Core built-ins, and the reference-app stack already wired in TaskFlow. If a recurring pattern is missing, write a small extension method in the appropriate layer instead of pulling in a library.

### Pre-approved third-party packages

These are already part of the reference app and may be added without developer discussion when the pattern requires them. Use the canonical wiring from the reference app - do not re-evaluate the choice each time:

| Package family | Purpose | Skill |
|---|---|---|
| `Yarp.ReverseProxy` | API gateway / reverse proxy | [gateway.md](gateway.md) |
| `Scalar.AspNetCore` | OpenAPI UI | [api.md](api.md) |
| `ZiggyCreatures.FusionCache.*` | Hybrid cache + Redis backplane | [caching.md](caching.md) |
| `StackExchange.Redis` | Redis client (backplane / direct) | [caching.md](caching.md) |
| `Moq` | Test doubles | [testing.md](testing.md) |
| `Testcontainers.*` | Real-infra integration/E2E tests | [testing.md](testing.md) |
| `BenchmarkDotNet` | Microbenchmarks | [testing.md](testing.md) |
| `dotnet-stryker` (local tool) | Mutation testing runner | [testing-quality.md](testing-quality.md) |
| `MudBlazor` | Blazor component library | [ui-blazor.md](ui-blazor.md) |
| `Refit` / `Refit.HttpClientFactory` | Typed HTTP clients | [external-api.md](external-api.md) |
| `Azure.*` (Identity, Storage, KeyVault, Cosmos, ServiceBus, EventGrid, EventHubs, AI) | Azure SDK | [azure-data-storage.md](azure-data-storage.md), [security.md](security.md), [messaging.md](messaging.md), [ai-integration.md](ai-integration.md) |
| `Aspire.*` (Hosting + client integrations like `Aspire.Azure.AI.Inference` + `Aspire.Hosting.Testing`) | Orchestration + integration tests | [bootstrapper.md](bootstrapper.md), [aspire.md](aspire.md), [testing.md](testing.md) |
| `Microsoft.Extensions.AI` / `Microsoft.Agents.AI` (+ `.OpenAI`) | `IChatClient` + Microsoft Agent Framework agents | [ai-integration.md](ai-integration.md) |

Add only the specific sub-package needed (e.g., `Azure.Storage.Blobs`, not the entire SDK). Versions stay in `Directory.Packages.props` per the Latest, Not Pinned rule. Consuming a Foundry **project** or **server-hosted/pre-existing agent** from app code adds `Azure.AI.Projects` + `Microsoft.Agents.AI.Foundry` (the `AIProjectClient.AsAIAgent(...)` path). `Aspire.Hosting.Foundry`, `Aspire.Azure.AI.Inference`, and `Microsoft.Agents.AI.Foundry` are preview-only (no stable release); pin them with a one-line inline reason - the documented version-pinning exception.

### Any other package - discuss first

Anything **not in the pre-approved table above** is not approved by default. The NuGet ecosystem is large; this section deliberately does not enumerate disallowed packages because the list would be endless and brittle. The rule is the opposite - **the pre-approved table is the allowlist**.

Before adding any other package, pause and discuss with the developer. The bar is "**high value** that the reference-app stack cannot deliver." Justification must answer:

1. What built-in (BCL / `Microsoft.Extensions.*` / ASP.NET Core) or reference-app pattern fails to cover this?
2. Why is a small in-house extension method insufficient?
3. What is the maintenance, license, and transitive-dependency cost?
4. Could equivalent behavior live as a thin extension package under `src/Packages/<packagePrefix>.<Layer>` (so it benefits other scaffolded apps) instead of as a third-party dependency?

**No paid licenses by default.** A package, tool, or framework whose license requires payment for organizational or commercial use - including a free package whose current major moved to a commercial license - is excluded unless it adds significant value **and** no free built-in, allowlisted, in-house, or OSI-licensed option covers the need. Check the license of the version you would actually resolve, not the one you remember. An approved exception records the license name, cost basis, what the free options lacked, and an exit path in `.scaffold/DESIGN-DECISIONS.md`. Known exclusions: FluentAssertions ([testing.md](testing.md) section Assertion Policy), commercial load-test packages (load tests use the EF.Testing `LoadRunner`, [test-templates-quality.md](../templates/test-templates-quality.md)), and MassTransit (use the EF.Data.Outbox outbox and the `IOutboxTransport` port, [messaging.md](messaging.md)).

If a candidate clears that bar, propose it explicitly to the developer with a one-paragraph rationale. Examples of common categories where teams reach for a package but the reference-app stack already covers the need: input validation, object mapping, assertion DSLs, alternate mocking frameworks, alternate JSON serializers. Default response in these categories: **write the extension or use what's already there.**

### Build a shared package instead (preferred path)

When a pattern recurs three or more times and no pre-approved package covers it cleanly, the answer is almost always **a small in-house extension**, not a NuGet dependency:

1. Add the helper to the appropriate layer - `EF.Common` (cross-cutting), `EF.Domain` (domain-pure), or a project-local `*Extensions.cs` for app-specific behavior. If the pattern is reusable across scaffolded apps, promote it to a packable project under `src/Packages/<packagePrefix>.<Layer>` so future apps inherit it via the standard package strategy.
2. Keep it minimal - one responsibility per extension method; no fluent builders that mimic a third-party DSL.
3. Cover it with a unit test that pins the contract.
4. Record the decision in `HANDOFF.md` so future sessions do not re-litigate the package-vs-extension trade-off.

The goal is a small, owned dependency surface - every package added is one the team commits to tracking for CVEs, license changes, and major-version breakage.

## Feed + Version Rules (Mandatory)

### When `packageStrategy: feed` or `hybrid` (feed-supplied layers only)

1. `nuget.config` must include `nuget.org` and all `customNugetFeeds` from [resource-implementation-schema.md](../ai/resource-implementation-schema.md).
2. **Both private feeds** must be declared when Enterprise packages (`<packagePrefix>.FlowEngine`, `<packagePrefix>.FilterBuilder`) are used - for the canonical `EF.*` example they ship from the same GitHub Packages org:
   - `https://nuget.pkg.github.com/efreeman518/index.json` (covers `EF.*` pattern for both Core and Enterprise)
3. Use central package versions in `Directory.Packages.props` for every feed-supplied `<packagePrefix>.<Layer>`.
4. After adding packages, restore and update to latest stable versions.
5. Re-verify with `dotnet restore` and `dotnet build`.
6. **Private feed auth:** GitHub Packages and other authenticated feeds require a PAT or token. Local dev stores credentials in `nuget.config` (user-level, not committed). CI/CD must pass credentials via environment variable or `dotnet nuget` auth step - see [cicd.md](cicd.md) for workflow setup. A 401 on restore means the feed credential is missing or expired. When the dev already has the feed configured with working credentials in the user-global `nuget.config`, author a secret-free repo `nuget.config` (source entry only, no `<packageSourceCredentials>`) so the project file does not shadow those global creds - see the probe-first Step 2 in [../support/operator-setup.md](../support/operator-setup.md) section Shared Base-Type Readiness.

### When `packageStrategy: local` or `hybrid` (locally-generated layers only)

1. No `nuget.config` private-feed entry is required for layers in `localPackageLayers`. `nuget.org` access is still mandatory, but the repo-root file may be absent when NuGet's default source is sufficient.
2. Each generated project under `src/Packages/<packagePrefix>.<Layer>/` sets `IsPackable=true`, `<PackageId>=<packagePrefix>.<Layer>`, and a developer-selected initial package version.
3. Application/domain/host projects consume locally-generated layers via `<ProjectReference Include="..\..\Packages\<packagePrefix>.<Layer>\<packagePrefix>.<Layer>.csproj" />` - no `<PackageVersion>` entry in `Directory.Packages.props`.
4. Transitive NuGet dependencies of the generated projects (e.g., `Microsoft.EntityFrameworkCore`) still go through `Directory.Packages.props` central versions.
5. To publish later: `dotnet pack src/Packages/<packagePrefix>.<Layer>` produces a `.nupkg` that can be pushed to any feed. After the layer is published and consumed via `<PackageReference>`, move the layer from `localPackageLayers` into the feed-supplied set and delete the local project. When a layer package is meant to own a type that was temporarily copied into a consuming project, reference the package directly, prove it with `dotnet restore` + `dotnet build`, then delete the local copy - a shadow copy masks whether the package actually provides the type.

If `applicationStyle` is `cqrs` or `switch`, include `CQRS` in `localPackageLayers` for `packageStrategy: local`/`hybrid`. The generated project is `src/Packages/<packagePrefix>.CQRS/<packagePrefix>.CQRS.csproj` and is referenced by `{Project}.Application.Cqrs` and CQRS-focused tests via `<ProjectReference>`.

### Vendored Native Assets and Package Content

Apply this only when an approved dependency has no maintained package for every deployment RID. Prefer an upstream multi-RID package first; compiling and vendoring native source creates patch, provenance, and ABI ownership.

1. Record the source repository, license, pinned tag/commit, checksum, supported RIDs, and rebuild owner in `.scaffold/DESIGN-DECISIONS.md`.
2. Build each native binary in a container whose OS/libc baseline matches the runtime image family. For example, a Noble chiseled runtime uses an Ubuntu 24.04-compatible glibc build environment. A binary built on a newer glibc may load locally and fail on the server.
3. Declare the supported build/publish RIDs (`<RuntimeIdentifiers>` or an equivalent CI matrix) and pack native binaries under `runtimes/<rid>/native/`, one asset per RID such as `win-x64` and `linux-x64`. Do not place a Windows DLL in a generic content folder and claim cross-platform support.
4. Keep P/Invoke behind one class. In its static constructor, call `NativeLibrary.SetDllImportResolver` when the managed import name must map to platform-specific filenames or packaged paths. Fail with the requested RID and attempted asset name when unsupported.
5. For non-code runtime data packaged through `contentFiles`, set `PackageCopyToOutput=true`. A plain `Content` item in the package project does not guarantee the file reaches a consuming app's build or publish output. Direct project content also sets `CopyToOutputDirectory`/`CopyToPublishDirectory` as applicable.
6. Pack, then restore the `.nupkg` into a clean consumer. Run `dotnet publish -r <rid>` for every supported RID, assert native and data files exist in publish output, and execute one minimal P/Invoke smoke inside the final runtime image. A successful compile alone does not prove native loadability.

> **CPM + floating versions = NU1011.** When `ManagePackageVersionsCentrally=true`, every `<PackageVersion>` entry must use an exact version (e.g. `Version="<latest-stable>"` resolved at scaffold time). Wildcard/floating versions (e.g. `1.0.*`, `*`) are prohibited and cause restore to fail with NU1011. To use floating versions, set `ManagePackageVersionsCentrally=false` and add `Version="*"` directly to each `<PackageReference>`. This rule applies regardless of `packageStrategy`.

> **Every `<PackageVersion>` row maps to a real, referenced feed package.** A central version belongs in `Directory.Packages.props` only when the package exists on a configured feed **and** at least one project consumes it via `<PackageReference>`. Do not pre-seed rows from the contract map ([../support/ef-packages-reference.md](../support/ef-packages-reference.md)) for names no project pulls as a package, and never add a row for a layer consumed via `<ProjectReference>` (see the local-mode rule above). Resolve versions by restoring against the configured feed at scaffold time - never guess or invent a version string. These exact rows are latest-at-scaffold snapshots (CPM forbids floating - see NU1011 rule above); on an intentional dependency refresh, re-resolve `<packagePrefix>.*` to the current feed latest rather than hand-editing pins. Remove orphan `<PackageVersion>` rows when no project references them.

---

## Package Map

Which project references which `<packagePrefix>.*` package, matching the TaskFlow csproj files. Reference a package directly where its types are named; do not re-reference what a project already gets transitively through a listed package. Add a capability row only when the capability is in scope. Type lists: [../support/ef-packages-reference.md](../support/ef-packages-reference.md) and [../support/ef-packages-optional.md](../support/ef-packages-optional.md).

| Project | References | Notes |
|---|---|---|
| `{App}.Domain.Shared` | EF.Domain.Contracts | Typed ids, `IDomainEvent` |
| `{App}.Domain.Model` | EF.Domain | Entities, `DomainEventContainer`; `[Mask]` comes from EF.Domain.Contracts, so no EF.Common reference |
| `{App}.Application.Models` | EF.Common.Contracts, EF.Tenancy (multi-tenant) | DTOs, `ITenantEntityDto`, `ITenantScopedFilter` search filters |
| `{App}.Application.Contracts` | EF.Common.Contracts, EF.Data.Contracts; EF.Messaging.Contracts (messaging); EF.Cache (entity caching) | Service and repository contracts, `IOutboxStaging` consumers |
| `{App}.Application.Services` | EF.Common, EF.Common.Contracts | Services, `{Entity}StructureValidator` over `EntityDtoRules` |
| `{App}.Application.Cqrs` | EF.CQRS, EF.Common.Contracts, EF.Data.Contracts | Only when `applicationStyle` is `cqrs` or `switch` |
| `{App}.Application.MessageHandlers` | EF.BackgroundServices, EF.Audit.Contracts | Internal-bus handlers, `IntegrationEventConsumerBase` consumers (EF.Messaging.Contracts through Application.Contracts) |
| `{App}.Infrastructure.Data` | EF.Data, EF.Data.Contracts, EF.Common.Contracts, EF.Domain.Contracts; EF.Data.PostgreSql and/or EF.Data.SqlServer per provider arm; EF.Data.Encryption, EF.Data.Outbox, EF.Audit.Data when enabled | DbContexts, configurations, outbox/inbox model |
| `{App}.Infrastructure.Repositories` | EF.Data, EF.Data.Contracts, EF.Audit.Contracts | Repositories and updaters |
| `{App}.Infrastructure.Caching` | EF.Cache | `AddTypedCache` and the shared Redis connection |
| `{App}.Infrastructure.Storage` | EF.Storage, EF.Storage.Contracts, EF.Table, EF.Audit.AzureTable (Azure lane) | Blob/Table repositories, Azure Table audit sink |
| `{App}.Infrastructure.Messaging.RabbitMq` | EF.Messaging.RabbitMq | Topology, consumers, outbox transport (NonAzure lane) |
| `{App}.Infrastructure.AI` | EF.AI | Chat and embedding clients |
| `ServiceDefaults` | EF.AspNetCore, EF.Host, EF.OpenTelemetry | Correlation, host lifecycle, OpenTelemetry, health endpoints |
| `{App}.Bootstrapper` | EF.Host, EF.AspNetCore, EF.AspNetCore.DataProtection, EF.Data, EF.Common, EF.BackgroundServices; EF.Messaging (Service Bus arm), EF.Storage / EF.Storage.S3 / EF.CosmosDb per store, EF.AI when enabled | Shared host registration |
| `{App}.Api` | EF.AspNetCore, EF.Auth, EF.Common; EF.RateLimiting.Redis (brings EF.RateLimiting) or EF.RateLimiting; EF.Grpc when gRPC is enabled | HTTP concerns |
| `{App}.Gateway` | EF.Gateway (brings EF.Auth), EF.RateLimiting | YARP transforms, edge limiter |
| `{App}.Scheduler` | EF.BackgroundServices, EF.BackgroundServices.TickerQ | Direct reference: the TickerQ source generator flows only to a project that references the package |
| `{App}.Functions` | EF.Messaging.Functions | Service Bus triggers |
| `{App}.DatabaseMigrator` | EF.Data | Migration runner |
| `{App}.Blazor` | EF.Http.Resilience | Read hedging on the UI read client |
| `{App}.Uno.Core` | EF.UI.Client | Busy, notifications, problem details, runtime base URL |
| `Test.Support` | EF.Testing, EF.IntegrationTesting, EF.IntegrationTesting.PostgreSql, EF.IntegrationTesting.SqlServer (SQL Server arm), EF.IntegrationTesting.Aspire (`Test.Aspire` tier) | WAF adapter, `TestDatabaseContainer`, builders |
| `Test.Unit` | EF.AI.Testing (AI in scope) plus the packages whose types the tests construct | No test framework helpers beyond EF.Testing through `Test.Support` |
| `Test.Architecture` | EF.Testing, EF.Testing.Architecture | Architecture and source rules |
| `Test.Endpoints`, `Test.Integration` | EF.IntegrationTesting; EF.AI.Testing (AI in scope) | |
| `Test.Aspire` | EF.IntegrationTesting, EF.IntegrationTesting.Aspire | Mesh fixtures |
| `Test.E2E` | EF.IntegrationTesting | |
| `Test.UI`, `Test.Mobile` | EF.Testing | HTTP stubs, readiness, environment |

---

## Critical Domain Contracts

Full type list per package: [../support/ef-packages-reference.md](../support/ef-packages-reference.md); capability-gated packages in [../support/ef-packages-optional.md](../support/ef-packages-optional.md).

### `EF.Domain.Contracts` (identity and tenancy)

```csharp
public interface IDomainId<TSelf> where TSelf : struct, IDomainId<TSelf>
{
    Guid Value { get; }
    static abstract TSelf From(Guid value);
}
```

```csharp
public interface IEntityBase<TId> { TId Id { get; init; } }
```

```csharp
public interface ITenantEntity<TTenantIdType> where TTenantIdType : struct
{
    TTenantIdType TenantId { get; init; }
}
```

### `EF.Domain`

```csharp
public abstract class EntityBase<TId> : IEntityBase<TId>, IVersionedEntity
    where TId : struct, IDomainId<TId>
{
    public TId Id { get; init; }     // typed domain ID, value set from Guid.CreateVersion7()
    public long Version { get; set; } // concurrency token: 1 after insert, incremented by DbContextBase on save
}
```

`AuditableBase<TAuditIdType>` is Guid-keyed (`: EntityBase, IAuditable<TAuditIdType>`) with getter-only `CreatedAtUtc`, `ModifiedAtUtc`, `CreatedBy`, `ModifiedBy` stamped on save. An entity that needs only timestamps implements `ITimestampedEntity` with private setters.

Critical invariants:
- Entity IDs use `Guid.CreateVersion7()`.
- Optimistic concurrency uses `Version` (`RegisterVersionConcurrencyTokens()` in EF.Data).
- Tenant entities implement `ITenantEntity<T>` and map through `TenantEntityTypeConfiguration`.

### `EF.Domain.Contracts` (results and events)

```csharp
public record DomainError(string Error, string? Code = null);
```

`DomainResult` / `DomainResult<T>`:
- success/failure states
- `Errors: IReadOnlyList<DomainError>`
- map/bind/match/tap helpers for railway flow

Also available: `IDomainEvent` / `IHasDomainEvents` (EF.Domain.Contracts), `DomainEventContainer` and `DomainException` (EF.Domain), and the one `MaskAttribute` (EF.Domain.Contracts) for audit and serialization redaction.

---

## Data Layer Contracts

### `EF.Data`

`DbContextBase<TAuditIdType, TTenantIdType>` provides:
- save-time stamping of timestamps, audit ids and `Version` from `Clock`
- the named, fail-closed tenant filter (`ApplyTenantQueryFilters`, `AllTenants`)
- concurrency-aware `SaveChangesAsync(OptimisticConcurrencyWinner winner, ...)`

Also in `EF.Data`: `TenantEntityTypeConfiguration` (`EF.Data.Configurations`), `AuditInterceptor` (`EF.Data.Interceptors`), `DbContextScopedFactory`, `RegisterDomainIdConversions`, `RegisterUtcTemporalConversions`, `RegisterVersionConcurrencyTokens`. EF.Data references no database provider: add EF.Data.PostgreSql or EF.Data.SqlServer.

### `EF.Data.Contracts`

`IRepositoryBase` supports:
- CRUD (`Create`, `PrepareForUpdate`, `UpdateFull`, `Delete`, `DeleteAsync`)
- existence and key lookups
- single query and paged queries
- projection queries and async streaming
- save changes with/without concurrency winner
- include/split-query options

Other key types:
- `OptimisticConcurrencyWinner` (`ClientWins`, `DBWins`, `Throw`) and `ConcurrencyGuard`
- `SplitQueryThresholdOptions`
- `ReadIsolation` (`Default`, `ReadUncommitted`) for the paging overloads
- `RelationalProviderSettings`, keyset paging (`CursorCodec`, `InvalidCursorException`)
- queryable helpers (`IQueryableExtensions`)

---

## Common Contracts

### `EF.Common.Contracts`

- `Result` / `Result<T>` (same shape as domain result, `Errors: IReadOnlyList<DomainError>`)
- `IRequestContext<TAuditIdType, TTenantIdType>`
- `RequestContext<...>` implementation - constructor order is `(correlationId, auditId, tenantId, roles)`
- `PagedResponse<T>` - properties: `PageSize` (int), `PageIndex` (int), `Total` (int), `Data` (IReadOnlyList&lt;T&gt;)
- `SearchRequest<TFilter>` - record with: `PageSize` (int), `PageIndex` (int), `Sorts` (IEnumerable&lt;Sort&gt;?), `Filter` (TFilter?)
- `IEntityBaseDto<TKey>` (`TKey? Id`, `TKey : struct`) + non-generic `IEntityBaseDto : IEntityBaseDto<Guid>` alias - base DTO contract; app-level `EntityBaseDto` implements the alias, non-Guid-key apps derive `EntityBaseDto<TKey>`
- `ITenantEntityDto`, `EntityDtoRules`, `IETagVersioned`, `UuidV7`
- `Sort` - constructor: `Sort(string propertyName, SortOrder sortOrder)` - properties: `PropertyName`, `SortOrder`
- `SortOrder` - enum: `Ascending = 0`, `Descending = 1`
- `IMessage`
- `AuditEntry<TAuditIdType, TTenantIdType>` + `AuditStatus`
- `NotFoundException`, `ConflictException`, `PreconditionFailedException`, `PreconditionRequiredException`

### `EF.Common`

- `ResultExtensions.ToResult(...)` for domain->application conversion
- expression/predicate helpers for EF-safe composition
- `ExceptionClassifier` and `ValidationException` (`EF.Common.Exceptions`)
- `StrictEnum` and the `GetRequiredEnum` / `GetEnum` configuration readers

---

### `EF.CQRS`

Add when `applicationStyle` is `cqrs` or `switch`.

| Type | Used For |
|---|---|
| `ICommand<TResponse>` | Write request marker (`EF.CQRS.Abstractions`) |
| `IQuery<TResponse>` | Read request marker (`EF.CQRS.Abstractions`) |
| `IRequestHandler<in TRequest,TResponse>` | Single request handler contract (`EF.CQRS.Abstractions`) |
| `IRequestValidator<TRequest>` | Optional request validator contract |
| `RequestValidationResult` | Validator result with one or more errors |
| `IValidationFailureResponseFactory<out TResponse>` | `CreateFailure(IReadOnlyCollection<DomainError>)` converts validation errors to the app response shape |
| `ValidationRequestHandlerDecorator<TRequest,TResponse>` | Decorates handlers with validation before execution |
| `AddDecoratedRequestHandler<TRequest,TResponse,THandler>()` | Registers the handler wrapped in validation and logging decorators (`DecoratedRequestHandlerOptions`) |

No MediatR, dispatcher, request bus, or generic `Send` API is part of this package. CQRS endpoints inject the specific `IRequestHandler<TRequest,TResponse>` they need.

---

## Background and Messaging

### `EF.BackgroundServices`

```csharp
// namespace EF.BackgroundServices.Work
public interface IBackgroundTaskQueue
{
    int QueueBackgroundWorkItem(Func<CancellationToken, Task> workItem, bool throwOnNullWorkitem = false);
    int QueueScopedBackgroundWorkItem<TScoped>(Func<TScoped, CancellationToken, Task> workItem,
        bool throwOnNullWorkitem = false, CancellationToken cancellationToken = default);
    Task<Func<CancellationToken, Task>?> DequeueAsync(CancellationToken cancellationToken);
}
```

### `EF.BackgroundServices.InternalMessageBus`

```csharp
public interface IInternalMessageBus
{
    void AutoRegisterHandlers(params Assembly[] assemblies);
    void RegisterMessageHandler<T>(IMessageHandler<T> handler) where T : IMessage;
    void UnregisterMessageHandler<T>(IMessageHandler<T> handler) where T : IMessage;
    void Publish<T>(InternalMessageBusProcessMode mode, ICollection<T> messages) where T : IMessage;
}

public interface IMessageHandler<in T> where T : IMessage
{
    Task HandleAsync(T message, CancellationToken cancellationToken = default);
}
```

**Namespace warning:** `IInternalMessageBus` / `IMessageHandler<T>` come from `EF.BackgroundServices.InternalMessageBus`.

**Dispatch warning:** `Publish(...)` queues work onto the registered `IBackgroundTaskQueue`; it is not an inline handler invocation, and there is no `PublishAsync` / single-message overload.

### Messaging packages

- `EF.Messaging.Contracts`: envelope, tracing, metrics, the `IOutboxTransport` port, the inbox contract and `IntegrationEventConsumerBase`; domain, application and RabbitMQ-only projects reference it instead of `EF.Messaging`.
- `EF.Data.Outbox`: outbox staging and dispatcher, `InboxStore<TContext>`, leased work tables.
- `EF.Messaging`: Service Bus, Event Grid and Event Hub senders/processors and the Service Bus outbox transport. Use the package base classes for sender/publisher/processor implementations.
- `EF.Messaging.RabbitMq`, `EF.Messaging.Functions`: transport adapters over the same consumer base.

---

## Data Service Extensions

### `EF.CosmosDb`

- Base entity: `CosmosDbEntity` (`PartitionKey`, `id` alias)
- Main abstraction: `ICosmosDbRepository`
  - save/get/delete
  - paged query + projection
- `CosmosDbRepositoryBase` adds `GetStream` query variants

### `EF.Storage`

`IBlobRepository` supports:
- container create/delete
- blob paging and streaming lists
- upload/download/delete (container and SAS URI overloads)
- SAS URI generation

`BlobRepositoryBase` also implements `IObjectStorageRepository` (EF.Storage.Contracts, including `ExistsAsync`) and adds `DistributedLockExecuteAsync` (blob lease).

### `EF.Table`

`ITableRepository` supports:
- get/upsert/delete entity
- paged query and streaming

### `EF.KeyVault`

- `IKeyVaultManager`: secrets/keys/certs operations
- `IKeyVaultCryptoUtility`: encrypt/decrypt helpers

### `EF.Grpc`

`ServiceErrorInterceptor` (through `ExceptionClassifier`), `ClientErrorInterceptor`, and `AddEFGrpcClient<TClient>()` for consistent gRPC error handling and client registration.

### `EF.FilterBuilder`

`FilterSet` / `Filter` contracts to generate dynamic query filters.

**Enterprise packages** (from <https://github.com/efreeman518/EF.Packages.Enterprise>):

### `EF.FlowEngine`

Durable, JSON-defined workflow orchestration engine. Add only when the requirement is a long-running, branching, or resumable process that a code-hosted agent cannot meet.

- `IFlowEngine`: start, signal, resume, terminate, status
- `IWorkflowRegistry`: workflow definition CRUD
- `IFlowClient` subtypes: `IRequestResponseClient`, `IQueryClient`, `IMessageClient`, `IAgentClient`, `IFlowEngineClient`
- `IDistributedLockProvider`, `IExecutionStateStore`, `IHumanTaskStore`, `IOutboxStore`, `ICircuitBreakerStore`
- Pluggable backend packages: `EF.FlowEngine.StateStore.*`, `EF.FlowEngine.Locks.*`, `EF.FlowEngine.WorkflowRegistry.*`, `EF.FlowEngine.HumanTaskStore.*`, `EF.FlowEngine.Clients.*`
- See [../support/ef-packages-optional.md](../support/ef-packages-optional.md) for full type list.

---

## Public Packages Used with EF.*

- `Refit` / `Refit.HttpClientFactory` (typed clients; `RefitCallHelper` in EF.UI.Refit)
- `Microsoft.Extensions.Http.Resilience` (ServiceDefaults standard handler; EF.Http.Resilience builds on it)
- `TickerQ.EntityFrameworkCore` (the scheduler's `TickerQDbContext` in the migration-owning data project) and `TickerQ.Dashboard` (when the dashboard is enabled); `TickerQ` itself arrives through EF.BackgroundServices.TickerQ

Pattern reference: [external-api.md](external-api.md)

---

## Generation Checklist

- [ ] For `packageStrategy: feed`/`hybrid`, repo-root `nuget.config` includes `nuget.org` and every entry in `customNugetFeeds`; for `local`, the file may be absent when NuGet's default source is sufficient
- [ ] For `packageStrategy: feed`/`hybrid`: local `NUGET_AUTH_TOKEN` or approved credential provider is configured for the private feed
- [ ] For `packageStrategy: feed`/`hybrid`: `python .instructions/scripts/configure-ef-packages-feed.py --root . --feed-url <feed-url> --username <github-user> --prefix <packagePrefix>` has been run or equivalent config has been manually verified
- [ ] For `packageStrategy: local`/`hybrid`: every layer in `localPackageLayers` has a corresponding `src/Packages/<packagePrefix>.<Layer>` project planned with `IsPackable=true` and `<PackageId>=<packagePrefix>.<Layer>`
- [ ] `dotnet restore` exits 0 before Phase 4 (with `NUGET_AUTH_TOKEN` set when `feed`/`hybrid`)
- [ ] `Directory.Packages.props` owns versions
- [ ] `global.json` pins SDK with roll-forward policy
- [ ] EF Core runtime/provider, Design, Tools when referenced, and repo-local `dotnet-ef` are patch-aligned; `dotnet tool restore` succeeds
- [ ] Referenced `Testcontainers.*` packages were refreshed together and each consuming test project compiled; unrelated package families were not forced to share a version
- [ ] Correct package placement across Domain/Data/Application/Infrastructure hosts
- [ ] Latest stable versions resolved successfully
- [ ] `dotnet restore` re-runs cleanly after projects are generated
- [ ] `EntityBase.Id` behavior preserved (`Guid.CreateVersion7()`)
- [ ] Domain (`DomainResult`) and application (`Result`) result types are not mixed across layer boundaries; both expose `Errors` / `Match` failure as `IReadOnlyList<DomainError>`
- [ ] Internal message bus namespaces are correct
- [ ] If `applicationStyle` is `cqrs` or `switch`: `<packagePrefix>.CQRS` is sourced by feed or local project, and no MediatR/dispatcher package was added
- [ ] Azure client factories and package-required DI wiring are registered
- [ ] Vendored native packages, when present, pass clean-consumer publish and runtime smoke for every declared RID; packaged data reaches consumer publish output

## Pitfalls

- Adding a package outside the allowlist without recording the decision in `.scaffold/DESIGN-DECISIONS.md` (**GR-04**) - drift compounds: each undocumented dependency makes the next one easier to slip in, and license/security review has no audit trail.
- Hard-coding a package version in instructions, templates, or `Directory.Packages.props` examples - violates the latest-stable rule (**GR-08**). Use `<latest-stable>` placeholders and let scaffold-time resolution pin the version.
- Adding MediatR or a similar dispatcher when `applicationStyle` is `cqrs` or `switch` - the scaffold ships `<packagePrefix>.CQRS` for exactly that role; layering MediatR on top fragments the request pipeline.
- Pinning a private-feed PAT into `nuget.config` instead of `%NUGET_AUTH_TOKEN%` / `$NUGET_AUTH_TOKEN` - leaks the credential into source control on the next push.
- Skipping `dotnet restore` verification after generating `src/Packages/<packagePrefix>.*` projects in `local`/`hybrid` mode - the first hint of a missing layer otherwise surfaces as a build error mid-Phase-5 with no easy diff to read.
- Shipping one platform's native binary in a generic content folder - publish can succeed while another RID fails at first P/Invoke or silently misses required data.
