# Security

## Purpose

Hardening checklist for API, Gateway, and optional hosts. Complements [identity-management.md](identity-management.md) (which handles authn); this covers authz patterns, transport security, and input safety.

---

## Rate Limiting

Rate limiting is EF.RateLimiting over ASP.NET Core's `RateLimiterMiddleware`; generate no partitioner, limiter factory, fail-open wrapper or rejection writer. Types and settings: [../support/ef-packages-optional.md](../support/ef-packages-optional.md) section Rate Limiting (EF.RateLimiting, EF.RateLimiting.Redis).

### Patterns

```csharp
// API (RegisterApiServices.cs): per-tenant tiers and named budgets from RateLimiting:Tenants
services.AddTenantRateLimiting(config);
if (services.HasSharedRedis())            // the EF.Cache default instance has Redis configured
    services.AddRedisRateLimiting();      // one shared budget across replicas, over the EF.Cache connection

// Per-IP policies that must work without Redis (health probes) stay in process.
services.AddRateLimiter(options => options
    .AddPerClientIpFixedWindowPolicy("HealthFull", permitLimit: 3, window: TimeSpan.FromSeconds(30), queueLimit: 1));

// An endpoint that spends only its own budget:
group.MapGet("/export", Export).RequireTenantBudget("export");

// Gateway (edge): per-client token bucket plus a process concurrency cap from RateLimiting:Edge
var edge = config.GetSection(EdgeRateLimitSettings.ConfigSectionName).Get<EdgeRateLimitSettings>() ?? new();
services.AddRateLimiter(options => options.UseEdgeLimiter(edge));
```

`HasSharedRedis()` is the app's one-line check that `AddTypedCache` registered the unkeyed `IConnectionMultiplexer` (`services.Any(d => d.ServiceType == typeof(IConnectionMultiplexer) && !d.IsKeyedService)`); the Redis health check uses the same answer.

### Pipeline Registration

```csharp
app.UseProxyForwarding();   // real client IP before any per-IP partition
app.UseAuthentication();
app.UseAuthorization();
app.UseRateLimiter();
```

Run the rate limiter after `UseAuthentication()` and `UseAuthorization()` whenever any partition reads a claim: before authentication `context.User` is anonymous, so every caller lands in the anonymous partition and one tenant can exhaust everyone's budget. The tenant partitioner throws `InvalidOperationException` on the first request when `UseRateLimiter` runs before `UseAuthentication`. Only the unauthenticated per-IP edge limiter (`UseEdgeLimiter`) may run earlier, and it needs `UseProxyForwarding` before it or every request partitions into the ingress proxy's address. The tenant claim type must match what JwtBearer puts on the principal ([identity-management.md](identity-management.md) section Claim-type contract).

### Distributed Limiter

- A request is counted by exactly one limiter per budget: the global tenant limiter skips endpoints carrying `TenantBudgetMetadata`, so `RequireTenantBudget` never double counts, and a route-group policy over the same budget is never added.
- **The Redis rate limiter shares the EF.Cache connection.** `AddRedisRateLimiting()` resolves the `IConnectionMultiplexer` that `AddTypedCache` registered (the unkeyed default instance, or `AddRedisRateLimiting(cacheInstanceName)` for a named one); register `AddTypedCache` first and never open a second Redis connection for the limiter. That multiplexer always has `AbortOnConnectFail = false`, so a Redis outage at boot does not fail startup.
- When Redis is unavailable the package fails open and increments `ratelimit.backend_failure`; alert on it, because limits are not enforced while it moves ([../support/scalability-and-hosting.md](../support/scalability-and-hosting.md) section Edge, TLS, and Rate Limits). Export meter `EF.RateLimiting` from ServiceDefaults.
- Health endpoints mapped by `MapEfHealthEndpoints` carry `DisableRateLimiting()` and skip every limiter.

### Testing

