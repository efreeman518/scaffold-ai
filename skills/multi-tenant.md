# Multi-Tenant Architecture

Reference patterns: [../patterns/api-host-wiring.md](../patterns/api-host-wiring.md) (Request Context Resolution), [../patterns/data-layer-wiring.md](../patterns/data-layer-wiring.md) (Multi-tenant Query Filter).

> **Applicability:** This skill applies only when the domain specification enables multi-tenancy. The TaskFlow reference app demonstrates full multi-tenant patterns. For single-tenant scaffolds, skip this entire file - omit `ITenantEntity<TenantId>`, `ITenantBoundaryValidator`, tenant query filters, tenant stamping, and tenant-scoped search enforcement. The service template marks optional sections with `// [MULTI-TENANT]`.

## Purpose

Enforce tenant isolation through data, service, and request-context layers with explicit global-admin escape paths only where intended.

## Enforcement Layers

1. EF query filters on tenant-scoped entities.
2. Service-layer tenant boundary validation.
3. Scoped `IRequestContext` built from authenticated claims (or the explicit local/background fallback paths in [api-host-wiring.md](../patterns/api-host-wiring.md)).

## Non-Negotiables

1. Tenant-scoped entities implement `ITenantEntity<TenantId>`.
2. DbContext applies the fail-closed tenant query filter (`ApplyTenantQueryFilters`) to every tenant entity, and every scoped context factory carries an explicit all-tenants rule.
3. Services validate tenant boundary before returning/modifying entity data.
4. Create/update flows derive tenant from request context, not client payload.
5. Cross-tenant access is explicit and auditable, and is derived from a role in `TenancyOptions.CrossTenantRoles` (`AppConstants.ROLE_GLOBAL_ADMIN` on `ClaimTypes.Role` for users, `ROLE_SYSTEM` for the no-request system identity) checked by `EnsureCrossTenantRole(...)`.
6. DTOs retain `TenantId` for response/round-trip compatibility, but clients never own write-side tenant selection.
7. No request header, query parameter, or environment flag flips tenant filtering. An ambient bypass is reachable in Production by anyone who can set it, and it sidesteps the boundary validator that enforces isolation; the role-claim path above is the only bypass.

---

## Tenant Entity Contract

```csharp
public interface ITenantEntity<TTenantIdType> where TTenantIdType : struct
{
    TTenantIdType TenantId { get; init; }
}

public class TodoItem : EntityBase<TodoItemId>, ITenantEntity<TenantId>
{
    public TenantId TenantId { get; init; }
}
```

`TenantId` is a typed value struct (`TenantId : IDomainId<TenantId>`) and is immutable after creation. **Why:** Tenant identity is an ownership boundary, not editable business data; reassignment would turn an update into a cross-tenant move that bypasses query-filter and audit assumptions. Therefore ordinary updates cannot change it.

---

## Automatic Query Filters

`{App}DbContextBase.OnModelCreating` ends with `ApplyTenantQueryFilters<TenantId>(modelBuilder)` (EF.Data), which puts the named filter `DbContextBase.TenantQueryFilterName` (`"Tenant"`) on every root `ITenantEntity<TenantId>`; generate no filter loop. `IgnoreQueryFilters([DbContextBase.TenantQueryFilterName])` bypasses only this filter, for explicitly authorized cross-tenant paths (migrations, maintenance, a system repository for scheduler scans).

**The filter fails closed.** A context with `TenantId` set reads only that tenant; a context with no tenant reads **nothing** unless it is marked `AllTenants`; setting both throws `InvalidOperationException`. `AllTenants` is never inferred from a missing tenant, so every scoped context factory needs an explicit all-tenants rule:

```csharp
// Bootstrapper: a caller with no tenant reads every tenant only when it holds a cross-tenant role.
internal static bool AllowsAllTenants(IRequestContext<string, Guid?> rc) =>
    rc.TenantId is null && (rc.RoleExists(AppConstants.ROLE_SYSTEM) || rc.RoleExists(AppConstants.ROLE_GLOBAL_ADMIN));
```

