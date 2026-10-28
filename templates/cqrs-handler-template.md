# CQRS Handler Template

Use when `.scaffold/resource-implementation.yaml` sets `applicationStyle: cqrs` or `switch`.

> **Aggregate roots and standalone entities only - not owned children (GR-15).** Before generating Create/Update/Delete commands + handlers, check the entity's aggregate classification from the domain spec (see [../ai/domain-specification-schema.md](../ai/domain-specification-schema.md) section Aggregate Roots vs Owned Children). The full write-command set below applies to **aggregate roots and independent standalone entities**. For an **owned child** (a 1:N owned entity or M:N junction inside another aggregate - e.g. a comment, checklist item, membership, score), generate read queries only (`Get`/`Search`); its writes flow through the **root**: the root's `UpdateFromDto` graph sync, or dedicated aggregate-routed commands on the root that load it and call its `Add*`/`Remove*`/`Transition` domain methods (`AddTaskItemCommentCommand`, `AssociateTaskItemTagCommand`, ...). Never emit a `Create{Child}`/`Update{Child}`/`Delete{Child}` handler that constructs or deletes the child through a child repository - that bypasses the root's invariants. This default is on unless the developer explicitly opts a specific child out (recorded in `.scaffold/DESIGN-DECISIONS.md`). See [../skills/domain-model.md](../skills/domain-model.md) section Aggregate Roots vs Internal Children and the reference app's `Features/TaskItems/TaskItemChildHandlers.cs`.

EF.CQRS contracts and registration helpers: [../support/ef-packages-optional.md](../support/ef-packages-optional.md) section CQRS.

Place request records, handlers, validators, and feature registration in `Application.Cqrs/Features/{Entity}/`. Keep shared CQRS helpers in `Application.Cqrs/Features/Shared/`. The root `Registration/CqrsHandlerRegistrationCatalog.cs` aggregates the per-feature registration fragments.

Default scaffold and TaskFlow reference app: keep DTOs in `Application.Models` and static mappers in `Application.Mappers` so service and CQRS styles share one HTTP contract. Full CQRS vertical slice: move feature-specific models, mappers, projections, and adapters into `Application.Cqrs/Features/{Entity}` when they are not shared with service endpoints.

