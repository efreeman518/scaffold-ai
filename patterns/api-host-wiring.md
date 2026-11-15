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

The EF.Data tenant filter fails closed: a request with no tenant claim reads nothing ([../skills/multi-tenant.md](../skills/multi-tenant.md) section Automatic Query Filters). A multi-tenant scaffold reads its seeded rows because the `Scaffold` fixed principal (section Conditional Auth Configuration) carries the seeded dev tenant as its `tenant_id` claim. A single-tenant scaffold drops `ITenantEntity<TenantId>` and the tenant filter instead.

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

The host authenticates and authorizes from its first wiring. `AuthMode` has two values: `Scaffold` (the default: the EF.Auth fixed principal authenticates every request, so the backend maps no sign-in route) and `Entra` (the live provider, added to the same registration in Phase 5e: [../skills/identity-management.md](../skills/identity-management.md) section Live Provider Registration). `AuthMode` and `AuthModeResolver.Resolve` (an unknown value throws, so the host fails to start) live beside `ScaffoldPrincipal` in `Application.Contracts`. EF.Auth API list: [../support/ef-packages-optional.md](../support/ef-packages-optional.md) section Authentication (EF.Auth).

```csharp
// File: Host/{App}.Api/Auth/AuthConfiguration.cs
using EF.Auth.Fixed;

public static class AuthConfiguration
{
    public static IServiceCollection Add{App}Auth(this IServiceCollection services, IConfiguration config)
    {
        var mode = AuthModeResolver.Resolve(config["AuthMode"]);

        if (mode == AuthMode.Scaffold)
        {
            services.AddAuthentication(ScaffoldPrincipal.SchemeName)
                .AddFixedPrincipal(ScaffoldPrincipal.SchemeName, o =>
                {
                    o.Claims = [.. ScaffoldPrincipal.Claims.Select(c => new FixedClaim(c.Type, c.Value))];
                    o.AllowedEnvironments = [.. ScaffoldPrincipal.AllowedEnvironments];
                });
            return services;
        }

        // AuthMode.Entra: the live provider registration goes here (Phase 5e); without it the mode fails startup.
        throw new InvalidOperationException("AuthMode 'Entra' has no provider registration");
    }
}

// File: Host/{App}.Api/Auth/AuthorizationPolicies.cs
using Microsoft.AspNetCore.Authorization;

public static class AuthorizationPolicies
{
    public static IServiceCollection Add{App}Authorization(this IServiceCollection services)
    {
        services.AddAuthorizationBuilder()
            // Every AuthMode: an endpoint with no policy of its own still requires an authenticated user.
            .SetFallbackPolicy(new AuthorizationPolicyBuilder().RequireAuthenticatedUser().Build());
        // Named policies (roles, TenantMatch) are added on the same builder.
        return services;
    }
}
```

```csharp
// File: Application.Contracts/AuthMode.cs - the one mode decision; every HTTP host calls it
public enum AuthMode { Scaffold, Entra }

public static class AuthModeResolver
{
    // Unset means Scaffold; an unknown value fails startup. The fixed principal's AllowedEnvironments is the
    // guard: a host outside that list fails to start in Scaffold mode.
    public static AuthMode Resolve(string? value) => value?.Trim().ToLowerInvariant() switch
    {
        null or "" or "scaffold" => AuthMode.Scaffold,
        "entra" => AuthMode.Entra,
        _ => throw new InvalidOperationException($"AuthMode '{value}' is not Scaffold or Entra")
    };
}

// File: Application.Contracts/ScaffoldPrincipal.cs - shared by the Api and the Gateway so both register one identity
using System.Security.Claims;

public static class ScaffoldPrincipal
{
    public const string SchemeName = "Scaffold";

    // Environments the fixed identity may run in; kept in code so configuration can never widen it.
    // A login-free app that deploys as Production lists it deliberately and records that in its design
    // decisions; any other environment fails host start.
    public static IReadOnlyList<string> AllowedEnvironments { get; } = ["Development", "Testing"];

    public static IReadOnlyList<(string Type, string Value)> Claims { get; } =
    [
        // Audit id: the request context reads oid > NameIdentifier > sub. Use the FIXED seeded dev-user GUID
        // (SeedConstants.DevUserId) so a stamped owner FK resolves - never a random/string id.
        ("oid", SeedConstants.DevUserId.ToString()),
        (ClaimTypes.NameIdentifier, SeedConstants.DevUserId.ToString()),
        (ClaimTypes.Name, "Scaffold Principal"),
        // Tenant: the request context reads tenant_id; the seeded dev tenant GUID. Omit it and tenant is null.
        ("tenant_id", SeedConstants.DevTenantId.ToString()),
        // Roles MUST use ClaimTypes.Role; a bare "roles" string leaves roles empty.
        (ClaimTypes.Role, AppConstants.ROLE_GLOBAL_ADMIN)
    ];
}
```

`AddFixedPrincipal` authenticates every request as the configured claims, fails host start outside `AllowedEnvironments` (default `Development`, `Testing`) or with no claims, and logs one warning per scheme the first time it authenticates; generate no authentication handler. The scaffold principal authenticates HTTP requests only. Code running outside a request resolves the explicit system context (section Request Context Resolution), never this principal, its global-admin role, or the dev tenant. The Gateway resolves the mode through the same `AuthModeResolver` and registers the same principal and fallback policy ([../skills/gateway.md](../skills/gateway.md) section Authentication Model). A deployed host runs as `Production`, so it runs with `AuthMode: Entra` once Phase 5e has added the provider, or, for a login-free app, with `Production` in `AllowedEnvironments`.

**Anonymous endpoints are opted in one by one**, each with its reason at the site. The set is closed:

- **Health probes** (`/healthz/live`, `/healthz/ready`, `/healthz`): `MapEfHealthEndpoints` maps them anonymous because an orchestrator probe carries no identity. The package exempts them from every rate limiter, so an orchestrator probe is never throttled.
- **`GET /auth/mode`** on the host clients call (the Gateway when one is generated, else the API): a client reads the mode before it signs in. It returns only the validated public value (`{ "mode": "Scaffold" }` or `{ "mode": "Entra" }`), never tenant IDs, client IDs, authorities, or secrets, and it sits behind the host's rate limiter ([../skills/security.md](../skills/security.md) section Rate Limiting). Clients use it for presentation; the backend authorization gate remains the security boundary.

```csharp
// In the pipeline of the host clients call, after MapDefaultEndpoints.
var authMode = AuthModeResolver.Resolve(app.Configuration["AuthMode"]);
app.MapGet("/auth/mode", () => TypedResults.Ok(new { mode = authMode.ToString() }))
    .AllowAnonymous();   // read before sign-in; returns the public mode only
```