> **CRITICAL:** Disable rate limiter in `CustomApiFactory` for integration tests to avoid flaky 429 responses:
> ```csharp
> services.Configure<RateLimiterOptions>(o => o.GlobalLimiter = PartitionedRateLimiter.CreateChained<HttpContext>());
> ```
> This is a test-only bypass: keep it behind an explicit Testing guard and add a negative test proving Production still rate-limits ([testing.md](testing.md) section Never Silently Pass).

---

## Input Validation & Sanitization

### DTO Structure Validation

Use [structure-validator-template](../templates/structure-validator-template.md) for DTO shape validation before domain operations. Validates required fields, string lengths, enum ranges.

### String Safety

- Store canonical validated text. Prefer framework text bindings that encode for their sink; when raw output is unavoidable, use the encoder for that specific HTML, attribute, URL, or JavaScript context. **Why:** Storage-time HTML encoding causes double encoding and does not protect other output contexts. Therefore the actual sink owns encoding.
- Enforce `MaxLength` at both DTO (StructureValidator) and EF (`HasMaxLength()`) levels - defense in depth.
- Reject null bytes and control characters in text inputs.

---

## Security Headers

`app.UseBasicSecurityHeaders()` (EF.AspNetCore, `EF.AspNetCore.Security`) sets the baseline response headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`); generate no security-headers middleware. Register it early in the pipeline, after `UseProxyForwarding` and before routing. HSTS stays a config-toggled `UseHsts()`.

For UI hosts (Gateway serving Uno WASM), add `Content-Security-Policy` with appropriate directives. Use config-driven toggle to adjust between dev/prod.

---

## CORS Policy

CORS configuration belongs in the **Gateway only**. API behind gateway should reject direct browser requests.

### Configuration Pattern

```json
// appsettings.json
{
  "CorsSettings": {
    "AllowedOrigins": ["https://localhost:5001", "https://myapp.azurewebsites.net"],
    "AllowCredentials": true
  }
}
```

```csharp
// Gateway RegisterServices - EF.AspNetCore.Cors
services.AddCorsPolicyFromConfiguration("{Project}UI", config.GetSection("CorsSettings"));
// Pipeline: app.UseCors("{Project}UI");
```

`AddCorsPolicyFromConfiguration` validates the origins at registration: at least one; each an `http`/`https` origin with no path, query, fragment or trailing `/` (which never matches an `Origin` header); `*` never combined with credentials.

---

## Data Protection

ASP.NET Core Data Protection handles encryption of cookies, anti-forgery tokens, and other sensitive payloads. In multi-instance deployments, keys must be shared and persisted externally. **Why:** Without one persisted key ring, another replica or a restarted host cannot decrypt existing payloads, causing intermittent authentication failures and mass session invalidation. Therefore every replica uses the same durable key ring and application name.

### Provider-aware persistence contract

Phase 2 maps `hostingLaneDefaults.<active>.dataProtectionPersistence` to runtime `DataProtection:Persistence`. `TASKFLOW_DATAPROTECTION_PERSISTENCE` is the environment override; otherwise the strict lane default applies. The shared hosting resolver returns the validated arm before host startup and names an unknown or cross-lane value in the exception.

| Arm | Required input | Provisioning rule |
|---|---|---|
| `Redis` (`NonAzure` default) | Named `Redis1` connection string | Leave `DataProtection:Redis:ConnectionString` null so the key ring uses the shared EF.Cache `IConnectionMultiplexer`; it never connects at registration. |
| `AzureBlob` (`Azure` lane default) | Either an absolute `DataProtectionKeysFileUrl`, or the named `BlobStorage1` endpoint/connection string injected by Aspire or deployment configuration | Infrastructure creates the production container. Only the storage emulator gets its container created at registration. Endpoint authentication uses the one `TokenCredential`; connection-string authentication uses the connection string. |
| `None` | None | Development and isolated tests only. Log that keys do not survive restart or work across replicas. Do not use as a scaled deployment default. |

Key persistence and key encryption are independent. `DataProtectionEncryptionKeyUrl`, when supplied, adds Azure Key Vault protection after persistence is selected. It is required only when the deployment policy requires at-rest key encryption, and it is rejected by a strict zero-Azure NonAzure lane. Do not require a Key Vault URL merely because Azure Blob persistence was selected.

Keep these rules in the shared Bootstrapper path used by every cookie/token-producing host. A test factory that selects `AzureBlob` must also inject `DataProtectionKeysFileUrl` or `BlobStorage1`; otherwise the resulting startup error is configuration failure, not an unavailable AI, browser, or container runtime.

### Registration skeleton

`AddEfDataProtection(settings, credential)` (EF.AspNetCore.DataProtection) owns the persistence arms and the Key Vault key protection; the app only resolves the lane's arm and fills the settings from its own configuration keys.

```csharp
public static IServiceCollection AddAppDataProtection(this IHostApplicationBuilder builder, ILogger logger)
{
    var config = builder.Configuration;
    var settings = config.GetSection(DataProtectionSettings.ConfigSectionName).Get<DataProtectionSettings>()
        ?? new DataProtectionSettings();
    settings.Persistence = DataProtectionPersistenceResolver.Resolve(config); // lane-aware closed switch (StrictEnum)
    settings.KeyVaultKeyUri = config["DataProtectionEncryptionKeyUrl"];

    switch (settings.Persistence)
    {
        case DataProtectionPersistence.AzureBlob:
            settings.AzureBlob.BlobUri = config["DataProtectionKeysFileUrl"];
            settings.AzureBlob.Connection = config.ResolveConnection("BlobStorage1", "BlobStorage1:blobServiceUri");
            if (string.IsNullOrWhiteSpace(settings.AzureBlob.BlobUri) && string.IsNullOrWhiteSpace(settings.AzureBlob.Connection))
                throw new InvalidOperationException(
                    "DataProtection:Persistence=AzureBlob requires DataProtectionKeysFileUrl or BlobStorage1.");
            break;
        case DataProtectionPersistence.Redis:
            if (string.IsNullOrWhiteSpace(config.GetConnectionString("Redis1")))
                throw new InvalidOperationException("DataProtection:Persistence=Redis requires ConnectionStrings:Redis1.");
            settings.Redis.ConnectionString = null;   // the shared EF.Cache multiplexer, resolved on first key access
            break;
        case DataProtectionPersistence.None:
            logger.LogWarning("Data Protection keys are ephemeral and do not survive restart or scale-out.");
            break;
    }

    builder.Services.AddEfDataProtection(settings, AzureCredentialFactory.Create(config));   // EF.Host credential
    return builder.Services;
}
```

### Rules

- Leave `DataProtection:ApplicationName` unset on an app that is already deployed: the framework's implicit discriminator is kept, and setting one for the first time invalidates every payload protected before. Unrelated apps sharing a store set distinct names from their first deployment.
- Treat the application discriminator, key-store location, encryption key, and purpose strings as persisted wire-contract inputs. Before changing one, protect a payload with the previous release and prove the candidate can unprotect it.
- Fail before host startup on an unknown persistence value or missing selected-arm input. Never catch this error and reclassify it as another optional provider's failure.
- Pre-provision production Blob containers and Key Vault keys. Configure a Key Vault rotation policy when Key Vault encryption is selected.


---

## Dependency Scanning

### CI Pipeline

Run the vulnerability audit after restore. Severity policy is owned by [../support/execution-gates.md](../support/execution-gates.md) section Vulnerability Audit. The generated workflow step shape lives in [cicd.md](cicd.md).

```yaml
- run: dotnet restore {SolutionName}.slnx --locked-mode
- run: dotnet list {SolutionName}.slnx package --vulnerable --include-transitive
```

There is no `dotnet nuget audit` verb - do not emit one. `dotnet list package --vulnerable` also exits `0` even when it reports findings, so the step must inspect its output to warn or fail; the `<NuGetAudit>` build property below is the complementary mechanism that fails the build itself.

### GitHub Dependabot

Optional, not a default. The baseline freshness path is refresh-on-touch plus the vulnerability audit gate ([../support/execution-gates.md](../support/execution-gates.md) section Vulnerability Audit): dependencies and action refs are re-resolved to latest stable during normal maintenance, and the audit blocks known-vulnerable resolutions. Enable Dependabot only when the team owns the resulting PR churn, and account for two CI-breaking caveats:

- Dependabot-triggered workflow runs read the separate Dependabot secrets store, never repository Actions secrets. Register every restore credential the CI workflow requires (e.g. `NUGET_PAT`) as a Dependabot secret too, or every Dependabot PR fails CI.
- Each `npm`/`nuget` ecosystem `directory:` must contain its manifest (`package.json`, or a project/props file), and a `nuget` ecosystem restoring from a private feed needs a `registries:` entry with a Dependabot-secret token.

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "nuget"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10
```

