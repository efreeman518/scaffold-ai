# API Host Wiring Patterns

Cross-project wiring for API host startup, request context, and conditional auth. Load before Phase 5b (App Core + Runtime) when API host orchestration or runtime/edge wiring is in scope.

For base types used here, see [../support/ef-packages-reference.md](../support/ef-packages-reference.md).

---

## API Startup Sequence

**Source:** `Host/{App}.Api/Program.cs`

The startup follows a strict order: early logger, service registration chain, build, pipeline, startup tasks, run. The entire body is wrapped in try/catch/finally using a `StaticLogging` logger created before the host exists.

```csharp
var builder = WebApplication.CreateBuilder(args);
var config = builder.Configuration;
var services = builder.Services;
var appName = config.GetValue<string>("AppName") ?? "{App}.Api";
var env = config.GetValue<string>("ASPNETCORE_ENVIRONMENT")
    ?? config.GetValue<string>("DOTNET_ENVIRONMENT") ?? "Undefined";

ILogger<Program> startupLogger = CreateStartupLogger();
startupLogger.LogInformation("{AppName} {Environment} - Startup.", appName, env);

try
{
    // 0. Azure App Configuration (EF.Host AddEfAzureAppConfiguration; no-op without AppConfig:Endpoint), first so
    //    every later configuration read sees its values.
    builder.Add{App}AppConfiguration();

    // 1. Service defaults (OpenTelemetry, health, correlation, host lifecycle, resilience) and trusted proxy forwarding
    builder.AddServiceDefaults();
    builder.AddProxyForwarding();                // EF.AspNetCore, section Proxy
    builder.Add{App}DataProtection(startupLogger); // EF.AspNetCore.DataProtection (security.md section Data Protection)

    // 2. Registration chain -- order matters for dependency resolution
    services
        .RegisterInfrastructureServices(config)  // config, caching, DB, request context, startup tasks
        .RegisterDomainServices(config)          // domain-specific registrations
        .RegisterApplicationServices(config)     // message handlers, app services
        .RegisterBackgroundServices(config)      // channel background queue
        .AddApiServices(config, startupLogger); // auth, routing, health checks, rate limiting

    // 3. Build + pipeline
    var app = builder.Build().ConfigurePipeline();

    // 4. Handler registration + EF.Host startup tasks (cache warmup, dev seeding - never schema migrations)
    await app.RunStartupTasks();

    // 5. Switch to runtime logger
    StaticLogging.SetStaticLoggerFactory(app.Services.GetRequiredService<ILoggerFactory>());

    await app.RunAsync();
}
catch (Exception ex)
{
    startupLogger.LogCritical(ex, "{AppName} {Environment} - Host terminated unexpectedly.", appName, env);
    throw;
}
finally
{
    startupLogger.LogInformation("{AppName} {Environment} - Ending application.", appName, env);
}

// Required for WebApplicationFactory in integration tests
public partial class Program { }
```

**Early logger factory** -- created before the host so startup failures are visible:

```csharp
ILogger<Program> CreateStartupLogger()
{
    StaticLogging.CreateStaticLoggerFactory(logBuilder =>
    {
        logBuilder.SetMinimumLevel(LogLevel.Information);
        logBuilder.AddConsole();
    });
    return StaticLogging.CreateLogger<Program>();
}
```

**Middleware pipeline order** (`Host/{App}.Api/WebApplicationBuilderExtensions.cs`):

```csharp
public static WebApplication ConfigurePipeline(this WebApplication app)
{
    // 1. Public scheme/host/client IP from the trusted proxy (EF.AspNetCore) - everything below reads them
    app.UseProxyForwarding();

    // 2. Security headers (EF.AspNetCore)
    app.UseBasicSecurityHeaders();

    // 3. Correlation tracking (EF.AspNetCore; AddCorrelationId is in ServiceDefaults)
    app.UseCorrelationId();

    // 4. Catch unhandled exceptions (before routing; AddEfProblemDetails)
    app.UseExceptionHandler();

    // 5. CORS
    app.UseCors("UiCors");

    // 6. Authenticate
    app.UseAuthentication();

    // 7. Authorize
    app.UseAuthorization();

    // 8. Rate limiting after auth so tenant partitions see the principal (skills/security.md)
    app.UseRateLimiter();

    // OpenAPI + Scalar (feature-gated)
    if (app.Configuration.GetValue<bool>("OpenApiSettings:Enable", true))
    {
        app.MapOpenApi();
        app.MapScalarApiReference(options =>
        {
            options.WithTitle("{App} API");
            options.WithTheme(ScalarTheme.Moon);
        });
    }

    // ServiceDefaults maps /healthz/live, /healthz/ready, and /healthz here (MapEfHealthEndpoints).
    app.MapDefaultEndpoints();

    // API endpoint groups
    SetupApiEndpoints(app);

    return app;
}
```

**Why:** Forwarded values must be applied before anything reads them, security and correlation must envelope every response, exception handling must wrap downstream failures, CORS must answer preflight before authentication, and authentication must establish the principal before authorization. Therefore preserve this middleware order.

---

## Gateway Claim Relay Trust Boundary

