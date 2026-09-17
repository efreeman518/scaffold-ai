# Security

## Purpose

Hardening checklist for API, Gateway, and optional hosts. Complements [identity-management.md](identity-management.md) (which handles authn); this covers authz patterns, transport security, and input safety.

---

## Rate Limiting

Use ASP.NET `RateLimiterMiddleware` for request throttling.

### Patterns

```csharp
// In RegisterApiServices.cs
services.AddRateLimiter(options =>
{
    // Fixed window per-tenant
    options.AddPolicy("PerTenant", context =>
        RateLimitPartition.GetFixedWindowLimiter(
            context.User?.FindFirst("tenant_id")?.Value ?? "anonymous",
            _ => new FixedWindowRateLimiterOptions
            {
                PermitLimit = 100,
                Window = TimeSpan.FromMinutes(1)
            }));

    // Sliding window per-endpoint
    options.AddPolicy("PerEndpoint", context =>
        RateLimitPartition.GetSlidingWindowLimiter(
            context.Request.Path.Value ?? "/",
            _ => new SlidingWindowRateLimiterOptions
            {
                PermitLimit = 30,
                Window = TimeSpan.FromSeconds(30),
                SegmentsPerWindow = 3
            }));

    options.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
});
```

### Pipeline Registration

```csharp
app.UseRateLimiter();  // After UseRouting, before UseAuthorization
```

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

Add middleware to set security headers on all responses:

```csharp
public class SecurityHeadersMiddleware(RequestDelegate next)
{
    public async Task InvokeAsync(HttpContext context)
    {
        context.Response.Headers["X-Content-Type-Options"] = "nosniff";
        context.Response.Headers["X-Frame-Options"] = "DENY";
        context.Response.Headers["Referrer-Policy"] = "strict-origin-when-cross-origin";

        // HSTS - set via config toggle, not in middleware (UseHsts in pipeline)
        // Content-Security-Policy - set in Gateway for UI responses only

        await next(context);
    }
}
```