```csharp
namespace {Project}.Application.Cqrs.Features.{EntityPlural};

public sealed record Create{Entity}Command(DefaultRequest<{Entity}Dto> Request)
    : ICommand<Result<DefaultResponse<{Entity}Dto>>>;

// ExpectedVersion is the endpoint's ifMatch.ExpectedVersion (EF.AspNetCore.Concurrency).
public sealed record Update{Entity}Command(DefaultRequest<{Entity}Dto> Request, long? ExpectedVersion)
    : ICommand<Result<DefaultResponse<{Entity}Dto>>>;

public sealed record Delete{Entity}Command(Guid Id, long? ExpectedVersion) : ICommand<Result<Unit>>;

internal sealed class Create{Entity}Handler(
    ILogger<Create{Entity}Handler> logger,
    IRequestContext<string, Guid?> requestContext,
    I{Entity}RepositoryTrxn repoTrxn,
    ITenantBoundaryValidator tenantBoundaryValidator)
    : IRequestHandler<Create{Entity}Command, Result<DefaultResponse<{Entity}Dto>>>
{
    public async Task<Result<DefaultResponse<{Entity}Dto>>> HandleAsync(
        Create{Entity}Command command,
        CancellationToken ct = default)
    {
        var dto = command.Request.Item;
        var authoritativeTenantId = requestContext.TenantId ?? Guid.Empty;
        dto.TenantId = authoritativeTenantId; // overwrite untrusted payload; never fall back to dto.TenantId

        var validation = {Entity}StructureValidator.ValidateCreate(dto);
        if (validation.TryGetValue(out Error? validationError)) return validationError;

        var boundary = tenantBoundaryValidator.EnsureTenantBoundary(   // EF.Tenancy
            requestContext.TenantId, requestContext.Roles, authoritativeTenantId,
            "{Entity}:Create", nameof({Entity}));
        if (boundary.TryGetValue(out Error? boundaryError)) return boundaryError;

        var entityResult = dto.ToEntity(authoritativeTenantId)
            .Bind(e => repoTrxn.UpdateFromDto(e, dto));
        if (entityResult.TryGetValue(out Error? entityError)) return entityError;

        var entity = entityResult.GetValueOrThrow();
        repoTrxn.Create(ref entity);

        var save = await CqrsHandlerSupport.TrySaveAsync(repoTrxn, logger, "Error creating {Entity}", ct);
        if (save.TryGetValue(out Error? saveError)) return saveError;

        return HandlerHelpers.Success(entity.ToDto());
    }
}

internal sealed class Update{Entity}Handler(
    ILogger<Update{Entity}Handler> logger,
    IRequestContext<string, Guid?> requestContext,
    I{Entity}RepositoryTrxn repoTrxn,
    ITenantBoundaryValidator tenantBoundaryValidator)
    : IRequestHandler<Update{Entity}Command, Result<DefaultResponse<{Entity}Dto>>>
{
    public async Task<Result<DefaultResponse<{Entity}Dto>>> HandleAsync(
        Update{Entity}Command command,
        CancellationToken ct = default)
    {
        var dto = command.Request.Item;
        var authoritativeTenantId = requestContext.TenantId ?? Guid.Empty;
        dto.TenantId = authoritativeTenantId;

        var validation = {Entity}StructureValidator.ValidateUpdate(dto);
        if (validation.TryGetValue(out Error? validationError)) return validationError;

        return await ConcurrencyRetry.RunAsync(repoTrxn, command.ExpectedVersion,   // If-Match: * retries (service-template.md)
            attemptCt => UpdateOnceAsync(dto, authoritativeTenantId, command.ExpectedVersion, attemptCt), ct);
    }

    private async Task<Result<DefaultResponse<{Entity}Dto>>> UpdateOnceAsync(
        {Entity}Dto dto, Guid authoritativeTenantId, long? expectedVersion, CancellationToken ct)
    {
        var entity = await repoTrxn.Get{Entity}Async(dto.Id!.Value, true, ct);
        if (entity == null) return new NotFoundError(ErrorConstants.ERROR_ITEM_NOTFOUND);

        var boundary = tenantBoundaryValidator.EnsureTenantBoundary(
            requestContext.TenantId, requestContext.Roles, entity.TenantId.Value,
            "{Entity}:Update", nameof({Entity}), entity.Id.Value);
        if (boundary.TryGetValue(out Error? boundaryError)) return boundaryError;

        ConcurrencyGuard.Require(expectedVersion, entity.Version, nameof({Entity}), entity.Id.Value);

        var tenantChange = tenantBoundaryValidator.PreventTenantChange(
            entity.TenantId.Value, authoritativeTenantId, nameof({Entity}), entity.Id.Value);
        if (tenantChange.TryGetValue(out Error? tenantChangeError)) return tenantChangeError;

        var update = repoTrxn.UpdateFromDto(entity, dto, RelatedDeleteBehavior.RelationshipAndEntity);
        if (update.TryGetValue(out Error? updateError)) return updateError;

        var save = await CqrsHandlerSupport.TrySaveAsync(repoTrxn, logger, "Error updating {Entity}", ct);
        if (save.TryGetValue(out Error? saveError)) return saveError;

        return HandlerHelpers.Success(entity.ToDto());
    }
}

internal sealed class Delete{Entity}Handler(
    ILogger<Delete{Entity}Handler> logger,
    IRequestContext<string, Guid?> requestContext,
    I{Entity}RepositoryTrxn repoTrxn,
    ITenantBoundaryValidator tenantBoundaryValidator)
    : IRequestHandler<Delete{Entity}Command, Result<Unit>>
{
    public Task<Result<Unit>> HandleAsync(Delete{Entity}Command command, CancellationToken ct = default) =>
        ConcurrencyRetry.RunAsync(repoTrxn, command.ExpectedVersion, attemptCt => DeleteOnceAsync(command, attemptCt), ct);

    private async Task<Result<Unit>> DeleteOnceAsync(Delete{Entity}Command command, CancellationToken ct)
    {
        var entity = await repoTrxn.Get{Entity}Async(command.Id, false, ct);
        if (entity == null) return Result.Ok();   // idempotent

        var boundary = tenantBoundaryValidator.EnsureTenantBoundary(
            requestContext.TenantId, requestContext.Roles, entity.TenantId.Value,
            "{Entity}:Delete", nameof({Entity}), entity.Id.Value);
        if (boundary.TryGetValue(out Error? boundaryError)) return boundaryError;

        ConcurrencyGuard.Require(command.ExpectedVersion, entity.Version, nameof({Entity}), entity.Id.Value);

        repoTrxn.Delete(entity);
        return await CqrsHandlerSupport.TrySaveAsync(repoTrxn, logger, "Error deleting {Entity}", ct);
    }
}
```