API may consume the relay header only after bearer authentication validates issuer, audience, and an allowlisted gateway application identity (`azp`/`appid`). `services.AddForwardedClaimsTransformation(config)` (EF.Auth) then replaces the principal with a new identity holding only the allowlisted forwarded claims plus a relayed-by marker; `IRequestContext` reads that principal, never the raw header. Direct-user-token and other service-token paths ignore the envelope. The canonical trust boundary and forged-header cases live in [gateway.md](../skills/gateway.md#forwarded-claims-trust-boundary); generate no claims transformer.

Bind the one `ForwardedClaims` section the Gateway binds (`HeaderName`, `ClaimTypes`, `TrustedCallerIds`). An empty `TrustedCallerIds` disables the relay (fail closed), so a scaffold that relays nothing registers the transformation with an empty list and stays inert.

---

## Request Context Resolution

**Source:** `Host/{App}.Bootstrapper/Registration/RegisterServices.RequestContext.cs`

The scoped `IRequestContext<string, Guid?>` is EF.AspNetCore's claims-based context; generate no factory:

```csharp
internal static void AddRequestContext(IServiceCollection services)
{
    services.AddHttpRequestContext<Guid?>(
        value => Guid.TryParse(value, out var tenantId) ? tenantId : null,
        options =>
        {
            options.SystemAuditId = AppConstants.SYSTEM_USER_ID;
            options.SystemRoles = [AppConstants.ROLE_SYSTEM];   // CrossTenantRoles includes it (multi-tenant.md)
        });
}
```

- Correlation id: `HttpContext.TraceIdentifier` (set by `UseCorrelationId`), else the W3C trace id, else a GUID.
- Authenticated request: audit id from `oid` > name identifier > `sub`, tenant from `tenant_id`, roles from `ClaimTypes.Role`.
- Unauthenticated request: `anonymous`, no tenant, no roles.
- No HttpContext (background job, consumer, Functions trigger): the explicit system context - no tenant, `SYSTEM_USER_ID`, and every `SystemRoles` role. Never the scaffold/dev principal or a default tenant. A token can never claim a system role: every `SystemRoles` entry is stripped from inbound roles.

> **Claim source must match these reads.** The Scaffold fixed principal emits roles as `ClaimTypes.Role`, tenant as `tenant_id`, and the seeded dev-user GUID as `oid` / `NameIdentifier` - see
> [../skills/identity-management.md](../skills/identity-management.md) section Claim-type contract. A mismatch silently empties roles and tenant.
> When claims originate at Gateway, the EF.Auth relay adds them only after validating the
> allowlisted gateway service identity in [gateway.md](../skills/gateway.md#forwarded-claims-trust-boundary). The request context reads the resulting
> principal; it never parses the relay header itself.

### No Tenant Means No Rows

The EF.Data tenant filter fails closed: a request with no tenant claim reads nothing ([../skills/multi-tenant.md](../skills/multi-tenant.md) section Automatic Query Filters). A multi-tenant scaffold therefore never runs with authentication off: from the first API wiring it registers the `Scaffold` fixed principal ([../skills/identity-management.md](../skills/identity-management.md)), whose `tenant_id` claim is the seeded dev tenant. A single-tenant scaffold drops `ITenantEntity<TenantId>` and the tenant filter instead.

**Symptom:** if a client lands at the API without a tenant claim, every list endpoint returns an empty payload and no error. Log the resolved tenant id at `Information` once per request during dev so the empty-payload case is observable.

### Dev-Mode Write Identity (owner/tenant stamping)

The tenant fallback above fixes the **read** path (query-filter tenant). The **write** path needs the
same treatment: DTOs retain `TenantId` for response and round-trip compatibility, but the browser does
not own that value. UI-driven creates may also carry a forged owner/created-by. If the server does not
stamp both from trusted context, writes can violate user/tenant FKs or accept forged ownership.

Stamp tenant from `IRequestContext` unconditionally before validation/mapping; never fall back to the
caller-supplied DTO value. For server-owned creator/owner fields, overwrite from the audit identity even
when the payload is non-empty. The application service is
the natural seam - it already stamps tenant in its `CreateAsync` (see
[../templates/service-template.md](../templates/service-template.md)):

```csharp
// Application service CreateAsync, before the factory call:
var authoritativeTenantId = RequestTenantId ?? Guid.Empty;
dto.TenantId = authoritativeTenantId;                 // overwrite untrusted payload
dto.OwnerId = ParseAuditId(requestContext.AuditId);   // overwrite untrusted payload
```

`Guid.Empty` deliberately fails structure validation when no request tenant exists. Do not recover with
`dto.TenantId`; that would let a caller establish its own tenant boundary.

For the owner FK to resolve, the audit id must be a real, seeded user GUID - hence the
Scaffold fixed principal carries the fixed `SeedConstants.DevUserId` and the dev seeder inserts that user (see
[../support/data-persistence-advanced.md](../support/data-persistence-advanced.md) section Startup Seeding). The
client may round-trip tenant/owner fields for contract compatibility, but the server owns them in every
mode. Production resolves both from claims; dev resolves them from the scaffold principal + seeded user.
If users may assign work to someone else, model a separate `AssigneeId` and authorize that operation;
do not overload server-owned creator/owner identity.

---

## Conditional Auth Configuration

**Source:** `Host/{App}.Api/Auth/AuthConfiguration.cs` + `Auth/AuthorizationPolicies.cs`

Auth is delegated to separate files under `Auth/`. In `RegisterApiServices.cs`:

```csharp
private static void AddAuthentication(IServiceCollection services, IConfiguration config, ILogger logger)
{
    services.Add{App}Auth(config);  // delegates to Auth/AuthConfiguration.cs
}

private static void AddAuthorization(IServiceCollection services)
{
    services.Add{App}Authorization();  // delegates to Auth/AuthorizationPolicies.cs
}
```

The auth configuration registers the EF.Auth fixed principal in `Scaffold` mode and JwtBearer + MicrosoftIdentityWebApi + fallback policy in live modes. The scaffold-vs-live `AuthMode` toggle and the `ScaffoldPrincipal` claims are owned by [../skills/identity-management.md](../skills/identity-management.md).
