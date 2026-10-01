# Caching

Reference patterns: [../patterns/infrastructure-wiring.md](../patterns/infrastructure-wiring.md) (Multi-Cache Configuration).

## Purpose

Use EF.Cache as the application cache: `ITypedCache` over FusionCache, with Redis as distributed layer and backplane for cross-instance invalidation. Types: [../support/ef-packages-reference.md](../support/ef-packages-reference.md) section Caching (EF.Cache).

Services and handlers inject `ITypedCache` (and `CacheKey`) directly; the registration lives in `Infrastructure.Caching`, so FusionCache and Redis stay behind that project. `ITypedCache` owns key rendering (namespace, schema version) and the profile-to-expiry mapping, so no call site builds a raw key or an entry-options object. This is the deliberate direct-reference exception to the usual contract-in-Application / implementation-in-Infrastructure split - see the Wrap vs. Direct Reference rule in [solution-structure.md](solution-structure.md#wrap-vs-direct-reference).

## Architecture

```
Application -> ITypedCache -> FusionCache (L1 memory) -> Redis (L2 distributed)
                                         \-> Redis backplane (invalidation sync)
```

For local Redis inspection under Aspire, use `WithRedisInsight` over the desktop app ([aspire.md](aspire.md) -> *Local Explorer Tooling*: pinned port, `isTesting` gate).

## Non-Negotiables

1. Register with `AddTypedCache`; generate no FusionCache registration loop, cache-settings class, key builder or Redis connection code.
2. Configure cache instances from settings (`CacheSettings[]`).
3. Use cache-aside for reads (`GetOrSetAsync`) and tag invalidation on writes (`RemoveByTagAsync`).
4. Keep fail-safe enabled for resilience under transient dependency failures.
5. Align Redis connection names with Aspire/bootstrapper config.

---

## Configuration

```json
{
  "CacheSettings": [
    {
      "Name": "Default",
      "DurationMinutes": 30,
      "DistributedCacheDurationMinutes": 60,
      "FailSafeMaxDurationMinutes": 120,
      "FailSafeThrottleDurationSeconds": 1,
      "RedisConnectionStringName": "Redis1",
      "BackplaneChannelName": "cache-sync"
    }
  ]
}
```

`KeyNamespace` defaults to the host environment name, so a Redis shared across environments never serves one environment's entries to another. `Serializer` (`Json` default, or `MessagePack`) and `Profiles` are optional per instance. `StaticData`-style long-lived caches can be added as separate named instances.

---

## Registration Pattern (Bootstrapper)

**Source:** `Infrastructure/{App}.Infrastructure.Caching/RegisterCachingServices.cs`, called from the Bootstrapper.

```csharp
public static IServiceCollection Add{App}Caching(this IServiceCollection services, IConfiguration config)
{
    // Every CacheSettings entry becomes a named instance; ITypedCache binds to the default one. For each
    // Redis-backed instance the package registers one shared IConnectionMultiplexer (keyed by Name, the default
    // instance also unkeyed; AbortOnConnectFail forced false) and the matching IDistributedLock.
    services.AddTypedCache(config, "CacheSettings", configure: settings =>
    {
        // Code decisions, not deployment knobs: bump SchemaVersion when a cached shape changes.
        settings.SchemaVersion = {App}Cache.SchemaVersion;
        settings.Profiles.TryAdd("Summary", new CacheProfileOptions { DurationSeconds = 5, FactorySoftTimeoutMilliseconds = 500 });
    });
    return services;
}

/// <summary>True when AddTypedCache registered the shared default Redis connection.</summary>
public static bool HasSharedRedis(this IServiceCollection services) =>
    services.Any(d => d.ServiceType == typeof(IConnectionMultiplexer) && !d.IsKeyedService);
```

With no Redis connection string the instance is L1-only and `IDistributedLock` is the in-process lock: correct on one replica only. **Every other Redis consumer shares this connection:** the Redis rate limiter and the Data Protection key ring (both in [security.md](security.md)), the Redis health check (`AddRedisHealthCheck`), and any host client resolve the `IConnectionMultiplexer` from DI and never connect themselves. Export `CacheTelemetry.MeterNames()` / `ActivitySourceNames` from ServiceDefaults. Azure Redis with Entra auth attaches the credential through the `configureRedis` hook.

---

## Tag-Based Invalidation

Tags are a parameter on `GetOrSetAsync` / `SetAsync`. Invalidate by tag with `RemoveByTagAsync`, which evicts across replicas through the backplane; tags carry the same namespace and schema prefix as keys.

```csharp
// Setting tags when caching
await cache.SetAsync(new CacheKey("todoitem", $"{tenantId}:{id}"), dto, profile: null, tags: [$"todoitem:{tenantId}:{id}"], ct);

// Invalidating by tag
await cache.RemoveByTagAsync($"todoitem:{tenantId}:{id}", ct);
```

---

## Usage Patterns

### Cache-aside read

```csharp
// tenantId = requestContext.TenantId, never request input: tenants can share an id
public Task<TodoItemDto?> GetCachedAsync(Guid tenantId, Guid id, CancellationToken ct) =>
    cache.GetOrSetAsync(
        new CacheKey("todoitem", $"{tenantId}:{id}"),
        token => repoQuery.GetTodoItemDtoAsync(id, token),
        profile: "Short",
        tags: [$"todoitem:{tenantId}:{id}"],
        ct);
```

### Invalidate on write

```csharp
await repoTrxn.SaveChangesAsync(OptimisticConcurrencyWinner.Throw, ct);
await cache.RemoveByTagAsync($"todoitem:{tenantId}:{id}", ct);   // after the commit, same tenant scope
```

Subscribe to `ITypedCache.Degraded` (or alert on `ef.cache.degraded`) to see fail-safe activation and circuit-breaker trips, which are otherwise silent.

---

## Cache Key Rules

- item keys: `new CacheKey("{entity}", id)`
- list/query keys: `new CacheKey("{entity}", "list", filterHash)`
- tenant-owned keys and their tags carry the authoritative tenant (`$"{tenantId}:{id}"`)

`ITypedCache` renders `[{keyNamespace}:]{schemaVersion}:{category}:{id}[:{discriminator}]`, so keys stay deterministic and versionable without app code.

---

## Scale Hazards

- Invalidate after the database commit, never before; a read between an early invalidation and the commit repopulates the stale value.
- Factory coalescing (stampede protection) is per node. A cold start across N replicas still reaches the store up to N times per key; the L2 plus eager refresh and jitter keep that bounded.
- More than one replica with L1 enabled needs the backplane, or each node serves its own stale copy for up to `Duration`.
- Keys that vary by tenant or user include that scope; never cache a user-specific response under a shared key.
- Keep the JSON serializer. `MessagePack` is a measured, **GR-04**-gated change under [../support/scalability-and-hosting.md](../support/scalability-and-hosting.md) section Edge, TLS, and Rate Limits; it needs public cached types, and switching serializer migrates nothing, so bump `SchemaVersion` in the same change.

## Testing Guidance

Mock `ITypedCache` in unit tests; verify:

- cache hits return expected value,
- misses call underlying repository once,
- write operations invalidate the relevant tags after the commit.

A component test over a Redis Testcontainer proves the shared-connection wiring (cache, lock and limiter on one multiplexer).

---

## Verification

- [ ] `AddTypedCache` registered once; no app FusionCache loop, `CacheSettings` class or Redis connection code
- [ ] Redis L2 + backplane configured where distributed caching is enabled
- [ ] key and tag patterns are deterministic and tenant-safe
- [ ] reads use `GetOrSetAsync` cache-aside pattern
- [ ] writes invalidate relevant tags after commit
- [ ] every Redis consumer resolves the shared `IConnectionMultiplexer`
- [ ] Aspire Redis resource name aligns with connection string naming
- [ ] tests mock `ITypedCache` and validate behavior