Pass it as the last `DbContextScopedFactory` constructor argument on both the Trxn and Query factories ([../patterns/data-layer-wiring.md](../patterns/data-layer-wiring.md) section Database Context Pooling & Scoped Wrappers); `true` sets `AllTenants` and clears `TenantId` on the leased context. A caller that carries a tenant stays pinned to it, global admin included; a tenant-less caller with neither role reads nothing. Test harness contexts built outside DI set `AllTenants = true` explicitly, and tenant isolation is proven by the container-backed tests.

**Hand-written tenant filters** (a non-root entity, or a tenant id type with no conversion to the context's) keep the fail-closed shape `e => AllTenants || (TenantId != null && e.TenantId == TenantId)`, never a tenant-less pass-through. Never read `TenantId!.Value` there: EF parameterizes it eagerly despite the short-circuit and throws `InvalidOperationException: Nullable object must have a value` at query time when the context tenant is null.

## Tenant Input Models

The scaffold baseline is **server-authoritative with a DTO-carried field**:

- Keep `TenantId` on shared DTOs so read responses, mappers, validators, service/CQRS styles, and existing clients retain one compatible contract.
- Treat the inbound value as untrusted on create/update. Immediately compute `var authoritativeTenantId = RequestTenantId ?? Guid.Empty`, assign it to `dto.TenantId`, then validate and map with `authoritativeTenantId`.
- Never use `RequestTenantId ?? dto.TenantId`. Missing trusted tenant context must fail validation/authorization; a caller-provided value cannot establish ownership.
- Keep `ITenantBoundaryValidator` for loaded-entity access, explicit admin paths, and defense-in-depth reassignment checks.

**Why:** Stamping before validation and mapping makes every downstream check use the same server-owned tenant; validating first either rejects normal empty DTOs or evaluates an attacker-controlled value. Therefore every write path overwrites the DTO first.

Generic service/CQRS create and update paths are tenant-local even for global admins. A cross-tenant admin mutation is a separate, explicitly authorized path: call `EnsureCrossTenantRole`, load the target outside normal query filters, then stamp an update DTO from the loaded entity tenant. A cross-tenant create derives its target from a separately authorized admin contract, never the shared DTO field. Do not route either case through the ordinary request-context stamp.

---

## Request Context Contract

`IRequestContext<string, Guid?>` (EF.Common.Contracts) exposes `CorrelationId`, `AuditId`, `TenantId`, `Roles`, `RoleExists(role)`. Register EF.AspNetCore's claims-based implementation; generate no request-context middleware or factory:

```csharp
services.AddHttpRequestContext<Guid?>(
    value => Guid.TryParse(value, out var tenantId) ? tenantId : null,
    options =>
    {
        options.SystemAuditId = AppConstants.SYSTEM_USER_ID;
        options.SystemRoles = [AppConstants.ROLE_SYSTEM];
    });
```

- HTTP path: audit id from `oid`, then the name identifier, then `sub`; tenant from `tenant_id`; roles from role claims. An unauthenticated request gets no tenant and no roles.
- No-request path (message consumers, scheduled jobs, Functions triggers): the explicit system context - no tenant, `SystemAuditId`, and every role in `SystemRoles`.
- Every `SystemRoles` entry is stripped from an inbound token, so a token can never claim `System`.

## System Identity Across Tenants

**EF.Tenancy lets only a cross-tenant role past the tenant boundary, so the background system identity crosses tenants by role, never by a hand-built context.** Configure both lists together:

```csharp
services.AddTenancy(o => o.CrossTenantRoles = [AppConstants.ROLE_GLOBAL_ADMIN, AppConstants.ROLE_SYSTEM]);
// and, above: HttpRequestContextOptions.SystemRoles = [AppConstants.ROLE_SYSTEM]
```

The no-request context then carries `System`, `EnsureTenantBoundary` / `EnsureCrossTenantRole` / `EnforceTenantFilter` admit it, and `AllowsAllTenants` marks its contexts all-tenants. It acts for the tenant the data names; it must not borrow a user identity, which would pin background reads to one tenant through the query filter and attribute background writes to that user.

---

## Tenant Boundary Validator

`ITenantBoundaryValidator` / `TenantBoundaryValidator` is EF.Tenancy's stateless singleton (`AddTenancy`; [../support/ef-packages-optional.md](../support/ef-packages-optional.md) section Tenancy); generate no validator, helper or logging-extension class. Its checks, each returning `Result`:

1. `EnsureTenantBoundary(callerTenantId, callerRoles, entityTenantId, operation, entityName, entityId)`: a cross-tenant role passes; no roles, a global (null-tenant) entity or a tenant mismatch fail with `tenant.forbidden`.
2. `EnsureCrossTenantRole(callerRoles, operation)`: `tenant.forbidden` unless the caller holds a role in `CrossTenantRoles`.
3. `PreventTenantChange(existingTenantId, incomingTenantId, entityName, entityId)`: `tenant.change` when the ids differ.
4. `EnforceTenantFilter(filter, callerTenantId, callerRoles, operation)`: a cross-tenant caller gets the filter back untouched; any other caller gets a filter (created when null) forced to its tenant, and a non-cross-tenant caller with no tenant throws `UnauthorizedAccessException`. The app's `DefaultSearchFilter` implements `ITenantScopedFilter`.

Violations are logged as source-generated security events 4100-4104 (no roles, global entity, mismatch, tenant change, filter manipulation).

---

## Service Usage Rules

For entity reads/writes:

1. load entity (or query projection),
2. enforce `EnsureTenantBoundary(...)`,
3. continue only on success.

For searches:

- `request.Filter = tenantBoundaryValidator.EnforceTenantFilter(request.Filter, RequestTenantId, RequestRoles, "{Entity}Search")` before querying; the validator logs a supplied foreign tenant,
- never trust client-supplied tenant filter as-is.

For updates:

- stamp the request-context tenant before validation,
- after loading and boundary-checking the entity, call `PreventTenantChange(...)` against the stamped value as a defense-in-depth invariant,
- never restore or fall back to the original payload tenant,
- keep generic updates tenant-local; use the explicit admin path above for authorized cross-tenant mutation.

---

## API and Route Considerations

- Tenant-scoped APIs may include `tenantId` in route, but the route value does not establish ownership.
- Apply route-tenant vs claim-tenant policy (`TenantMatch`) at gateway/API boundary.
- Keep cross-tenant endpoints clearly separated and admin-guarded; role membership alone never turns the generic write endpoint into a cross-tenant mutation path.

---

## Data-Access Performance Rule

Tenant-owned entities use the tenant-first key `(TenantId, Id)` from `TenantEntityTypeConfiguration`, so one tenant's rows are a key range; every secondary index leads with `TenantId` ([../templates/ef-configuration-template.md](../templates/ef-configuration-template.md)).

---

## Testing Expectations

Minimum test matrix:

1. same-tenant access succeeds,
2. cross-tenant access is rejected,
3. global-admin cross-tenant access succeeds only on explicitly allowed paths (read-only by default),
4. forged create/update DTO `TenantId` is overwritten by request-context tenant before validation/mapping,
5. missing request-context tenant fails even when the DTO supplies a non-empty tenant,
6. tenant-change attempts fail.

Drive case 3 with the role claim, never a test-only header. Assert the claim type as well as the outcome: a bare `"roles"` claim leaves roles empty and the bypass never fires ([identity-management.md](identity-management.md) section Claim-type contract), which makes a negative test pass for the wrong reason. Test shapes: [testing.md](testing.md).

---

## Verification

- [ ] tenant entities implement `ITenantEntity<TenantId>`
- [ ] DbContext calls `ApplyTenantQueryFilters<TenantId>`; both scoped context factories pass the `AllowsAllTenants` rule
- [ ] `AddHttpRequestContext` resolves tenant/roles from claims; `SystemRoles` and `CrossTenantRoles` both include the system role
- [ ] EF.Tenancy `ITenantBoundaryValidator` is used in service operations; no app validator class
- [ ] DTO retains `TenantId`, but create/update flows overwrite it from request context before validation/mapping
- [ ] no write path uses `RequestTenantId ?? dto.TenantId` or otherwise falls back to payload tenant
- [ ] cross-tenant access is explicit and limited, derived from a `CrossTenantRoles` role via `EnsureCrossTenantRole(...)`
- [ ] no request header, query parameter, or env flag bypasses tenant filtering
- [ ] generic create/update paths remain tenant-local; any cross-tenant admin mutation has a separate authorization contract
- [ ] tests cover same-tenant, cross-tenant, admin-bypass, forged-payload, and missing-context scenarios
- [ ] cross-check with [application-layer.md](application-layer.md) and [domain-model.md](domain-model.md)
