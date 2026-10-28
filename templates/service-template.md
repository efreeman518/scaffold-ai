# Service Template

> **When to read:** Phase 5b, when generating an application service for an entity - orchestrating repositories, mapping DTOs, returning `Result<T>` / `Result<DefaultResponse>`.
> **Skip if:** Pure projection (no orchestration); query-only with no domain rules; service already exists.

| | |
|---|---|
| **File** | `Application.Services/{Entity}Service.cs` |
| **Depends on** | [repository-template](repository-template.md), [data-mapping-template](data-mapping-template.md), [structure-validator-template](structure-validator-template.md) |
| **Referenced by** | [endpoint-template](endpoint-template.md), [bootstrapper.md](../skills/bootstrapper.md) |

> **Token vs log placeholder:** in `"{Entity} {Id} created"`, `{Entity}` is a scaffold token and `{Id}` the log property bound to the trailing argument; in the cache tag `$"{entity}:{tenantId}:{id}"`, `{entity}` is the token and the rest are interpolated parameters. Substitute tokens only, then confirm the surviving `{...}` count equals the trailing-argument count. Rule: [../ai/placeholder-tokens.md](../ai/placeholder-tokens.md) section Disambiguating Tokens From Logging And Interpolation.

> **Multi-tenant toggle:** Lines marked `// [MULTI-TENANT]` apply only when the domain specification enables multi-tenancy. DTOs keep `TenantId` for round-trips; write services overwrite it from `IRequestContext` before validation, so clients never pick the owner. `ITenantBoundaryValidator` is the EF.Tenancy singleton ([../skills/multi-tenant.md](../skills/multi-tenant.md)) and logs its own security events. Single-tenant scaffolds omit it, tenant stamping, boundary checks, filter enforcement, the cache tag's tenant segment and `TenantInfoDto`.

## File: Application/Services/{Entity}Service.cs

