# EF Configuration Template

| | |
|---|---|
| **File** | `Infrastructure.Data/Configuration/{Entity}Configuration.cs` |
| **Depends on** | [entity-template](entity-template.md) |
| **Referenced by** | [data-persistence.md](../skills/data-persistence.md), [repository-template](repository-template.md) |

## Key and Concurrency Mapping (package)

The key, `Id` value generation, `TenantId` requirement and the `Version` concurrency token come from EF.Data; generate no app-level base configuration.

- **Tenant-owned entity:** derive from `TenantEntityTypeConfiguration<TEntity, TId, TTenantId>` (`EF.Data.Configurations`) and call `base.Configure(builder)` first. It maps the tenant-first key `(TenantId, Id)` - one tenant's rows are a key range - with `Id` `ValueGeneratedNever()` and `TenantId` required. It makes no clustering or other provider call.
- **Non-tenant entity:** implement `IEntityTypeConfiguration<TEntity>` with `builder.HasKey(e => e.Id)` and `builder.Property(e => e.Id).ValueGeneratedNever()`.
- **`Version`:** `{App}DbContextBase.OnModelCreating` ends with `modelBuilder.RegisterVersionConcurrencyTokens()`, which maps `Version` on every `IVersionedEntity`; entity configs never mention it. `DbContextBase` writes it on save (1 after insert, incremented on every modified save), with the timestamps of an `ITimestampedEntity`.
- **Tenant filter:** `ApplyTenantQueryFilters<TenantId>(modelBuilder)`, also at the end of `OnModelCreating` ([../skills/multi-tenant.md](../skills/multi-tenant.md)).

> **`Version` is provider-neutral.** The same mapping works on SQL Server and PostgreSQL; no provider maps `rowversion` or `xmin`.
>
> **`ValueGeneratedNever()` is load-bearing for aggregate child inserts, not just a perf detail (GR-16).** It tells EF the `Guid.CreateVersion7()` key is application-assigned - the scaffold default. With it, a NEW child added to an already-tracked parent through a navigation collection (the aggregate Update path / `{Root}Updater`) is correctly inferred as `Added` and saved as an `INSERT`. Without it, EF treats the non-default key as store-generated, infers the navigation-added child as `Modified`, and `SaveChanges` emits an `UPDATE` against a non-existent row -> `DbUpdateConcurrencyException`. Therefore **every** entity config derives from `TenantEntityTypeConfiguration` (or sets `ValueGeneratedNever()` itself when non-tenant) and calls `base.Configure(builder)` - a child config that skips it silently reintroduces this bug for that entity. DB/store-generated keys are a deviation requiring an explicit developer request recorded in `.scaffold/DESIGN-DECISIONS.md` (GR-16); when chosen, the `{Root}Updater` createFunc must `db.Add(child)`. See [updater-template.md](updater-template.md) section New children and EF Added state.

## File: Infrastructure/Data/Configuration/{Entity}Configuration.cs

```csharp
using EF.Data.Configurations;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Infrastructure.Data.Configuration;

public class {Entity}Configuration : TenantEntityTypeConfiguration<{Entity}, {Entity}Id, TenantId>
{
    public override void Configure(EntityTypeBuilder<{Entity}> builder)
    {
        base.Configure(builder);   // tenant-first key (TenantId, Id), Id never store-generated, TenantId required

        builder.ToTable("{Entity}");

        // ===== Properties =====
        builder.Property(e => e.Name)
               .IsRequired()
               .HasMaxLength(200);  // realistic length for names

        // Value-object converters such as Email/Locale are registered once in
        // {App}DbContextBase.ConfigureConventions. Keep only per-property facets here:
        // builder.Property(e => e.Email).IsRequired();
        // builder.Property(e => e.Locale).HasDefaultValue(Locale.Default);

        // decimal (18,4) and UTC temporal conversion come from ConfigureConventions
        // (section Model Conventions); override precision only when the domain needs it:
        // builder.Property(e => e.Rate).HasPrecision(18, 8);

        builder.Property(e => e.Flags)
               .IsRequired()
               .HasDefaultValue({Entity}Flags.None);

        // ===== Relationships (composite, tenant-first) =====
        builder.HasMany(e => e.{ChildEntities})
               .WithOne()
               .HasForeignKey(c => new { c.TenantId, c.{Entity}Id })
               .HasPrincipalKey(p => new { p.TenantId, p.Id })
               .IsRequired()
               .OnDelete(DeleteBehavior.Cascade);

        // ===== Polymorphic children (NO navigation) =====
        // If this entity participates as a polymorphic owner, do NOT add
        // ICollection<PolymorphicChild> here. EF would generate a real FK
        // from each parent navigation, creating conflicting constraints on
        // the shared OwnerId/EntityId column. Query polymorphic children
        // explicitly: db.Attachments.Where(a => a.OwnerType == ... && a.OwnerId == id)

        // ===== Indexes (tenant-first; an Id suffix makes each a keyset-paging cover) =====
        builder.HasIndex(e => new { e.TenantId, e.Name, e.Id })
               .HasDatabaseName("IX_{Entity}_TenantId_Name_Id");

        builder.HasIndex(e => new { e.TenantId, e.Flags })
               .HasDatabaseName("IX_{Entity}_TenantId_Flags");
    }
}
```

