# Service Template

> **When to read:** Phase 5b, when generating an application service for an entity - orchestrating repositories, mapping DTOs, returning `Result<T>` / `Result<DefaultResponse>`.
> **Skip if:** Pure projection (no orchestration); query-only with no domain rules; service already exists.

| | |
|---|---|
| **File** | `Application.Services/{Entity}Service.cs` |
| **Depends on** | [repository-template](repository-template.md), [data-mapping-template](data-mapping-template.md), [structure-validator-template](structure-validator-template.md) |
| **Referenced by** | [endpoint-template](endpoint-template.md), [bootstrapper.md](../skills/bootstrapper.md) |

> **Token vs log placeholder:** one `ILogger` template below carries both - in `"{Entity} {Id} created"`, `{Entity}` is a scaffold token and `{Id}` is the log property bound to the single trailing argument; in the cache tag `$"{entity}:{id}"`, `{entity}` is the token and `{id}` the interpolated parameter. Substitute the first, leave the second verbatim, then confirm the surviving `{...}` count equals the trailing-argument count. Rule: [../ai/placeholder-tokens.md](../ai/placeholder-tokens.md) section Disambiguating Tokens From Logging And Interpolation.

> **Multi-tenant toggle:** Lines marked `// [MULTI-TENANT]` apply only when the domain specification enables multi-tenancy. DTOs retain `TenantId` for response/round-trip compatibility, but write services overwrite it from `IRequestContext` before validation/mapping; clients never select tenant ownership. `ITenantBoundaryValidator` is the EF.Tenancy singleton ([../skills/multi-tenant.md](../skills/multi-tenant.md)); it logs its own security events. For single-tenant scaffolds, omit its injection, tenant stamping, boundary checks, tenant filter enforcement, and `TenantInfoDto` in `DefaultResponse`. TaskFlow demonstrates multi-tenant patterns.

## File: Application/Services/{Entity}Service.cs

