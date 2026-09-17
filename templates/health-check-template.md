# Health Check Template

**Generates:** `SqlHealthCheck.cs`, `RedisHealthCheck.cs` (and per-dependency checks as needed)
**Requires:** [../skills/observability.md](../skills/observability.md)

## Health Check Implementation

```csharp
public class SqlHealthCheck(IDbContextFactory<{App}DbContextTrxn> factory) : IHealthCheck
{
    public async Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context, CancellationToken ct = default)
    {
        try
        {
            using var db = await factory.CreateDbContextAsync(ct);
            await db.Database.CanConnectAsync(ct);
            return HealthCheckResult.Healthy();
        }
        catch (Exception ex)
        {
            return HealthCheckResult.Unhealthy("SQL connection failed", ex);
        }
    }
}
```

## Registration

```csharp
// In RegisterApiServices or Bootstrapper
services.AddHealthChecks()
    .AddCheck<SqlHealthCheck>("sql", tags: ["ready"])
    .AddCheck<RedisHealthCheck>("redis", tags: ["ready"]);
```

## Endpoint Mapping

```csharp
app.MapHealthChecks("/healthz/live", new() { Predicate = r => r.Tags.Contains("live") }).AllowAnonymous();  // liveness
app.MapHealthChecks("/healthz/ready", new() { Predicate = r => r.Tags.Contains("ready") }).AllowAnonymous(); // readiness
app.MapHealthChecks("/healthz", new()).AllowAnonymous(); // operator aggregate
```

## Rules

- One `IHealthCheck` class per external dependency.
- Tag dependency checks with `"ready"`; ServiceDefaults owns the `"self"` check tagged `"live"`.
- `/healthz/live` runs only `"live"` checks. `/healthz/ready` runs only `"ready"` checks. `/healthz` runs the operator aggregate and is never the liveness target.
- Do not duplicate ServiceDefaults self-liveness - add domain-specific readiness only.
- **Why:** dependency failure must stop new traffic through readiness without making the orchestrator restart a healthy process through liveness.
- Verify a failed critical dependency makes `/healthz/ready` unhealthy while `/healthz/live` remains healthy. This is a required test, not a manual check: generate `tests/Test.Endpoints/HealthProbeContractTests.cs` from [test-templates-endpoint.md](test-templates-endpoint.md) section Health Probe Contract Tests, which forces a `"ready"`-tagged check to fail and asserts the two probes diverge.
