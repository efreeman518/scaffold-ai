# Updater Template

| | |
|---|---|
| **File** | `Infrastructure.Repositories/Updaters/{Entity}Updater.cs` |
| **Depends on** | [entity-template](entity-template.md), [data-mapping-template](data-mapping-template.md) |
| **Referenced by** | [repository-template](repository-template.md) |

## File: Infrastructure/Repositories/Updaters/{Entity}Updater.cs

The graph-sync **always lives in its own `internal static {Root}Updater` file** under `Infrastructure.Repositories/Updaters/`, as a `this {Project}DbContextTrxn db` extension method - never inlined into the repository. `{Root}RepositoryTrxn.UpdateFromDto` collapses to a one-line `=> DB.UpdateFromDto(entity, dto, relatedDeleteBehavior)` delegate, so the repo stays "load-with-includes + delegate" only. The extension shape is what gives the sync access to `db.Delete()` for explicit EF change-tracker removal of orphaned children. (This is behavior-preserving and test-safe: handler/service tests mock `I{Root}RepositoryTrxn`, not the updater.)

> **Generation gotcha - the standalone updater MUST declare `using EF.Data;`.** `db.Delete(toRemove)` (used in every `removeFunc`) is an **extension method in the `EF.Data` namespace**. While the logic sits inline in the repository it compiles without an extra import (the repo already imports `EF.Data` for `RepositoryBase`), but once it moves to a standalone `{Root}Updater.cs` the import must be present or the file fails with **CS1061** (`'{Project}DbContextTrxn' does not contain a definition for 'Delete'`). Do not let a using-pruner drop it - it looks unused to a naive scan but is required for the `db.Delete` call.

```csharp
using EF.Data;            // REQUIRED: db.Delete(...) is an extension method in this namespace (see gotcha above)
using EF.Data.Contracts;
using EF.Domain;
using EF.Domain.Contracts;

namespace Infrastructure.Repositories.Updaters;

internal static class {Entity}Updater
{
    /// <summary>
    /// Updates scalar properties then syncs child collections via railway pattern.
    /// Extension on DbContextTrxn for access to db.Delete().
    /// </summary>
    public static Result<{Entity}> UpdateFromDto(
        this {Project}DbContextTrxn db,
        {Entity} entity,
        {Entity}Dto dto,
        RelatedDeleteBehavior relatedDeleteBehavior = RelatedDeleteBehavior.None)
    {
        return entity.Update(
            name: dto.Name,
            description: dto.Description)
        .Bind(updatedEntity => Result.Combine(
            // Sync {ChildEntities} collection (owned, 1:N). The create/remove callbacks route through
            // the aggregate root's own Add{ChildEntity} / Remove{ChildEntity} methods - never raw
            // collection .Add() / .Remove() - so the root stays the single owner of its invariants
            // (GR-15). New children added to the tracked parent are inferred as Added on save because
            // the key is ValueGeneratedNever (see "New children and EF Added state" note below); removeFunc
            // calls db.Delete() so EF detaches the orphaned row from the change tracker.
            CollectionUtility.SyncCollectionWithResult<{ChildEntity}, {ChildEntity}Dto, Guid>(
                updatedEntity.{ChildEntities},
                dto.{ChildEntities} ?? [],
                e => e.Id,
                i => i.Id,
                incomingDto => updatedEntity.Add{ChildEntity}(incomingDto.Name).Map(_ => Unit.Value),
                (existing, incomingDto) => existing.Update(incomingDto.Name).Map(_ => Unit.Value),
                toRemove =>
                {
                    if (relatedDeleteBehavior == RelatedDeleteBehavior.None) return Result.Ok();
                    updatedEntity.Remove{ChildEntity}(toRemove);
                    db.Delete(toRemove);
                    return Result.Ok();
                }
            ),
            // Sync Tags collection (M:N via junction entity) through the root's AssociateTag / RemoveTag.
            CollectionUtility.SyncCollectionWithResult<{Entity}Tag, TagDto, Guid>(
                updatedEntity.{Entity}Tags,
                dto.Tags ?? [],
                e => e.TagId,
                i => i.Id,
                incomingDto => updatedEntity.AssociateTag(TagId.From(incomingDto.Id!.Value)).Map(_ => Unit.Value),
                // updateFunc omitted - junction has no updatable properties
                removeFunc: toRemove =>
                {
                    if (relatedDeleteBehavior == RelatedDeleteBehavior.None) return Result.Ok();
                    updatedEntity.RemoveTag(toRemove);
                    db.Delete(toRemove);
                    return Result.Ok();
                }
            ))
            .Map(_ => updatedEntity)
        );
    }
}
```