```csharp
using EF.Cache;
using EF.Common.Contracts;
using EF.Data.Contracts;
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

    // Invalidate after the commit, never before (caching.md section Scale Hazards).
    private Task InvalidateAsync(Guid id, CancellationToken ct) => cache.RemoveByTagAsync($"{entity}:{id}", ct);

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
        if (entity == null) return Result<DefaultResponse<{Entity}Dto>>.None();

        // [MULTI-TENANT]
        var boundary = tenantBoundaryValidator.EnsureTenantBoundary(
            RequestTenantId, RequestRoles, entity.TenantId.Value,
            "{Entity}:Get", nameof({Entity}), entity.Id.Value);
        if (boundary.IsFailure) return Result<DefaultResponse<{Entity}Dto>>.Failure(boundary.ErrorMessage!);

        return Result<DefaultResponse<{Entity}Dto>>.Success(BuildResponse(entity.ToDto()));
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
        if (validation.IsFailure) return Result<DefaultResponse<{Entity}Dto>>.Failure(validation.Errors);

        // [MULTI-TENANT] Tenant boundary
        var boundary = tenantBoundaryValidator.EnsureTenantBoundary(
            RequestTenantId, RequestRoles, authoritativeTenantId,
            "{Entity}:Create", nameof({Entity}));
        if (boundary.IsFailure) return Result<DefaultResponse<{Entity}Dto>>.Failure(boundary.ErrorMessage!);

        // Create domain entity via factory + UpdateFromDto for children
        var entityResult = dto.ToEntity(authoritativeTenantId)
            .Bind(e => repoTrxn.UpdateFromDto(e, dto));
        if (entityResult.IsFailure)
            return Result<DefaultResponse<{Entity}Dto>>.Failure(entityResult.ErrorMessage);

        var entity = entityResult.Value!;
        repoTrxn.Create(ref entity);

        // The aggregate raised {Entity}CreatedEvent in its factory; when messaging is enabled, the EF.Data.Outbox
        // staging interceptor writes it as an outbox row in this same save (messaging.md). No publish call here.
        await repoTrxn.SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct);
        logger.LogInformation("{Entity} {Id} created", entity.Id.Value);

        return Result<DefaultResponse<{Entity}Dto>>.Success(BuildResponse(entity.ToDto()));
    }

    // ===== Update =====
    public async Task<Result<DefaultResponse<{Entity}Dto>>> UpdateAsync(
        DefaultRequest<{Entity}Dto> request, long? expectedVersion, CancellationToken ct = default)
    {
        var dto = request.Item;

        // [MULTI-TENANT] Overwrite untrusted payload tenant before validation/mapping.
        var authoritativeTenantId = RequestTenantId ?? Guid.Empty;
        dto.TenantId = authoritativeTenantId;

        // Structure validation
        var validation = {Entity}StructureValidator.ValidateUpdate(dto);
        if (validation.IsFailure) return Result<DefaultResponse<{Entity}Dto>>.Failure(validation.Errors);

        // Fetch existing
        var entity = await repoTrxn.Get{Entity}Async(dto.Id!.Value, true, ct);
        if (entity == null)
            return Result<DefaultResponse<{Entity}Dto>>.Failure($"{ErrorConstants.ERROR_ITEM_NOTFOUND}: {dto.Id}");

        // [MULTI-TENANT] Tenant boundary
        var boundary = tenantBoundaryValidator.EnsureTenantBoundary(
            RequestTenantId, RequestRoles, entity.TenantId.Value,
            "{Entity}:Update", nameof({Entity}), entity.Id.Value);
        if (boundary.IsFailure) return Result<DefaultResponse<{Entity}Dto>>.Failure(boundary.ErrorMessage!);

        // Stale If-Match -> PreconditionFailedException -> 412 with the current ETag (RequireIfMatch filter).
        ConcurrencyGuard.Require(expectedVersion, entity.Version, nameof({Entity}), entity.Id.Value);

        // [MULTI-TENANT] Prevent tenant change
        var tenantChange = tenantBoundaryValidator.PreventTenantChange(
            entity.TenantId.Value, authoritativeTenantId, nameof({Entity}), entity.Id.Value);
        if (tenantChange.IsFailure) return Result<DefaultResponse<{Entity}Dto>>.Failure(tenantChange.ErrorMessage!);

        // Update domain entity via UpdateFromDto (handles children).
        // RelationshipAndEntity: aggregate-edit pages send the full desired child
        // list, so items missing from the DTO must be hard-deleted. Default `None`
        // silently drops client-side removals. If this service is used only by
        // non-aggregate callers that never remove children, drop the 3rd arg.
        var updateResult = repoTrxn.UpdateFromDto(entity, dto, RelatedDeleteBehavior.RelationshipAndEntity);
        if (updateResult.IsFailure)
            return Result<DefaultResponse<{Entity}Dto>>.Failure(updateResult.ErrorMessage);

        await repoTrxn.SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct);
        await InvalidateAsync(entity.Id.Value, ct);

        return Result<DefaultResponse<{Entity}Dto>>.Success(BuildResponse(entity.ToDto()));
    }

    // ===== Delete (idempotent - return success if not found) =====
    public async Task<Result> DeleteAsync(Guid id, long? expectedVersion, CancellationToken ct = default)
    {
        var entity = await repoTrxn.Get{Entity}Async(id, false, ct);
        if (entity == null) return Result.Success();  // idempotent

        // [MULTI-TENANT]
        var boundary = tenantBoundaryValidator.EnsureTenantBoundary(
            RequestTenantId, RequestRoles, entity.TenantId.Value,
            "{Entity}:Delete", nameof({Entity}), entity.Id.Value);
        if (boundary.IsFailure) return Result.Failure(boundary.ErrorMessage!);

        ConcurrencyGuard.Require(expectedVersion, entity.Version, nameof({Entity}), entity.Id.Value);

        repoTrxn.Delete(entity);

        await repoTrxn.SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct);
        await InvalidateAsync(entity.Id.Value, ct);

        return Result.Success();
    }

    // ===== Lookup (autocomplete / dropdowns) =====
    public async Task<StaticList<StaticItem<Guid, Guid?>>> LookupAsync(
        Guid? tenantId, string? search, CancellationToken ct = default)
    {
        // [MULTI-TENANT] Only a cross-tenant role may name another tenant.
        if (tenantBoundaryValidator.EnsureCrossTenantRole(RequestRoles, "{Entity}:Lookup").IsFailure) tenantId = RequestTenantId;
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
    Task<Result> DeleteAsync(Guid id, long? expectedVersion, CancellationToken ct = default);
    Task<StaticList<StaticItem<Guid, Guid?>>> LookupAsync(Guid? tenantId, string? search, CancellationToken ct = default);
}
```

## Common Mistakes (Verified via Test Failures)

