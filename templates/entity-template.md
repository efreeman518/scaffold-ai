# Entity Template

> **When to read:** Phase 5a, when generating a new entity class with private setters, factory `Create()`, and rule-based validation.
> **Skip if:** Entity already exists; modifying existing behavior only; non-entity domain work (value objects, domain services).

| | |
|---|---|
| **File** | `Domain.Model/Entities/{Entity}.cs` |
| **Depends on** | [domain-specification-schema.md](../ai/domain-specification-schema.md), [resource-implementation-schema.md](../ai/resource-implementation-schema.md) |
| **Referenced by** | [data-mapping-template](data-mapping-template.md), [ef-configuration-template](ef-configuration-template.md) |

> **Token vs interpolation:** inside a `$"..."` string, a `{Word}` that names an in-scope C# identifier is real interpolation - leave it verbatim. In `$"Cannot transition from {Status} to {target}."`, `{Status}` and `{target}` are the entity's property and the method parameter, while `{Entity}` on the same lines is a scaffold token. Rule: [../ai/placeholder-tokens.md](../ai/placeholder-tokens.md) section Disambiguating Tokens From Logging And Interpolation.

## File: Domain/Shared/Ids/DomainIds.cs

> **Centralized ID types - one file per bounded context, never scattered into individual entity files.**
> Define all domain ID structs here. `TenantId` is typically defined in a shared package; add it here only for apps that own their own tenant concept.

```csharp
using EF.Domain.Contracts;

namespace Domain.Shared.Ids;

public readonly record struct {Entity}Id(Guid Value) : IDomainId<{Entity}Id>
{
    public static {Entity}Id From(Guid value) => new(value);
    public static implicit operator Guid({Entity}Id id) => id.Value;
    public override string ToString() => Value.ToString();
}

// Repeat pattern for each entity ID in the bounded context:
// public readonly record struct {OtherEntity}Id(Guid Value) : IDomainId<{OtherEntity}Id> { ... }
```

---

## File: Domain/Model/Entities/{Entity}.cs

> **EntityBase properties (inherited, do NOT redefine):**
> - `{Entity}Id Id { get; init; }` - typed domain ID, client-generated via `Guid.CreateVersion7()` (set by the app, not the store; EF `ValueGeneratedNever()`), init-only
> - `long Version { get; set; }` - concurrency token, mapped by `RegisterVersionConcurrencyTokens()` and written by `DbContextBase` on save (1 after insert)
>
> `EntityBase<TId>` is the generic base where `TId : struct, IDomainId<TId>`. The typed `Id` property replaces the raw `Guid Id`.
>
> **Timestamps:** an entity that exposes `CreatedAtUtc` / `ModifiedAtUtc` implements `ITimestampedEntity` with `{ get; private set; }` properties; `DbContextBase` stamps them through the change tracker. **Do NOT inherit `AuditableBase<T>`** unless `CreatedBy` / `ModifiedBy` must live on the entity itself; the audit trail comes from the `AuditInterceptor`.
>
> **Domain events `[MESSAGING]`:** when the entity publishes integration events, it implements `IHasDomainEvents` over a private `DomainEventContainer` (EF.Domain) and raises each event from the factory or domain method that caused it. The EF.Data.Outbox staging interceptor drains `DomainEvents` in the same `SaveChanges` ([../skills/messaging.md](../skills/messaging.md) section Transactional Producer: Outbox). Event records live in `Domain.Shared` and derive from the closed base (same skill, section Event Boundary Rule): `public record {Entity}CreatedEvent(Guid {Entity}Id, Guid TenantId, string Name) : {Project}DomainEvent;`.

