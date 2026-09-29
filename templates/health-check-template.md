# Health Check Template

**Generates:** `SqlHealthCheck.cs` (the database check the app owns) and the health registration; every other dependency uses its package check
**Requires:** [../skills/observability.md](../skills/observability.md)

## Health Check Implementation

The relational database check stays app code, because readiness must prove the app's own context can connect:

```csharp
public class SqlHealthCheck(IDbContextFactory<{App}DbContextTrxn> factory) : IHealthCheck
{
    public async Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context, CancellationToken ct = default)
    {
        try
        {
            using var db = await factory.CreateDbContextAsync(ct);
            return await db.Database.CanConnectAsync(ct)
                ? HealthCheckResult.Healthy()
                : HealthCheckResult.Unhealthy("SQL connection failed");
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
// In the Bootstrapper; register only the checks for dependencies the host uses.
var health = services.AddHealthChecks()
    .AddCheck<SqlHealthCheck>("sql", tags: ["ready"])
    .AddMemoryHealthCheck("memory", tags: ["full"]);                                           // EF.AspNetCore

health.AddRedisHealthCheck("redis-cache", tags: ["full"]);                                     // EF.Cache, shared multiplexer; Degraded
health.AddBlobContainerHealthCheck("blob-storage", "{Project}BlobClient", "{container}", tags: ["full"]); // EF.Storage
health.AddS3BucketHealthCheck("s3-storage", "{bucket}", tags: ["full"]);                        // EF.Storage.S3
health.AddCosmosDbHealthCheck("cosmos-db", tags: ["full"]);                                    // EF.CosmosDb
health.AddServiceBusHealthCheck("{Project}SBClient", "{topic}", "service-bus", "full");         // EF.Messaging
health.AddRabbitMqHealthCheck(tags: "ready");                                                  // EF.Messaging.RabbitMq, consumer host
health.AddLeasedWorkBacklogCheck<OutboxMessage>("outbox", tags: ["ready"]);                    // EF.Data.Outbox, dispatcher host
health.AddSchedulerHealthCheck<{App}TickerQDbContext>(tags: ["ready"]);                         // EF.BackgroundServices.TickerQ
health.AddDownstreamHealthCheck("{project}-api", o => o.Url = apiHealthUrl, tags: ["full"]);    // EF.Gateway, gateway host
```

## Endpoint Mapping

```csharp
app.MapEfHealthEndpoints();   // EF.AspNetCore: /healthz/live (live), /healthz/ready (ready), /healthz (operator aggregate)
```

The three endpoints are anonymous and exempt from every rate limiter; generate no hand-mapped `MapHealthChecks` for them.

## Rules

- One health check per external dependency: the package check where one exists, an app `IHealthCheck` class otherwise.
- Branch on the `CanConnectAsync` result: it reports most connection failures as `false` instead of throwing, so an unconditional `Healthy()` after the call reports a down database as healthy.
- Tag dependency checks with `"ready"` only when the host must stop taking traffic without them; ServiceDefaults owns the `"self"` check tagged `"live"`. A cache that degrades to L1 (Redis) and a rate limiter that fails open are not readiness dependencies.
- `/healthz/live` runs only `"live"` checks. `/healthz/ready` runs only `"ready"` checks. `/healthz` runs the operator aggregate and is never the liveness target.
- Do not duplicate ServiceDefaults' `self` liveness or host-lifecycle `draining` checks ([../skills/observability.md](../skills/observability.md) section Health Checks) - add domain-specific readiness only.
- **Why:** dependency failure must stop new traffic through readiness without making the orchestrator restart a healthy process through liveness.
- Verify a failed critical dependency makes `/healthz/ready` unhealthy while `/healthz/live` remains healthy. This is a required test, not a manual check: generate `tests/Test.Endpoints/HealthProbeContractTests.cs` from [test-templates-endpoint.md](test-templates-endpoint.md) section Health Probe Contract Tests, which forces a `"ready"`-tagged check to fail and asserts the two probes diverge.