```csharp
using EF.Cache;
using EF.Common.Contracts;
using EF.Data.Contracts;
using EF.Domain.Contracts;
using EF.Tenancy;   // [MULTI-TENANT]

namespace Application.Services;

internal class {Entity}Service(
    ILogger<{Entity}Service> logger,
    IRequestContext<string, Guid?> requestContext,
    I{Entity}RepositoryTrxn repoTrxn,
    I{Entity}RepositoryQuery repoQuery,
    ITypedCache cache,
    ITenantBoundaryValidator tenantBoundaryValidator) : I{Entity}Service  // [MULTI-TENANT] omit ITenantBoundaryValidator for single-tenant
{
    private Guid? RequestTenantId => requestContext.TenantId;                           // [MULTI-TENANT]
    private IReadOnlyCollection<string> RequestRoles => requestContext.Roles;            // [MULTI-TENANT]

    // After the commit, never before; tenant-scoped like the key (caching.md sections Cache Key Rules, Scale Hazards).
    private Task InvalidateAsync(Guid tenantId, Guid id, CancellationToken ct) => cache.RemoveByTagAsync($"{entity}:{tenantId}:{id}", ct);

    #region Helpers

    private static DefaultResponse<{Entity}Dto> BuildResponse({Entity}Dto dto) =>
        new() { Item = dto, TenantInfo = null };  // [MULTI-TENANT] include TenantInfo when available

    #endregion

    // ===== Search =====
    public async Task<PagedResponse<{Entity}Dto>> SearchAsync(
        SearchRequest<{Entity}SearchFilter> request, CancellationToken ct = default)
    {
        // [MULTI-TENANT] Forces the caller's tenant for any non-cross-tenant caller; logs a supplied foreign tenant.
        request.Filter = tenantBoundaryValidator.EnforceTenantFilter(request.Filter, RequestTenantId, RequestRoles, "{Entity}Search");
        return await repoQuery.Search{Entity}Async(request, ct);
    }

    // ===== Get =====
    public async Task<Result<DefaultResponse<{Entity}Dto>>> GetAsync(Guid id, CancellationToken ct = default)
    {
        var entity = await repoTrxn.Get{Entity}Async(id, true, ct);
        if (entity == null) return new NotFoundError(ErrorConstants.ERROR_ITEM_NOTFOUND);

        // [MULTI-TENANT]
        var boundary = tenantBoundaryValidator.EnsureTenantBoundary(
            RequestTenantId, RequestRoles, entity.TenantId.Value,
            "{Entity}:Get", nameof({Entity}), entity.Id.Value);
        if (boundary.TryGetValue(out Error? boundaryError)) return boundaryError;

        return BuildResponse(entity.ToDto());
    }

    // ===== Create =====
    public async Task<Result<DefaultResponse<{Entity}Dto>>> CreateAsync(
        DefaultRequest<{Entity}Dto> request, CancellationToken ct = default)
    {
        var dto = request.Item;

        // [MULTI-TENANT] Overwrite untrusted payload tenant before validation/mapping.
        // Guid.Empty deliberately fails when trusted tenant context is missing; never fall back to dto.TenantId.
        var authoritativeTenantId = RequestTenantId ?? Guid.Empty;
        dto.TenantId = authoritativeTenantId;

        // [IDENTITY] Stamp owner/created-by from request context when the entity has one - UI-driven
        // creates arrive with an empty owner and would otherwise violate the user FK. The audit id is a
        // real seeded user GUID in dev (the fixed principal's user id claim). See
        // ../patterns/api-host-wiring.md section Dev-Mode Write Identity. Omit for ownerless entities.
        // dto.OwnerId = ParseAuditId(requestContext.AuditId); // overwrite untrusted payload

        // Structure validation (EntityDtoRules common checks plus the entity's own rules)
        var validation = {Entity}StructureValidator.ValidateCreate(dto);
        if (validation.TryGetValue(out Error? validationError)) return validationError;

        // [MULTI-TENANT] Tenant boundary
        var boundary = tenantBoundaryValidator.EnsureTenantBoundary(
            RequestTenantId, RequestRoles, authoritativeTenantId,
            "{Entity}:Create", nameof({Entity}));
        if (boundary.TryGetValue(out Error? boundaryError)) return boundaryError;

        // Create domain entity via factory + UpdateFromDto for children
        var entityResult = dto.ToEntity(authoritativeTenantId)
            .Bind(e => repoTrxn.UpdateFromDto(e, dto));
        if (entityResult.TryGetValue(out Error? entityError)) return entityError;

        var entity = entityResult.GetValueOrThrow();
        repoTrxn.Create(ref entity);

        // The aggregate raised {Entity}CreatedEvent in its factory; when messaging is enabled, the EF.Data.Outbox
        // staging interceptor writes it as an outbox row in this same save (messaging.md). No publish call here.
        await repoTrxn.SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct);
        logger.LogInformation("{Entity} {Id} created", entity.Id.Value);

        return BuildResponse(entity.ToDto());
    }

    // ===== Update =====
    public async Task<Result<DefaultResponse<{Entity}Dto>>> UpdateAsync(
        DefaultRequest<{Entity}Dto> request, long? expectedVersion, CancellationToken ct = default)
    {
        var dto = request.Item;

        // [MULTI-TENANT] Overwrite the payload tenant (as in CreateAsync).
        var authoritativeTenantId = RequestTenantId ?? Guid.Empty;
        dto.TenantId = authoritativeTenantId;

        var validation = {Entity}StructureValidator.ValidateUpdate(dto);
        if (validation.TryGetValue(out Error? validationError)) return validationError;

        // Concrete If-Match runs once (412); `*` (null) retries, 409 when exhausted.
        var result = await ConcurrencyRetry.RunAsync(repoTrxn, expectedVersion, nameof({Entity}), dto.Id!.Value,
            attemptCt => UpdateOnceAsync(dto, authoritativeTenantId, expectedVersion, attemptCt), ct);
        if (result is DefaultResponse<{Entity}Dto> { Item: not null }) await InvalidateAsync(authoritativeTenantId, dto.Id!.Value, ct);
        return result;
    }

    private async Task<Result<DefaultResponse<{Entity}Dto>>> UpdateOnceAsync(
        {Entity}Dto dto, Guid authoritativeTenantId, long? expectedVersion, CancellationToken ct)
    {
        var entity = await repoTrxn.Get{Entity}Async(dto.Id!.Value, true, ct);
        if (entity == null) return new NotFoundError(ErrorConstants.ERROR_ITEM_NOTFOUND);

        // [MULTI-TENANT] Tenant boundary
        var boundary = tenantBoundaryValidator.EnsureTenantBoundary(
            RequestTenantId, RequestRoles, entity.TenantId.Value,
            "{Entity}:Update", nameof({Entity}), entity.Id.Value);
        if (boundary.TryGetValue(out Error? boundaryError)) return boundaryError;

        // Stale If-Match -> PreconditionFailedException -> 412 with the current ETag (RequireIfMatch filter).
        ConcurrencyGuard.Require(expectedVersion, entity.Version, nameof({Entity}), entity.Id.Value);

        // [MULTI-TENANT] Prevent tenant change
        var tenantChange = tenantBoundaryValidator.PreventTenantChange(
            entity.TenantId.Value, authoritativeTenantId, nameof({Entity}), entity.Id.Value);
        if (tenantChange.TryGetValue(out Error? tenantChangeError)) return tenantChangeError;

        // RelationshipAndEntity: the DTO carries the full child list (data-persistence.md, Updater Pattern).
        var updateResult = repoTrxn.UpdateFromDto(entity, dto, RelatedDeleteBehavior.RelationshipAndEntity);
        if (updateResult.TryGetValue(out Error? updateError)) return updateError;

        await repoTrxn.SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct);
        return BuildResponse(entity.ToDto());
    }

    // ===== Delete (idempotent - return success if not found) =====
    public async Task<Result<Unit>> DeleteAsync(Guid id, long? expectedVersion, CancellationToken ct = default)
    {
        Guid deletedTenantId = default;
        var result = await ConcurrencyRetry.RunAsync<Result<Unit>>(repoTrxn, expectedVersion, nameof({Entity}), id, async attemptCt =>
        {
            var entity = await repoTrxn.Get{Entity}Async(id, false, attemptCt);
            if (entity == null) return Result.Ok();  // idempotent
            var boundary = tenantBoundaryValidator.EnsureTenantBoundary( // [MULTI-TENANT]
                RequestTenantId, RequestRoles, entity.TenantId.Value,
                "{Entity}:Delete", nameof({Entity}), entity.Id.Value);
            if (boundary.TryGetValue(out Error? boundaryError)) return boundaryError;
            ConcurrencyGuard.Require(expectedVersion, entity.Version, nameof({Entity}), entity.Id.Value);
            repoTrxn.Delete(entity);
            deletedTenantId = entity.TenantId.Value;   // before the save: a retry finding it gone still evicts
            await repoTrxn.SaveChangesAsync(OptimisticConcurrencyWinner.Throw, attemptCt);
            return Result.Ok();
        }, ct);
        if (deletedTenantId != default) await InvalidateAsync(deletedTenantId, id, ct);
        return result;
    }

    // ===== Lookup (autocomplete / dropdowns) =====
    public async Task<StaticList<StaticItem<Guid, Guid?>>> LookupAsync(
        Guid? tenantId, string? search, CancellationToken ct = default)
    {
        // [MULTI-TENANT] Only a cross-tenant role may name another tenant.
        if (!tenantBoundaryValidator.EnsureCrossTenantRole(RequestRoles, "{Entity}:Lookup").IsSuccess) tenantId = RequestTenantId;
        return await repoQuery.Lookup{Entity}Async(tenantId, search, ct);
    }
}
```