```csharp
using Domain.Shared;
using Domain.Shared.Constants;
using Domain.Shared.Ids;
using EF.Domain;
using EF.Domain.Contracts;

namespace Domain.Model;

public class {Entity} : EntityBase<{Entity}Id>, ITenantEntity<TenantId>, IHasDomainEvents  // [MULTI-TENANT] omit ITenantEntity<TenantId> for single-tenant; [MESSAGING] omit IHasDomainEvents without messaging
{
    // [MESSAGING] Buffered until the outbox staging interceptor drains them in SaveChanges.
    private readonly DomainEventContainer _domainEvents = new();
    public IReadOnlyCollection<IDomainEvent> DomainEvents => _domainEvents.Events;
    public void ClearDomainEvents() => _domainEvents.Clear();

    // ===== Factory Create - the ONLY way to create an instance =====
    public static Result<{Entity}> Create(Guid tenantId, string name, /* additional params */)
    {
        var entity = new {Entity}(TenantId.From(tenantId), name);  // wrap raw Guid on intake
        var validated = entity.Valid();
        if (validated.IsSuccess) entity._domainEvents.Raise(new {Entity}CreatedEvent(entity.Id.Value, tenantId, entity.Name)); // [MESSAGING]
        return validated;
    }

    // ===== Private constructor - enforces factory usage =====
    private {Entity}(TenantId tenantId, string name)
    {
        TenantId = tenantId;
        Name = name;
    }

    // ===== EF Core parameterless constructor =====
    private {Entity}() { }

    // ===== Properties - private setters enforce immutability outside domain methods =====
    public TenantId TenantId { get; init; }  // init for tenant (set once)
    public string Name { get; private set; } = null!;
    public {ValueObject}? {ValueObjectProperty} { get; private set; } // [VALUE-OBJECT] optional owned value object from domain spec
    public {Entity}Flags Flags { get; private set; } = {Entity}Flags.None;

    // ===== Navigation Properties - ICollection<T>, never List<T> =====
    public ICollection<{ChildEntity}> {ChildEntities} { get; private set; } = [];

    // ===== Update - returns Result for validation =====
    public Result<{Entity}> Update(string? name = null, {Entity}Flags? flags = null)
    {
        if (name is not null) Name = name;
        if (flags.HasValue) Flags = flags.Value;
        return Valid();
    }

    // ===== Child Collection Management =====
    public Result<{ChildEntity}> Add{ChildEntity}({ChildEntity} child)
    {
        var existing = {ChildEntities}.FirstOrDefault(c => c.Id == child.Id);
        if (existing != null) return existing;  // Idempotent

        {ChildEntities}.Add(child);
        return child;
    }

    public Result<Unit> Remove{ChildEntity}({ChildEntity} child)
    {
        {ChildEntities}.Remove(child);
        return Result.Ok();  // Desired-state: always succeeds
    }

    public Result<Unit> Remove{ChildEntity}(Guid id)
    {
        var child = {ChildEntities}.FirstOrDefault(c => c.Id.Value == id);  // unwrap for Guid comparison
        if (child != null) {ChildEntities}.Remove(child);
        return Result.Ok();  // Desired-state: always succeeds
    }

    // ===== Validation - called by Create() and Update() =====
    private Result<{Entity}> Valid()
    {
        var errors = new List<ValidationIssue>();

        if (TenantId.Value == Guid.Empty) errors.Add(new ValidationIssue("Tenant ID cannot be empty.", nameof(TenantId))); // [MULTI-TENANT]
        if (string.IsNullOrWhiteSpace(Name)) errors.Add(new ValidationIssue("Name is required.", nameof(Name)));
        if (Name?.Length < DomainConstants.RULE_DEFAULT_NAME_LENGTH_MIN)
            errors.Add(new ValidationIssue($"Name must be at least {DomainConstants.RULE_DEFAULT_NAME_LENGTH_MIN} characters.", nameof(Name)));
        if (Name?.Length > DomainConstants.RULE_DEFAULT_NAME_LENGTH_MAX)
            errors.Add(new ValidationIssue($"Name cannot exceed {DomainConstants.RULE_DEFAULT_NAME_LENGTH_MAX} characters.", nameof(Name)));

        return errors.Count > 0 ? new ValidationError(errors) : this;
    }
}
```

## File: Domain/Model/ValueObjects/{ValueObject}.cs

Generate value objects only when `.scaffold/domain-specification.yaml` declares `valueObjects`. Keep them immutable, domain-side, and free of EF/DTO concerns. Use factories returning `Result<T>` for validation instead of throwing expected domain failures.

```csharp
using EF.Domain.Contracts;

namespace Domain.Model.ValueObjects;

public sealed record {ValueObject}
{
    public string Value { get; }

    private {ValueObject}(string value)
    {
        Value = value;
    }

    public static Result<{ValueObject}> Create(string value) =>
        string.IsNullOrWhiteSpace(value)
            ? new ValidationError("{ValueObject} is required.", nameof(Value))
            : new {ValueObject}(value.Trim());

    public override string ToString() => Value;
}
```