### NuGet Vulnerability Alerts

Enable in `Directory.Build.props` or `.csproj`:
```xml
<PropertyGroup>
  <NuGetAudit>true</NuGetAudit>
  <NuGetAuditLevel>moderate</NuGetAuditLevel>
</PropertyGroup>
```

---

## Secret Rotation

Secrets must be stored in Azure Key Vault (see [configuration-secrets.md](configuration-secrets.md)).

### Rotation Workflow

1. **Create new version** - add new secret version in Key Vault
2. **Update config** - deploy app with config pointing to latest version (Key Vault references auto-resolve latest)
3. **Verify** - confirm app functions with new secret
4. **Remove old version** - disable/remove previous version after grace period

### Configuration Validation

> **CRITICAL:** Use `ValidateOnStart()` for options that bind to secrets - fail fast if secrets are missing or expired rather than failing on first request:
> ```csharp
> services.AddOptions<DatabaseSettings>()
>     .BindConfiguration("DatabaseSettings")
>     .ValidateDataAnnotations()
>     .ValidateOnStart();
> ```

---

## Verification Checklist

- [ ] `AddTenantRateLimiting` (API) / `UseEdgeLimiter` (Gateway) registered; the Redis limiter, when used, rides the EF.Cache multiplexer; `UseRateLimiter` runs after `UseAuthentication`
- [ ] Rate limiter disabled in `CustomApiFactory` only behind an explicit Testing guard, with a negative test proving Production retains the limiter ([testing.md](testing.md) section Never Silently Pass)
- [ ] `StructureValidator` enforces `MaxLength` matching EF configuration
- [ ] User content stays canonical in storage and is context-encoded at the rendering boundary
- [ ] `UseBasicSecurityHeaders()` in the pipeline; no app security-headers middleware
- [ ] CORS configured in Gateway only through `AddCorsPolicyFromConfiguration` - API rejects direct browser requests
- [ ] CI runs `dotnet list package --vulnerable --include-transitive` after restore and gates on its output; `<NuGetAudit>`/`<NuGetAuditLevel>` set in build props; no workflow references a `dotnet nuget audit` verb (it does not exist)
- [ ] Dependabot enabled only deliberately and configured per the GitHub Dependabot section (Dependabot secrets, manifest-per-directory, private-feed registries)
- [ ] Data Protection runtime `Persistence` matches the active lane: Azure Blob has a key URL or `BlobStorage1`, Redis has `Redis1`, and `None` is limited to isolated development/tests
- [ ] When Key Vault key encryption is selected, the encryption URL, managed identity permissions, stored secret policy, and rotation workflow are documented; strict NonAzure emits no Key Vault dependency
- [ ] `ValidateOnStart()` used for critical configuration sections