## File: Application/Contracts/Services/I{Entity}Service.cs

```csharp
namespace Application.Contracts.Services;

public interface I{Entity}Service
{
    Task<PagedResponse<{Entity}Dto>> SearchAsync(SearchRequest<{Entity}SearchFilter> request, CancellationToken ct = default);
    Task<Result<DefaultResponse<{Entity}Dto>>> GetAsync(Guid id, CancellationToken ct = default);
    Task<Result<DefaultResponse<{Entity}Dto>>> CreateAsync(DefaultRequest<{Entity}Dto> request, CancellationToken ct = default);
    Task<Result<DefaultResponse<{Entity}Dto>>> UpdateAsync(DefaultRequest<{Entity}Dto> request, long? expectedVersion, CancellationToken ct = default);
    Task<Result<Unit>> DeleteAsync(Guid id, long? expectedVersion, CancellationToken ct = default);
    Task<StaticList<StaticItem<Guid, Guid?>>> LookupAsync(Guid? tenantId, string? search, CancellationToken ct = default);
}
```

## Common Mistakes (Verified via Test Failures)

Service rules 5-10 in [application-layer.md](../skills/application-layer.md) section Service Pattern (delete marking, full DTO apply on create, the `Throw` save overload, `BuildResponse`, `ErrorConstants`, `nameof`) and Non-Negotiable 6 (tenant stamping) cover the most frequent failures. Also:
1. **Post-mapping search results** - When the query repo uses `QueryPageProjectionAsync` and returns `PagedResponse<{Entity}Dto>`, the service MUST direct-return: `return await repoQuery.Search{Entity}Async(request, ct);`. Do NOT re-wrap into a new `PagedResponse` or call `.ToDto()` - the projection already happened at the SQL level.
2. **Missing UpdateFromDto mock in tests** - `CreateAsync` uses `.Bind(e => repoTrxn.UpdateFromDto(e, dto))` and `UpdateAsync` calls `repoTrxn.UpdateFromDto(entity, dto, RelatedDeleteBehavior.RelationshipAndEntity)`. Unmocked, it returns the default `Result`, an `UnexpectedError` (500). Always mock with `It.IsAny<RelatedDeleteBehavior>()` so both call shapes match: `_repoTrxnMock.Setup(r => r.UpdateFromDto(It.IsAny<{Entity}>(), It.IsAny<{Entity}Dto>(), It.IsAny<RelatedDeleteBehavior>())).Returns((Entity e, EntityDto _, RelatedDeleteBehavior _) => e);` (`Result<{Entity}>` converts implicitly)
3. **[Multi-tenant] Missing PreventTenantChange in Update** - After boundary check, before domain update, compare the existing entity tenant with the stamped authoritative tenant as a defense-in-depth invariant.
4. **Invented repository members (GR-14)** - Call only members that exist on the injected contract. Read the interface (or the first green service/handler) before writing call sites. `IRepositoryQuery<TEntity, TId>` exposes `GetAsync(id)` / `ListAsync(predicate)`; paged search lives on the bespoke `I{Entity}RepositoryQuery.Search{Entity}Async`. `QueryPageAsync` / `QueryPageProjectionAsync` are protected `RepositoryBase` helpers for repository implementations only.
5. **Save failure as a result** - catch only `when (SaveFailure.MapsToFailureResult(ex))` and return `SaveFailure.ToError(ex)`, never `ex.Message`: [data-persistence.md](../skills/data-persistence.md) section Provider Branch and Concurrency Discipline.
6. **Version check after the load** - `ConcurrencyGuard.Require` runs right after the boundary check, before any change; concrete and `*` If-Match semantics: [data-persistence.md](../skills/data-persistence.md) section Provider Branch and Concurrency Discipline.

## Policy Notes

- Monetary and time-boundary sensitive logic should be delegated to dedicated policy services (for example money calculation, entitlement resolution, and period boundary policy) rather than hard-coded inside endpoint handlers.

---

**TaskFlow proof (local):** `../scaffold-proof/src/Application/TaskFlow.Application.Services/CategoryService.cs` (single aggregate) and `TaskItemService.cs` (children) + companion `Rules/{Entity}StructureValidator.cs`
**TaskFlow proof (remote fallback):** <https://github.com/efreeman518/scaffold-proof/blob/main/src/Application/TaskFlow.Application.Services/TaskItemService.cs>