### Composing a value object into the entity factory

VO `Create()` short-circuits on the first error (one `ValidationError`). The entity **aggregates** across VOs and primitives so the caller sees every field error in one pass. Use two VO construction paths:

- **Validating intake** (`Create` / `Update`): build the VO via `{ValueObject}.Create(raw)` and fold its issues into the same `List<ValidationIssue>` as the primitive checks; materialize the VO property only when the aggregate passes. Do this inside `Valid()` (which runs on both create and update) so both paths aggregate identically - keep the raw input as a backing field the constructor captures.
- **Non-validating materialization** (EF rehydration + internal reconstruction): add a `{ValueObject}.From(raw)` that skips validation and trusts stored data. EF and post-materialization code use `From`, never `Create`.

```csharp
// VO: validating Create for intake, non-validating From for EF/materialization
public static {ValueObject} From(string value) => new(value); // stored data assumed valid

// Entity Valid() folds the VO's issues into the aggregate (no short-circuit)
private Result<{Entity}> Valid()
{
    var errors = new List<ValidationIssue>();
    if (string.IsNullOrWhiteSpace(Name)) errors.Add(new ValidationIssue("Name is required.", nameof(Name)));

    var {vo} = {ValueObject}.Create({voRaw});   // {voRaw}: raw input captured at construction
    if ({vo} is ValidationError invalid) errors.AddRange(invalid.Issues);
    else {ValueObjectProperty} = {vo}.GetValueOrThrow();  // materialize only on success

    return errors.Count > 0 ? new ValidationError(errors) : this;
}
```

> **Child factory calls (cross-boundary):** When calling a child entity's factory that still accepts raw `Guid`, unwrap the typed ID:
> ```csharp
> {ChildEntity}.Create(TenantId.Value, Id.Value, body);
> ```
> These `.Value` unwraps are domain/post-materialization code. Do not copy this pattern into EF-translated predicates (`Where`, `Any`, `ListAsync`, search `QuerySpec`). In database predicates, build the typed ID outside the expression and compare the whole property, for example `e.TenantId == tenantId`.

## Critical domain-method rules

### `Update()` MUST re-validate (non-negotiable)

Every `Update()` ends with `return Valid();` - it returns `Result<T>`, never a bare `this`. Mutating fields and returning the entity without re-running `Valid()` lets an update persist invalid state (negative counters, blank required fields) that the factory would have rejected. If a generated `Update()` does not call `Valid()`, it is wrong.

```csharp
// WRONG - skips validation, can persist invalid state
public {Entity} Update(string? name = null) { if (name is not null) Name = name; return this; }

// RIGHT - re-validates, returns Result
public Result<{Entity}> Update(string? name = null)
{
    if (name is not null) Name = name;
    return Valid();
}
```

### Lifecycle status is a guarded `Transition`, never a settable `Update` field