Register early in pipeline - before routing.

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
// Gateway RegisterServices
services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
    {
        var origins = config.GetSection("CorsSettings:AllowedOrigins").Get<string[]>() ?? [];
        policy.WithOrigins(origins)
              .AllowAnyMethod()
              .AllowAnyHeader()
              .AllowCredentials();
    });
});
```

---

## Data Protection

ASP.NET Core Data Protection handles encryption of cookies, anti-forgery tokens, and other sensitive payloads. In multi-instance deployments, keys must be shared and persisted externally. **Why:** Without one persisted key ring, another replica or a restarted host cannot decrypt existing payloads, causing intermittent authentication failures and mass session invalidation. Therefore every replica uses the same durable key ring and application name.

### Provider-aware persistence contract

Phase 2 maps `hostingLaneDefaults.<active>.dataProtectionPersistence` to runtime `DataProtection:Persistence`. `TASKFLOW_DATAPROTECTION_PERSISTENCE` is the environment override; otherwise the strict lane default applies. The shared hosting resolver returns the validated arm before host startup and names an unknown or cross-lane value in the exception.

| Arm | Required input | Provisioning rule |
|---|---|---|
| `AzureBlob` | Either an absolute `DataProtectionKeysFileUrl`, or the named `BlobStorage1` endpoint/connection string injected by Aspire or deployment configuration | Infrastructure creates the production container. A local Azurite connection may create its test container on first use. Endpoint authentication uses `DefaultAzureCredential`; connection-string authentication uses the connection string. |
| `Redis` | Named `Redis1` connection string | Reuse a registered `IConnectionMultiplexer` when the app exposes one; otherwise record the extra eager connection as a bounded shortcut. |
| `None` | None | Development and isolated tests only. Log that keys do not survive restart or work across replicas. Do not use as a scaled deployment default. |

Key persistence and key encryption are independent. `DataProtectionEncryptionKeyUrl`, when supplied, adds Azure Key Vault protection after persistence is selected. It is required only when the deployment policy requires at-rest key encryption, and it is rejected by a strict zero-Azure NonAzure lane. Do not require a Key Vault URL merely because Azure Blob persistence was selected.

Keep these rules in the shared Bootstrapper path used by every cookie/token-producing host. A test factory that selects `AzureBlob` must also inject `DataProtectionKeysFileUrl` or `BlobStorage1`; otherwise the resulting startup error is configuration failure, not an unavailable AI, browser, or container runtime.

### Registration skeleton

Keep provider resolution and registration together. `CreateBlobServiceClient` accepts either an absolute service endpoint plus `DefaultAzureCredential` or a connection string. `DataProtection:AzureBlob:ContainerName` and `BlobName` default to `data-protection` and `keys.xml`; deployed infrastructure pre-creates the container, while local Azurite may create it during test setup.

```csharp
public static IServiceCollection AddAppDataProtection(
    this IHostApplicationBuilder builder,
    ILogger logger)
{
    var config = builder.Configuration;
    var persistence = DataProtectionPersistenceResolver.Resolve(config); // lane-aware closed switch
    var dataProtection = builder.Services.AddDataProtection(); // preserve the existing discriminator

    switch (persistence)
    {
        case DataProtectionPersistence.AzureBlob:
            var keysFileUrl = config["DataProtectionKeysFileUrl"];
            if (!string.IsNullOrWhiteSpace(keysFileUrl))
            {
                dataProtection.PersistKeysToAzureBlobStorage(
                    new Uri(keysFileUrl), CreateAzureCredential(config));
                break;
            }

            var blobInput = config.GetConnectionString("BlobStorage1")
                ?? config["BlobStorage1:blobServiceUri"]
                ?? throw new InvalidOperationException(
                    "DataProtection:Persistence=AzureBlob requires DataProtectionKeysFileUrl or BlobStorage1.");
            var containerName = config["DataProtection:AzureBlob:ContainerName"] ?? "data-protection";
            var blobName = config["DataProtection:AzureBlob:BlobName"] ?? "keys.xml";
            var blobService = CreateBlobServiceClient(blobInput, CreateAzureCredential(config));
            dataProtection.PersistKeysToAzureBlobStorage(
                blobService.GetBlobContainerClient(containerName).GetBlobClient(blobName));
            break;

        case DataProtectionPersistence.Redis:
            var redis = config.GetConnectionString("Redis1")
                ?? throw new InvalidOperationException(
                    "DataProtection:Persistence=Redis requires ConnectionStrings:Redis1.");
            // shortcut: use one eager connection only when the app does not expose a shared multiplexer.
            dataProtection.PersistKeysToStackExchangeRedis(ConnectionMultiplexer.Connect(redis));
            break;

        case DataProtectionPersistence.None:
            logger.LogWarning("Data Protection keys are ephemeral and do not survive restart or scale-out.");
            break;

        default:
            throw new InvalidOperationException($"Unsupported Data Protection persistence '{persistence}'.");
    }

    if (config["DataProtectionEncryptionKeyUrl"] is { Length: > 0 } encryptionKeyUrl)
        dataProtection.ProtectKeysWithAzureKeyVault(
            new Uri(encryptionKeyUrl), CreateAzureCredential(config));

    return builder.Services;
}
```

### Packages

- Azure Blob persistence: `Azure.Extensions.AspNetCore.DataProtection.Blobs`.
- Azure Key Vault encryption, only when configured: `Azure.Extensions.AspNetCore.DataProtection.Keys`.
- Redis persistence: `Microsoft.AspNetCore.DataProtection.StackExchangeRedis`.

### Rules

- Use the same application discriminator for every replica of one app and a different discriminator for unrelated apps sharing the store. Preserve the framework's existing discriminator when adding persistence to a deployed app unless deliberate token invalidation is planned.
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

- [ ] Rate limiting registered with per-tenant and/or per-endpoint policies
- [ ] Rate limiter disabled in `CustomApiFactory` only behind an explicit Testing guard, with a negative test proving Production retains the limiter ([testing.md](testing.md) section Never Silently Pass)
- [ ] `StructureValidator` enforces `MaxLength` matching EF configuration
- [ ] User content stays canonical in storage and is context-encoded at the rendering boundary
- [ ] Security headers middleware added (X-Content-Type-Options, X-Frame-Options)
- [ ] CORS configured in Gateway only - API rejects direct browser requests
- [ ] CI runs `dotnet list package --vulnerable --include-transitive` after restore and gates on its output; `<NuGetAudit>`/`<NuGetAuditLevel>` set in build props; no workflow references a `dotnet nuget audit` verb (it does not exist)
- [ ] Dependabot enabled only deliberately and configured per the GitHub Dependabot section (Dependabot secrets, manifest-per-directory, private-feed registries)
- [ ] Data Protection runtime `Persistence` matches the active lane: Azure Blob has a key URL or `BlobStorage1`, Redis has `Redis1`, and `None` is limited to isolated development/tests
- [ ] When Key Vault key encryption is selected, the encryption URL, managed identity permissions, stored secret policy, and rotation workflow are documented; strict NonAzure emits no Key Vault dependency
- [ ] `ValidateOnStart()` used for critical configuration sections