1. **Delete no-op** - Forgetting `repoTrxn.Delete(entity)` before `SaveChangesAsync`. The entity is loaded but never marked for deletion. Save commits nothing.
2. **CreateAsync incomplete** - `Entity.Create()` only accepts factory constructor args. Additional DTO properties (e.g., `EstimatedHours`, `ActualHours`, `Description`) must be applied via `entity.Update(...)` after creation. If omitted, domain validation that depends on those fields won't trigger.
3. **Wrong SaveChangesAsync** - `SaveChangesAsync(CancellationToken)` saves with no named conflict strategy. Normal application writes use `SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct)` so conflict handling remains reachable.
4. **Post-mapping search results** - When the query repo uses `QueryPageProjectionAsync` and returns `PagedResponse<{Entity}Dto>`, the service MUST direct-return: `return await repoQuery.Search{Entity}Async(request, ct);`. Do NOT re-wrap into a new `PagedResponse` or call `.ToDto()` - the projection already happened at the SQL level.
5. **Missing UpdateFromDto mock in tests** - `CreateAsync` uses `.Bind(e => repoTrxn.UpdateFromDto(e, dto))` and `UpdateAsync` calls `repoTrxn.UpdateFromDto(entity, dto, RelatedDeleteBehavior.RelationshipAndEntity)`. If tests don't mock `UpdateFromDto`, they get `NullReferenceException`. Always mock with `It.IsAny<RelatedDeleteBehavior>()` so both call shapes match: `_repoTrxnMock.Setup(r => r.UpdateFromDto(It.IsAny<{Entity}>(), It.IsAny<{Entity}Dto>(), It.IsAny<RelatedDeleteBehavior>())).Returns((Entity e, EntityDto _, RelatedDeleteBehavior _) => DomainResult<{Entity}>.Success(e));`
6. **[Multi-tenant] Missing authoritative TenantId stamp** - Immediately after `var dto = request.Item;`, compute `var authoritativeTenantId = RequestTenantId ?? Guid.Empty`, overwrite `dto.TenantId`, then validate/map with `authoritativeTenantId`. Never use `RequestTenantId ?? dto.TenantId`; that lets a forged payload establish ownership when trusted context is absent.
7. **Update not-found returns Failure** - Use `Result<DefaultResponse<{Entity}Dto>>.Failure($"{ErrorConstants.ERROR_ITEM_NOTFOUND}: {dto.Id}")`, not `Success` with `Item = null`.
8. **Inline entity name strings** - Always use `nameof({Entity})` in boundary-validator calls and error messages, not hardcoded strings.
13. **Version check after the load, not the save alone** - `ConcurrencyGuard.Require(expectedVersion, entity.Version, ...)` runs right after the boundary check, so a stale `If-Match` answers 412 with the current ETag before any change; `SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct)` still catches a lost update between load and save.
9. **Missing BuildResponse** - All success paths should use the private static `BuildResponse` helper, not inline `new() { Item = ... }`.
10. **[Multi-tenant] Missing PreventTenantChange in Update** - After boundary check, before domain update, compare the existing entity tenant with the stamped authoritative tenant as a defense-in-depth invariant.
11. **Invented repository members (GR-14)** - Call only members that exist on the injected contract. Read the interface (or the first green service/handler in the codebase) before writing call sites. `IRepositoryQuery<TEntity, TId>` exposes `GetAsync(id)` / `ListAsync(predicate)`; paged search lives on the bespoke `I{Entity}RepositoryQuery.Search{Entity}Async`. There is no `QueryPageAsync` on the consumer-facing contracts - `QueryPageAsync` / `QueryPageProjectionAsync` are protected `RepositoryBase` helpers, callable only inside repository implementations.
12. **Provider error text in a result** - Save exceptions propagate to the exception handler, which maps concurrency to 412 and everything else to a generic 500. Never return `ex.Message` or `GetBaseException().Message`: it leaks SQL, schema, and connection details to the caller. Catch only an app-mapped constraint exception (for example a unique-name violation) and return a fixed `ErrorConstants` message.

## Policy Notes

- Monetary and time-boundary sensitive logic should be delegated to dedicated policy services (for example money calculation, entitlement resolution, and period boundary policy) rather than hard-coded inside endpoint handlers.

---

**TaskFlow proof (local):** `../scaffold-proof/src/Application/TaskFlow.Application.Services/CategoryService.cs` (single aggregate) and `TaskItemService.cs` (children) + companion `Rules/{Entity}StructureValidator.cs`
**TaskFlow proof (remote fallback):** <https://github.com/efreeman518/scaffold-proof/blob/main/src/Application/TaskFlow.Application.Services/TaskItemService.cs>