When the domain spec declares a `stateMachine` for an entity, the status is **not** a parameter on `Update()`. Expose a dedicated `Transition(target)` that enforces allowed moves and keeps dependent fields aligned (a completion timestamp from the caller's `now`). A free-form `Update(status, ...)` lets callers jump to any state and bypass the lifecycle. Use an explicit transition matrix inside the aggregate; no separate rule class.

```csharp
public Result<{Entity}> Transition({Entity}Status target, DateTimeOffset now)
{
    if (!IsValidTransition(Status, target))  // a rule on a valid request: RuleError, 422
        return new RuleError($"Cannot transition from {Status} to {target}.", "{entity}.status_transition");
    Status = target;
    if (target == {Entity}Status.Completed) CompletedDate = now;   // no ambient clock (domain-model.md section Clock)
    return this;
}

private static bool IsValidTransition({Entity}Status current, {Entity}Status target) =>
    (current, target) switch { /* explicit allowed pairs */ _ => false };
```

Reference: `TaskItem.TransitionStatus` + `IsValidTransition` in the reference app. (Use a non-flags `enum` status for a state machine; `{Entity}Flags` is for independently combinable booleans, not a lifecycle.)

### `ValidationIssue` / `RuleError` argument order (GR-14)

Both take the **human message FIRST**: `new ValidationIssue(message, field, code)`, `new RuleError(message, code)`. Verify against the package rather than inferring from names. The silent bug is reversed arguments:

```csharp
// WRONG - code key surfaces as the user-facing message
new RuleError("task.status_transition", "Cannot transition from Open to Done.")

// RIGHT - message first; a ValidationIssue names its field
new RuleError("Cannot transition from Open to Done.", "task.status_transition")
new ValidationIssue("Tenant ID is required.", nameof(TenantId))
```

## File: Domain/Shared/{Entity}Flags.cs

```csharp
namespace Domain.Shared;

[Flags]
public enum {Entity}Flags
{
    None = 0,
    IsInactive = 1 << 0,
    IsArchived = 1 << 1,
    IsSuspended = 1 << 2,
    // Add domain-specific flags
}
```

## Polymorphic Join Entity Warning

> **CRITICAL:** When an entity participates as a polymorphic owner (e.g., both `TaskItem` and `Comment` can own `Attachment`), do NOT add `ICollection<PolymorphicChild>` navigation properties to the parent entities. EF auto-generates a real FK constraint from each navigation, creating multiple conflicting FKs on the shared `OwnerId` column. Instead, query polymorphic children explicitly via `OwnerType` + `OwnerId`.

## Polymorphic Ordered Block Note (Optional)

For playlist-driven content entities, model ordered blocks with:

- explicit `Position`
- block discriminator/type
- payload invariants enforced in `Valid()`/domain rules (for example text block requires text, image block requires image URL)

When the child collection property name differs from `{ChildEntities}`, use the explicit `{Children}` token from [placeholder-tokens.md](../ai/placeholder-tokens.md).

## File: Domain/Model/Entities/{Parent}{Related}.cs (Join Entity)

Default many-to-many join entity pattern - inherits `EntityBase<{Parent}{Related}Id>` with FK on both sides. Only use a pure composite-key join (no `EntityBase`) when confident the join will remain a pure association.

```csharp
using Domain.Shared.Ids;
using EF.Domain;

namespace Domain.Model;

public class {Parent}{Related} : EntityBase<{Parent}{Related}Id>
{
    public static Result<{Parent}{Related}> Create(Guid tenantId, Guid parentId, Guid relatedId) =>
        new {Parent}{Related}(TenantId.From(tenantId), {Parent}Id.From(parentId), {Related}Id.From(relatedId));

    private {Parent}{Related}(TenantId tenantId, {Parent}Id parentId, {Related}Id relatedId)
    {
        TenantId = tenantId;
        {Parent}Id = parentId;
        {Related}Id = relatedId;
    }

    private {Parent}{Related}() { }

    public TenantId TenantId { get; init; }
    public {Parent}Id {Parent}Id { get; init; }
    public {Related}Id {Related}Id { get; init; }

    public {Parent} {Parent} { get; private set; } = null!;
    public {Related} {Related} { get; private set; } = null!;

    // Add properties as needed (e.g., AssignedDate, SortOrder, CreatedBy)
}
```

**EF Configuration:**
```csharp
// Unique constraint on FK pair (PK is Id from EntityBase)
builder.HasIndex(e => new { e.{Parent}Id, e.{Related}Id }).IsUnique();

builder.HasOne(e => e.{Parent})
    .WithMany(e => e.{Children})
    .HasForeignKey(e => e.{Parent}Id)
    .OnDelete(DeleteBehavior.Cascade);

builder.HasOne(e => e.{Related})
    .WithMany()
    .HasForeignKey(e => e.{Related}Id)
    .OnDelete(DeleteBehavior.Restrict);
```

`{Children}` here is the parent's collection of join entities, named as the plural of the join entity `{Parent}{Related}`: `TaskItem` + `Tag` -> `TaskItemTags`, `TaskItem` + `Category` -> `TaskItemCategories`. Pluralize per [placeholder-tokens.md](../ai/placeholder-tokens.md) Derivation Rule 5, never by appending a literal `s`.

---

**TaskFlow proof (local):** `../scaffold-proof/src/Domain/TaskFlow.Domain.Model/TaskItem/TaskItem.cs` (full entity with factory + rules), and the `Category/`, `Tag/`, `Comment/`, `ChecklistItem/` sibling folders for relationship variants
**TaskFlow proof (remote fallback):** <https://github.com/efreeman518/scaffold-proof/blob/main/src/Domain/TaskFlow.Domain.Model/TaskItem/TaskItem.cs>