A composite foreign key cannot null only its entity-id half, so an optional reference to another aggregate uses `DeleteBehavior.Restrict` and the owning service clears the reference for the tenant before deleting the target.

## Compensation and Reason-Code Persistence (Optional)

When workflows include compensations:

- map compensation metadata as owned value objects where possible
- persist machine-readable `ReasonCode` fields (use compact string/varchar or enum converters)
- index `ReasonCode` on high-volume tables used by reconciliation and reporting

## JSON Column Mapping with `ToJson()`

`ToJson()` with owned types is the preferred pattern for structured data stored as JSON columns. When migration generation fails for complex shapes (nested collections, dictionaries), fall back to a serializer-backed value conversion as documented in [data-persistence.md](../skills/data-persistence.md) under *JSON Column Mapping (`ToJson()`) Troubleshooting*.

## File: Infrastructure/Data/Configuration/{ChildEntity}Configuration.cs

```csharp
namespace Infrastructure.Data.Configuration;

public class {ChildEntity}Configuration : TenantEntityTypeConfiguration<{ChildEntity}, {ChildEntity}Id, TenantId>
{
    public override void Configure(EntityTypeBuilder<{ChildEntity}> builder)
    {
        base.Configure(builder);

        builder.ToTable("{ChildEntity}");

        builder.Property(e => e.{Entity}Id)
               .IsRequired();

        builder.HasIndex(e => new { e.TenantId, e.{Entity}Id, e.Id })
               .HasDatabaseName("IX_{ChildEntity}_TenantId_{Entity}Id_Id");

        // ... child-specific properties
    }
}
```

## Model Conventions

Canonical owner of the scalar mapping rules. `{App}DbContextBase.ConfigureConventions` registers every type-level convention before EF discovers the model; `OnModelCreating` runs no type-default loop. The shared model names no provider column type (`nvarchar`, `datetime2`, `timestamptz`) outside the provider branch EF Core forces for a provider-only type, such as PostgreSQL `jsonb` or `vector` gated on `Database.ProviderName`; each provider maps the CLR type itself.

| C# type | Convention | Per-property override |
|---|---|---|
| `string` | Realistic `HasMaxLength(N)` (Name 200, Email 254, Sku 50, Description 2000). Leave it unbounded only for genuinely large text. | `.HasMaxLength(200)` |
| `decimal` | `HavePrecision(18, 4)` for every monetary/quantity value. | `.HasPrecision(18, 8)` for exchange rates |
| `DateTimeOffset`, `DateTime` | Stored and compared as UTC through `RegisterUtcTemporalConversions()` (EF.Data). Prefer `DateTimeOffset`. | none |

```csharp
using EF.Data;

public abstract class {App}DbContextBase(DbContextOptions options)
    : DbContextBase<string, Guid?>(options)
{
    protected override void ConfigureConventions(ModelConfigurationBuilder cb)
    {
        base.ConfigureConventions(cb);

        cb.RegisterDomainIdConversions(typeof({Entity}Id).Assembly);
        cb.Properties<decimal>().HavePrecision(18, 4);
        cb.RegisterUtcTemporalConversions();   // every DateTimeOffset / DateTime, nullable included
        cb.Properties<Email>()
            .HaveConversion<EmailValueConverter>()
            .HaveMaxLength(320);
        cb.Properties<Locale>()
            .HaveConversion<LocaleValueConverter>()
            .HaveMaxLength(20);
    }
}
```

