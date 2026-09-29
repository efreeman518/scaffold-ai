# Structure Validator Template

| | |
|---|---|
| **File** | `Application.Services/Rules/{Entity}StructureValidator.cs` |
| **Depends on** | [data-mapping-template](data-mapping-template.md) |
| **Referenced by** | [service-template](service-template.md), [application-layer.md](../skills/application-layer.md) |

## Purpose

Validates DTO structure (required fields, string lengths, enum ranges, child collection constraints) **before** domain factory/update calls. Static class - no DI registration needed.

Returns `Result<{Entity}Dto>` so services can short-circuit on invalid input without touching the domain layer.

> **Multi-tenant toggle:** the common checks are `EntityDtoRules.ValidateCreate` / `ValidateUpdate` (EF.Common.Contracts), which constrain on `ITenantEntityDto` and fail with `dto.required`, `tenant.required` or `id.required`. Generate no shared `StructureValidators` class. For single-tenant scaffolds the DTO does not implement `ITenantEntityDto`: replace the common call with a null check (and an `Id` check on update).

## Template

### Per-Entity Validator (Application.Services/Rules/{Entity}StructureValidator.cs)

Delegates common checks to `EntityDtoRules`, then adds entity-specific field validation using `DomainConstants`.

```csharp
// File: Application.Services/Rules/{Entity}StructureValidator.cs
using Application.Models;
using Domain.Shared.Constants;
using EF.Common.Contracts;
using EF.Domain.Contracts;

namespace Application.Services.Rules;

/// <summary>
/// Validates {Entity}Dto structure before domain operations.
/// </summary>
internal static class {Entity}StructureValidator
{
    public static Result<{Entity}Dto> ValidateCreate({Entity}Dto dto)
    {
        // Common checks (null, TenantId)
        var common = EntityDtoRules.ValidateCreate(dto);
        if (common.IsFailure) return Result<{Entity}Dto>.Failure(common.Errors);

        var errors = new List<DomainError>();

        // Entity-specific field checks
        if (string.IsNullOrWhiteSpace(dto.Name))
            errors.Add(DomainError.Create("{Entity} name is required."));

        if (dto.Name?.Length > DomainConstants.RULE_DEFAULT_NAME_LENGTH_MAX)
            errors.Add(DomainError.Create($"{Entity} name cannot exceed {DomainConstants.RULE_DEFAULT_NAME_LENGTH_MAX} characters."));

        if (dto.Description?.Length > DomainConstants.RULE_DEFAULT_DESCRIPTION_LENGTH_MAX)
            errors.Add(DomainError.Create($"Description cannot exceed {DomainConstants.RULE_DEFAULT_DESCRIPTION_LENGTH_MAX} characters."));

        return errors.Count > 0
            ? Result<{Entity}Dto>.Failure(errors)
            : Result<{Entity}Dto>.Success(dto);
    }

    public static Result<{Entity}Dto> ValidateUpdate({Entity}Dto dto)
    {
        // Common checks (null, Id, TenantId)
        var common = EntityDtoRules.ValidateUpdate(dto);
        if (common.IsFailure) return Result<{Entity}Dto>.Failure(common.Errors);

        var errors = new List<DomainError>();

        // Reuse shared field checks
        if (string.IsNullOrWhiteSpace(dto.Name))
            errors.Add(DomainError.Create("{Entity} name is required."));

        if (dto.Name?.Length > DomainConstants.RULE_DEFAULT_NAME_LENGTH_MAX)
            errors.Add(DomainError.Create($"{Entity} name cannot exceed {DomainConstants.RULE_DEFAULT_NAME_LENGTH_MAX} characters."));

        if (dto.Description?.Length > DomainConstants.RULE_DEFAULT_DESCRIPTION_LENGTH_MAX)
            errors.Add(DomainError.Create($"Description cannot exceed {DomainConstants.RULE_DEFAULT_DESCRIPTION_LENGTH_MAX} characters."));

        return errors.Count > 0
            ? Result<{Entity}Dto>.Failure(errors)
            : Result<{Entity}Dto>.Success(dto);
    }
}
```

## Rules

- **Static class** - no DI registration. Call directly: `{Entity}StructureValidator.ValidateCreate(dto)`.
- **Delegate common checks** - Per-entity validators call `EntityDtoRules.ValidateCreate/ValidateUpdate` first for null, TenantId, and Id checks. Only add entity-specific rules after.
- Keep validations purely structural (field presence, length, range). Domain invariants belong on the aggregate ([../skills/domain-model.md](../skills/domain-model.md) section Domain Rules). Entry-point validators can be bypassed; factories and domain methods are shared across API, CQRS, jobs, messages, and tests, so invariants need one domain-owned enforcement boundary.
- **Use `DomainConstants`** for string length limits - single source of truth shared with EF configuration and domain `Valid()`. Do not use magic numbers or contextual tokens like `{NameMaxLength}`.
- Provide separate `ValidateCreate` and `ValidateUpdate` methods - update requires `Id` (via `EntityDtoRules.ValidateUpdate`), create may have different required fields.
- Return all errors at once (don't short-circuit on first failure) so the caller gets a complete validation report.
- Add or remove validated properties to match the entity's DTO - `dto.Description` is shown as an example; adjust to your entity's actual fields.

## Verification Checklist

- [ ] No app `StructureValidators` class; per-entity validator delegates common checks to `EntityDtoRules` first
- [ ] `ValidateCreate` checks all required fields for new entity creation
- [ ] `ValidateUpdate` requires `Id` and validates mutable fields
- [ ] String length limits use `DomainConstants` - single source of truth with EF config and domain `Valid()`
- [ ] Returns `Result<{Entity}Dto>` consistent with service layer pattern
- [ ] Service template calls `ValidateCreate`/`ValidateUpdate` before domain operations
- [ ] No domain logic in validator - structural checks only