## CollectionUtility.SyncCollectionWithResult (from EF.Domain)

Synchronizes two collections; every callback returns `Result<Unit>` and failures aggregate through `Result.Combine`.

```csharp
namespace EF.Domain;

public static class CollectionUtility
{
    /// <summary>
    /// Synchronize a database collection with an incoming DTO collection.
    /// Matches by key; creates new items, updates matching items, removes missing items.
    /// </summary>
    /// <typeparam name="TEntity">Entity type in the database collection.</typeparam>
    /// <typeparam name="TDto">DTO type in the incoming collection.</typeparam>
    /// <typeparam name="TId">Key type (must be struct + IEquatable).</typeparam>
    /// <param name="dbCollection">The entity's navigation collection (ICollection).</param>
    /// <param name="dtoCollection">The incoming DTOs with desired state.</param>
    /// <param name="getDbId">Key selector for entity.</param>
    /// <param name="getDtoId">Key selector for DTO (returns TId? - null/default = new item).</param>
    /// <param name="createFunc">Creates entity from DTO. Must add to collection if successful.</param>
    /// <param name="updateFunc">Optional. Updates existing entity from DTO.</param>
    /// <param name="removeFunc">Optional. Removes entity from collection. If null, no deletes occur (partial update).</param>
    /// <param name="failFast">If true, stops on first failure. Default: false.</param>
    public static Result<Unit> SyncCollectionWithResult<TEntity, TDto, TId>(
        ICollection<TEntity> dbCollection,
        ICollection<TDto> dtoCollection,
        Func<TEntity, TId> getDbId,
        Func<TDto, TId?> getDtoId,
        Func<TDto, Result<Unit>> createFunc,
        Func<TEntity, TDto, Result<Unit>>? updateFunc = null,
        Func<TEntity, Result<Unit>>? removeFunc = null,
        bool failFast = false)
        where TId : struct, IEquatable<TId>
    { ... }
}
```

### Key Behaviors

- **Create:** When `getDtoId` returns null, default, or a key not found in `dbCollection`, calls `createFunc`. The create lambda must add the new entity to the parent's collection itself.
- **Update:** When a matching key exists in both collections, calls `updateFunc` (if provided). The matched entity is removed from the internal lookup so it won't be deleted.
- **Remove:** After processing all DTOs, any entities remaining in the lookup (not matched) are passed to `removeFunc` (if provided). If `removeFunc` is null, unmatched entities are left alone (partial update mode).
- **Error aggregation:** All results are combined via `Result.Combine()` (`ValidationError` issues merge; any other failure wins first). With `failFast: true`, stops on first failure.

### Parameter Order Mnemonic

`db, dto, dbKey, dtoKey, create, update?, remove?, failFast?`

## Patterns

### Owned 1:N Child (Comments, ChecklistItems)

All three callbacks needed - create routes through the root's `AddComment`, update delegates to the child's own method, remove routes through `RemoveComment` then `db.Delete()` to mark the orphan for EF deletion. Never call `collection.Add()` / `collection.Remove()` directly here - that bypasses the aggregate root (GR-15):

```csharp
CollectionUtility.SyncCollectionWithResult<Comment, CommentDto, Guid>(
    updatedEntity.Comments,
    dto.Comments ?? [],
    e => e.Id,
    i => i.Id,
    createFunc: incomingDto => updatedEntity.AddComment(incomingDto.Body).Map(_ => Unit.Value),
    updateFunc: (existing, incomingDto) => existing.Update(incomingDto.Body).Map(_ => Unit.Value),
    removeFunc: toRemove =>
    {
        if (relatedDeleteBehavior == RelatedDeleteBehavior.None) return Result.Ok();
        updatedEntity.RemoveComment(toRemove);
        db.Delete(toRemove);
        return Result.Ok();
    });
```

> The root's `AddComment(string body)` runs `Comment.Create` internally and returns `Result<Comment>`; only the root method mutates the collection.

#### New children and EF Added state

A new child added to the **already-tracked, persisted** parent (the Update path) must be saved as an `INSERT`. EF decides Added-vs-Modified for a navigation-added child partly from the key, so this hinges on how the key is configured:

- **Primary mitigation (required baseline):** the key is `ValueGeneratedNever()` on `EntityBase.Id`, set by the package `TenantEntityTypeConfiguration` every tenant-owned config derives from (the scaffold mandates this - see [ef-configuration-template.md](ef-configuration-template.md) and [../skills/data-persistence.md](../skills/data-persistence.md)). Because the scaffold's identity is a client-set `Guid.CreateVersion7()`, `ValueGeneratedNever` is the *correct* model, not a workaround: EF then treats the key as application-assigned and infers the navigation-added child as `Added`. With this in place the clean `createFunc` above (no `db.Add`) is correct, and it covers **every** navigation-add path - the updater, nested sub-resource handlers, any aggregate mutation - in one line.
- **Residual risk:** the protection is the *global* `ValueGeneratedNever`. It silently breaks if someone adds a child entity whose EF config does not derive from `TenantEntityTypeConfiguration` / skips `base.Configure(builder)`, or a non-tenant config that omits `ValueGeneratedNever()`. New child configs MUST derive from the package base.
- **If the key is store-generated** (no `ValueGeneratedNever`, e.g. an int identity or a deviating config - a GR-16 deviation that must be an explicit, recorded developer request), the navigation-add is inferred as `Modified` and `SaveChanges` emits `UPDATE ... WHERE Id=@id AND Version=@version` against a non-existent row -> `DbUpdateConcurrencyException`. In that case `createFunc` must `db.Add(newChild)` explicitly (the updater is a `DbContextTrxn` extension, so `db` is in scope; `Add` is a built-in `DbContext` method, no extra using), and nested child handlers must do the same. Prefer the client-generated default over scattering `db.Add` - `ValueGeneratedNever` covers all paths; `db.Add` only covers the one call site you remember.
- **Test it:** only a real `repo.UpdateFromDto(reloadedParent, dto)` round-trip that adds a NEW child exercises this state inference. A test that seeds children via `db.Set<Child>().Add(...)` bypasses it and masks both the bug and a regression of the `ValueGeneratedNever` baseline. Generate the `{Entity}_UpdateFromDto_AddsChildToReloadedParent_AgainstRealSql` integration test for this - see [../templates/test-templates-integration.md](../templates/test-templates-integration.md) coverage matrix (it is a required row for any aggregate with an updater, not a substitute for `{Entity}_WithChildren_PersistsCorrectly`).

#### createFunc must apply ALL DTO fields

Domain factory / `Add*` methods often take a minimal field set (e.g., `AddChecklistItem(title, sortOrder)` - no `IsCompleted`). If the DTO carries additional state (a pre-checked checkbox buffered in a create form, a status flag, a completion date), the `createFunc` must follow the add with an `Update` call on the returned child to apply those fields. Otherwise the UI's single-payload aggregate save silently drops them on newly-inserted children. Pattern:

```csharp
createFunc: incomingDto =>
{
    var result = updatedEntity.AddChecklistItem(incomingDto.Title, incomingDto.SortOrder);
    // AddChecklistItem has no IsCompleted arg - apply it via the child's Update() so buffered
    // "checked" state isn't lost when the parent + children are POSTed together.
    if (result.TryGetValue(out ChecklistItem? added) && incomingDto.IsCompleted) added.Update(isCompleted: true);
    return result.Map(_ => Unit.Value);
}
```

Rule: for every field the DTO can carry that the root's add method doesn't accept, the `createFunc` must call the corresponding `Update` on the returned child immediately after adding it.

### M:N Junction (Tags via TaskItemTag)

Only create + remove needed - junction entities have no updatable properties. The root exposes `AssociateTag` (idempotent) and `RemoveTag`; match on the foreign key (TagId), not the junction entity's own Id:

```csharp
CollectionUtility.SyncCollectionWithResult<TaskItemTag, TagDto, Guid>(
    updatedEntity.TaskItemTags,
    dto.Tags ?? [],
    e => e.TagId.Value,     // LINQ-to-objects sync: unwrap typed FK to match DTO Guid
    i => i.Id,
    createFunc: incomingDto => updatedEntity.AssociateTag(TagId.From(incomingDto.Id!.Value)).Map(_ => Unit.Value),
    removeFunc: toRemove =>
    {
        if (relatedDeleteBehavior == RelatedDeleteBehavior.None) return Result.Ok();
        updatedEntity.RemoveTag(toRemove);
        db.Delete(toRemove);
        return Result.Ok();
    });
    // updateFunc omitted - no properties to update on junction
```

### Partial Update (no removes)

Omit `removeFunc` to allow adding/updating without deleting unmatched entities:

```csharp
CollectionUtility.SyncCollectionWithResult<Address, AddressDto, Guid>(
    updatedEntity.Addresses,
    dto.Addresses ?? [],
    e => e.Id,
    i => i.Id,
    createFunc: incomingDto => { ... },
    updateFunc: (existing, incomingDto) => existing.Update(incomingDto.Street, incomingDto.City).Map(_ => Unit.Value));
    // removeFunc omitted - unmatched addresses are kept
```

## Usage in Repository

```csharp
// In {Entity}RepositoryTrxn - delegates to DbContext extension method:
public Result<{Entity}> UpdateFromDto({Entity} entity, {Entity}Dto dto,
    RelatedDeleteBehavior relatedDeleteBehavior = RelatedDeleteBehavior.None) =>
    DB.UpdateFromDto(entity, dto, relatedDeleteBehavior);
```

## Usage in Service (via .Bind chaining)

```csharp
// CreateAsync - chain entity creation with child sync:
var result = dto.ToEntity(tenantId)
    .Bind(entity => repoTrxn.UpdateFromDto(entity, dto));

// UpdateAsync - after updating scalar properties:
if (repoTrxn.UpdateFromDto(entity, dto).TryGetValue(out Error? syncError)) return syncError;
```

## Callback Types

Every callback is `Func<..., Result<Unit>>`. Domain methods return `Result<T>` (`Create`, `Update`, `Add*`, `AssociateTag`), so adapt with `.Map(_ => Unit.Value)`; `Remove*` already returns `Result<Unit>`, and a no-op remove returns `Result.Ok()`. Result idioms: [ef-packages-reference.md](../support/ef-packages-reference.md).

## Notes

- Updater is **always a standalone `internal static {Root}Updater` file** with a `this {Project}DbContextTrxn db` extension method - never inlined into the repository. The extension shape gives access to `db.Delete()` for EF change-tracker removal
- The standalone updater file **MUST** include `using EF.Data;` - `db.Delete(...)` is an extension method there; omitting it compiles inline but fails with CS1061 in the extracted file
- Repository delegates via a one-line `UpdateFromDto(...) => DB.UpdateFromDto(entity, dto, relatedDeleteBehavior)` where `DB` is the `RepositoryBase` context property; the repo keeps only load-with-includes + this delegate
- Uses railway `.Bind()` flow: `entity.Update(...).Bind(updatedEntity => Result.Combine(...).Map(_ => updatedEntity))` - parent update errors short-circuit child syncs
- `RelatedDeleteBehavior` gates whether `removeFunc` actually deletes: `None` = no-op, `RelationshipOnly` / `RelationshipAndEntity` = `db.Delete(toRemove)` + collection remove
- **CRITICAL:** Must call `db.Delete(toRemove)` in removeFunc, not just `collection.Remove()` - without explicit EF delete, orphaned children remain in DB when relationship isn't cascade-delete
- `dto.{ChildEntities} ?? []` - null-coalesce to empty array so `SyncCollectionWithResult` gets a valid collection (null DTO collection = no changes, empty = remove all)
- All callbacks return `Result<Unit>` (not void) - even remove returns `Result.Ok()`; see Callback Types
- Routes every child create/remove through the aggregate root's `Add*` / `Remove*` methods, never raw `collection.Add()` / `collection.Remove()` and never direct property mutation (GR-15). The root owns its invariants; the updater only resolves the desired-state diff and gates hard deletes.
- The root's `Add*` method is what puts the new child into the navigation collection - `SyncCollectionWithResult` does not do this automatically, so the `createFunc` must return the result of that `Add*` call (which has already added it), mapped to `Unit`
- **New children rely on `ValueGeneratedNever` for correct `Added` inference.** The package `TenantEntityTypeConfiguration` sets `ValueGeneratedNever()` on the key, so a navigation-added child on a tracked parent is saved as an `INSERT` (the clean `createFunc` above needs no `db.Add`). This covers all navigation-add paths. Only if the key is store-generated (deviating config) must `createFunc` `db.Add(newChild)` explicitly to avoid a `DbUpdateConcurrencyException`; `db.Add` is a built-in `DbContext` method (no using), safe because `createFunc` runs only for new children. See "New children and EF Added state" above. Cover the path with a `repo.UpdateFromDto(reloadedParent, dto)` round-trip test that adds a NEW child - not `db.Set<Child>().Add(...)`, which masks it.
- `getDtoId` returns `TId?` - null or default(TId) signals a new item (create path)
- Explicit generic type args (`<TEntity, TDto, TId>`) recommended when lambdas make inference ambiguous