Rules:

- **Derive repository call sites from the actual contract (GR-14).** Before writing handler bodies, read the repository interface the handler injects (vendored source under `src/Packages/<packagePrefix>.Data.Contracts`, or [repository-template.md](repository-template.md) section Generic Repository Pair) or the first green handler in the codebase, and call only members that exist there. `IRepositoryQuery<TEntity, TId>` exposes `GetAsync(id)` and `ListAsync(predicate)` - there is no `QueryPageAsync` on it. Paged search goes through the bespoke `I{Entity}RepositoryQuery.Search{Entities}Async` (which uses the protected `RepositoryBase.QueryPageProjectionAsync` internally). Do not invent method names from conventions; a plausible name that compiles nowhere costs a fix in every generated handler.
- One command/query maps to one handler registration; no dispatcher, request bus or generic `Send()`.
- Multi-tenant create/update handlers overwrite DTO `TenantId` from `IRequestContext` before validation/mapping. Keep the field for contract compatibility, but never use payload tenant as fallback when context is missing.
- Create handlers apply `UpdateFromDto` after the factory so non-factory fields and aggregate children match service-style behavior.
- Update and delete commands carry `long? ExpectedVersion` (the endpoint passes `ifMatch.ExpectedVersion`); the handler calls `ConcurrencyGuard.Require(command.ExpectedVersion, entity.Version, nameof({Entity}), entity.Id.Value)` right after the load and boundary check, exactly as [service-template.md](service-template.md) does.
- Handler injects only repositories and collaborators it uses.
- Reuse existing repository contracts; do not create CQRS-specific repositories unless the domain needs a genuinely different abstraction.
- Handlers return `Result<T>` / `Result<Unit>`, propagating per [../support/ef-packages-reference.md](../support/ef-packages-reference.md) Result idioms. Search handlers return plain `PagedResponse<{Entity}Dto>` in the same catalog; no custom validation failure factory ([../support/ef-packages-optional.md](../support/ef-packages-optional.md) section CQRS).
- `CqrsHandlerSupport` holds small ceremony only: `TrySaveAsync` (save failures as in [service-template.md](service-template.md) Common Mistake 5) and `ToValidationResult` ([cqrs-validation-template.md](cqrs-validation-template.md)); searches get no helper, so cancellation propagates. Do not hide create/update/delete flow behind generic base handlers.

Per-feature registration fragment:

```csharp
namespace {Project}.Application.Cqrs.Features.{EntityPlural};

internal static class {Entity}CqrsRegistrations
{
    public static IReadOnlyList<RequestHandlerRegistration> Registrations { get; } =
    [
        new(typeof(Create{Entity}Command), typeof(Result<DefaultResponse<{Entity}Dto>>), typeof(Create{Entity}Handler)),
        new(typeof(Update{Entity}Command), typeof(Result<DefaultResponse<{Entity}Dto>>), typeof(Update{Entity}Handler)),
        new(typeof(Delete{Entity}Command), typeof(Result<Unit>), typeof(Delete{Entity}Handler)),
    ];
}
```

Root catalog aggregates feature fragments:

```csharp
public static class CqrsHandlerRegistrationCatalog
{
    public static IReadOnlyList<RequestHandlerRegistration> Registrations { get; } =
    [
        ..{Entity}CqrsRegistrations.Registrations,
    ];
}
```