The UTC converters are EF.Data's (`UtcDateTimeOffsetConverter`, `UtcDateTimeConverter` in `EF.Data.Converters`); generate none. A `DateTime` of `Kind.Unspecified` is taken as UTC and never shifted by the host offset, and every value reads back with `Kind = Utc`.

Why UTC: Npgsql `timestamptz` rejects a non-zero offset and SQL Server compares by instant anyway, so one converter keeps every provider on one code path. EF applies it to query parameters too, so a caller-supplied `+05:00` filter is normalized before it reaches the provider. Clients convert for display.

Domain IDs are typed value objects (`{Entity}Id : IDomainId<{Entity}Id>`). **Do NOT hand-wire individual `HasConversion<>` calls** for each ID property and do not scan entity metadata from `OnModelCreating`. `RegisterDomainIdConversions` lives in the EF.Data package (`EF.Data` namespace). It scans the supplied assembly for `IDomainId<T>` structs and registers each converter as pre-convention model configuration, so EF discovers and converts mapped IDs, previously unmapped scalar IDs such as `TenantId`, and nullable FK IDs without an app-local reflection loop.

Use one non-nullable `DomainIdValueConverter<T>` implementation for nullable and non-nullable properties. EF never passes null into a converter. Do not create or keep `NullableDomainIdValueConverter<T>` or nullable value-object converters.

Register value-object converters once per type when the storage shape is consistent across the model. In entity configs, keep only facets the convention cannot safely carry, such as `.IsRequired()`, `.HasDefaultValue(Locale.Default)`, and indexes. Do not repeat `.HasConversion<EmailValueConverter>()` or shared `.HasMaxLength(...)` on every entity.

Exceptions stay per-property: a value object mapped to different provider types across entities, owned/complex types configured with `OwnsOne`, and raw-`Guid` polymorphic columns such as `OwnerId` / `EntityId`.

Converted value object defaults must use the **model CLR type**, not the provider/storage type. For example, a `Locale` property converted to `string` must use `.HasDefaultValue(Locale.Default)`, not `.HasDefaultValue("en-US")`. Fix the runtime model configuration in `OnModelCreating` or the entity configuration; generated migration snapshot/designer files may echo the old literal but are not the source of runtime model building.

## Notes

- `TenantEntityTypeConfiguration<TEntity, TId, TTenantId>` (EF.Data) handles the tenant-first key, `Id` (client-generated V7 GUID wrapped in a typed ID, never store-generated) and the required `TenantId` - NO audit fields; `RegisterVersionConcurrencyTokens()` maps `Version`
- **Every tenant-owned entity configuration derives from `TenantEntityTypeConfiguration` and calls `base.Configure(builder)`**; without it `Id` may be store-generated and aggregate child inserts fail
- Timestamps and audit ids are stamped by `DbContextBase` on save; audit trail entries come from the `AuditInterceptor`, not entity configuration
- Foreign keys to tenant-owned principals are composite `(TenantId, {Entity}Id)` against the principal key `(TenantId, Id)`
- Composite indexes always lead with `TenantId` for filtered queries
- Enum properties: use `HasDefaultValue({Enum}.None)` for flags enums; `HasConversion<string>()` is optional for readability
- All string properties must have `HasMaxLength()` with a realistic length; leave one unbounded only when it genuinely stores large text
- Decimal precision and UTC temporal conversion are `ConfigureConventions` rules (section Model Conventions); entity configs name no provider column type
- Domain ID properties (`{Entity}Id`, `TenantId`, nullable FKs) are handled by `ConfigureConventions` / `RegisterDomainIdConversions` - no per-property `HasConversion<>` and no `OnModelCreating` reflection loop
- Stable value objects such as `Email` and `Locale` are handled by `ConfigureConventions` once per type; entity configs keep only required/default/index facets
