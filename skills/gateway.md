# Gateway (YARP)

## Purpose

Gateway is a YARP reverse proxy in front of API/backends. It handles user-facing auth and CORS. The downstream token, the claims relay and the downstream health check are EF.Gateway over EF.Auth ([../support/ef-packages-optional.md](../support/ef-packages-optional.md) section Gateway (EF.Gateway)); generate no token service, claims transformer or relay header code.

## Non-Negotiables

1. Keep proxy routes/clusters in configuration and load through YARP.
2. Relay service-to-service bearer tokens per cluster with `AddDownstreamAuthTransforms` (cluster `Metadata:TokenScope`) over `AccessTokenCache`.
3. The relay header is gateway-owned: see Forwarded Claims Trust Boundary (a cluster opts in with `Metadata:RelayUserClaims`).
4. **The relay header and settings come from one shared `ForwardedClaims` section.** The Gateway binds it with `AddDownstreamAuthTransforms(config)` and the API with `AddForwardedClaimsTransformation(config)`, so the header name, claim allowlist and limits match; never write the header name as a literal on either side.
5. Keep pipeline order deterministic (forwarding -> security -> auth -> limiter -> endpoints -> proxy).
6. Normalize path prefixes consistently between UI, gateway transforms, and backend routes.
7. Normalize trusted forwarded scheme/host before OIDC or YARP so redirects use the public origin.

Reference patterns: [../patterns/api-host-wiring.md](../patterns/api-host-wiring.md) (Gateway Claim Relay).

---

## Project Shape

```
Host/{Gateway}.Gateway/
|-- Program.cs
|-- RegisterGatewayServices.cs
|-- appsettings.json
`-- Dockerfile
```

---

## YARP Configuration

```json
{
  "ReverseProxy": {
    "Routes": {
      "api-route": {
        "ClusterId": "api-cluster",
        "AuthorizationPolicy": "Default",
        "Match": { "Path": "/api/{**catch-all}" }
      }
    },
    "Clusters": {
      "api-cluster": {
        "Destinations": {
          "api": { "Address": "https://localhost:7065" }
        },
        "Metadata": {
          "TokenScope": "api://{api-client-id}/.default",
          "RelayUserClaims": "true"
        }
      }
    }
  },
  "ForwardedClaims": {
    "HeaderName": "X-Forwarded-User-Claims",
    "ClaimTypes": [ "sub", "oid", "name", "roles", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier",
                    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name", "http://schemas.microsoft.com/ws/2008/06/identity/claims/role", "tenant_id" ],
    "TrustedCallerIds": [ "{gateway-service-client-id}" ],
    "ServicePathPrefixes": [ "/healthz" ]
  }
}
```

With Aspire, destination resolution can be service-discovery driven. A cluster without `TokenScope` gets no token transform: the inbound `Authorization` header passes through unchanged, so never point such a cluster at a third party when the inbound token must not leave. A scaffold-mode gateway leaves `TokenScope` empty.

---

## Service Registration Pattern

```csharp
using EF.Auth.Tokens;
using EF.Gateway;
using EF.Host;

public static IServiceCollection AddGatewayServices(this IServiceCollection services, IConfiguration config)
{
    services.AddAzureTokenCredential(config);   // EF.Host: one TokenCredential (ManagedIdentityClientId / AzureTenantId)
    services.AddAccessTokenCache();             // EF.Auth: single-flight token cache over that credential
    services.AddEfProblemDetails();

    services.AddReverseProxy()
        .LoadFromConfig(config.GetSection("ReverseProxy"))
        .AddServiceDiscoveryDestinationResolver()
        .AddDownstreamAuthTransforms(config);   // binds ForwardedClaims, the same section the API binds

    services.AddCorsPolicyFromConfiguration("{Project}UI", config.GetSection("CorsSettings"));
    services.AddHealthChecks().AddDownstreamHealthCheck("{project}-api", o =>
    {
        o.Url = new Uri(config["AggregateHealthCheck:{Project}ApiHealthUrl"]!);   // missing or relative fails startup
        o.TokenScope = config["AggregateHealthCheck:TokenScope"];
    }, tags: ["full"]);
    return services;
}
```

> **Service discovery:** For Aspire-hosted scenarios, use service-discovery URI syntax (`https+http://{app}-api`) in cluster destinations and call `AddServiceDiscoveryDestinationResolver()` (package `Microsoft.Extensions.ServiceDiscovery.Yarp`); EF.Gateway does not reference it.

`AccessTokenCache` acquires per scope set with one identity-provider call per cold key, never shares a caller's cancellation, never caches a failure, and replaces a token inside its refresh window once. An acquisition failure fails the proxied request; it is never forwarded unauthenticated. A relay header over `MaxHeaderBytes` fails the request; it is never forwarded without the header.

### Forwarded Claims Trust Boundary

**Why:** Any client can forge an ordinary request header. Therefore the relay header carries context only; this exact boundary establishes trust:

1. Every claim-relaying proxy route requires an authenticated-user authorization policy. Pipeline order alone does not reject anonymous callers.
2. Gateway removes any inbound relay header on every route (the configured `HeaderName` and the default `X-Forwarded-User-Claims`) and regenerates one envelope only from the authenticated `HttpContext.User`.
3. Gateway replaces the user token with its downstream service token.
4. API bearer authentication validates issuer and audience; `AddForwardedClaimsTransformation` then honors the header only for an authenticated app-only token (no delegated-scope claim) whose `azp`/`appid` is in `ForwardedClaims:TrustedCallerIds`. An empty list disables the relay. With no valid header the gateway identity is unauthenticated (`RequireHeaderFromTrustedCaller`), except under `ServicePathPrefixes`: on those service-only paths (the API's `/healthz` prefix, for the gateway's app-only aggregate probe) a trusted caller that sends no header keeps its own principal, and a header that is sent is still verified. List only service endpoints there. A shared `SigningKey` optionally HMAC-signs the header. A configured `ClaimTypes` replaces the package default, so the list above is that default plus `tenant_id`.
5. Non-gateway service identities and direct-user-token paths ignore the header. `IRequestContext` reads only the resulting authenticated principal, never the raw envelope.

Required verification:

- `AnonymousClaimRelayRoute_IsRejectedBeforeProxy`: an anonymous caller never reaches the transform.
- `ForgedInboundEnvelope_IsOverwritten`: a caller-supplied envelope sent through Gateway cannot supply roles or tenant.
- `ForgedDirectEnvelope_WithoutTrustedGateway_IsIgnored`: a direct API call with no allowlisted gateway service identity returns 401/403 or leaves the principal unchanged.
- `TrustedCallerWithoutEnvelope_IsForbidden`: gateway identity, no envelope -> 403.
- `TrustedGatewayEnvelope_AddsExpectedClaims`: a valid gateway service token plus gateway-generated envelope produces only the expected user, role, and tenant claims, in a new identity that carries none of the gateway identity's claims.
- `DelegatedUserTokenForGatewayClient_IsIgnored`: a user token whose `azp` is the gateway client id cannot supply an envelope.
- `RepeatedTransformation_DoesNotDuplicateForwardedClaims`: repeated authentication transformation adds no duplicate identity or claim.

The package tests its own codec and transformation; the app keeps these cases because they prove its registration, its section binding and its route policies. Keep API-side wiring concise and point it back here; see [api-host-wiring.md](../patterns/api-host-wiring.md#gateway-claim-relay-trust-boundary).

---

## Authentication Model

The Gateway authenticates the user token (Entra External/B2C), sends its own `AccessTokenCache` service token downstream and regenerates the relay header; the API allowlists that service identity (Forwarded Claims Trust Boundary).

```csharp
private static void AddAuthentication(IServiceCollection services, IConfiguration config)
{
    services.AddAuthentication(options =>
    {
        options.DefaultScheme = JwtBearerDefaults.AuthenticationScheme;
    })
    .AddMicrosoftIdentityWebApi(config.GetSection("Gateway_EntraExt"));
    services.Configure<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme, o => o.MapInboundClaims = false);

    services.AddSingleton<IAuthorizationHandler, TenantMatchHandler>();
}
```

Claim types on both hosts must agree with `ForwardedClaims:ClaimTypes` ([identity-management.md](identity-management.md) section Claim-type contract). Scaffold mode registers the EF.Auth fixed principal instead (same file, section Pre-Auth Stub Pattern (Phases 5a-5d)).

---

## Pipeline Order

```csharp
app.UseProxyForwarding();   // EF.AspNetCore: public scheme/host/client IP first
app.UseExceptionHandler();
app.UseCors("{Project}UI");
app.UseCorrelationId();
app.UseAuthentication();
app.UseAuthorization();
app.UseRateLimiter();       // UseEdgeLimiter partitions on the forwarded client IP
app.UseRequestTimeouts();
app.MapDefaultEndpoints();  // MapEfHealthEndpoints
app.MapReverseProxy().RequireAuthorization();
```

**Why:** Proxy execution must follow authentication so transforms serialize a verified user principal, not attacker-supplied headers or an anonymous identity. Therefore claim-relaying routes require authorization and map only after authentication/authorization middleware.

---

## Multi-Hop Forwarded Headers and Path-Base Hosting

A chain such as edge proxy -> YARP Gateway -> app has two separate trust boundaries. Each process must adopt the public request values from its immediate trusted upstream before redirects, authentication, link generation, or proxying.

1. The edge proxy removes caller-supplied forwarding headers and writes the canonical `X-Forwarded-For`, `X-Forwarded-Proto`, and `X-Forwarded-Host` values.
2. Gateway runs `UseProxyForwarding()` before HTTPS redirection, authentication/OIDC, routing, and YARP. This changes `Request.Scheme` and `Request.Host` to the public values before YARP's default X-Forwarded transform re-stamps the downstream request.
3. The downstream app also runs `UseProxyForwarding()` first, before HTTPS redirection, static files, authentication/OIDC, routing, and endpoints.

`AddProxyForwarding()` (EF.AspNetCore, section `Proxy`) applies `X-Forwarded-For`, `-Proto` and `-Host` from trusted proxies and validates every value at registration; generate no `ForwardedHeadersOptions` code. The blanket `ASPNETCORE_FORWARDEDHEADERS_ENABLED=true` switch is not the complete chain pattern: it has a one-hop default and does not enable `X-Forwarded-Host`.

```json
"Proxy": {
  "ForwardedHeaders": { "Enabled": true, "ForwardLimit": 1, "KnownProxies": [ "{trusted-proxy-ip}" ], "AllowedHosts": [ "{public-host}" ] },
  "PathBase": ""
}
```

Prefer explicit `KnownProxies`/`KnownNetworks` and a finite `ForwardLimit`. Container networks with dynamic proxy addresses may instead set `TrustAllProxies: true` (not combinable with the allowlists) only when network policy makes the app port unreachable except through the controlled Gateway. Without a `ForwardLimit` it reads the whole chain (`ForwardLimit = null`), so set `ForwardLimit` to the proxy hop count and a client-supplied `X-Forwarded-For` entry cannot become the remote address. Trusting every proxy on a publicly reachable port lets clients forge scheme and host.

For an externally prefixed app such as `/admin`, preserve that prefix to the downstream host and set `Proxy:PathBase` (`"/admin"`), which applies `UsePathBase` before static files, routing, auth, and endpoints even with forwarding off. Derive the served HTML `<base href>` from the effective `Request.PathBase` and include the same prefix in redirect/logout URIs. If YARP strips the external prefix, the path base cannot rediscover it; either preserve the prefix or set `Proxy:PathBase` from controlled deployment configuration. ASP.NET Core forwarded-header middleware does not infer it from `X-Forwarded-Prefix`.

A per-IP edge limiter partitions on `Connection.RemoteIpAddress`, which is the ingress address until forwarded headers run. Enable forwarding with known proxies or networks in every deployed lane, before the limiter, and test that the partition key is the forwarded client address, not the ingress address.

Deployment proof uses the public URL: an unauthenticated challenge redirects to public `https://<host>/<path-base>/...`, and prefixed UI root, framework, content, API, and OIDC callback paths return the expected status. Internal `http://container:port` must not appear in a redirect.

---

## Path Prefix Normalization Rule

The `PathRemovePrefix` transform removes a prefix **before forwarding to the backend**. Only use it when the backend routes do NOT include that prefix.

| Backend routes registered at | Gateway route match | Correct transform |
|---|---|---|
| `/v1/tasks`, `/v1/categories` | `/api/{**catch-all}` | `PathRemovePrefix: "/api"` |
| `/api/tasks`, `/api/categories` | `/api/{**catch-all}` | *(no transform - keep the prefix)* |

**Wrong (causes 404):** stripping `/api` when the downstream routes already include it:
```
client: /api/categories  -> gateway strips /api -> backend: /categories  -> 404
```

**Correct:** omit the transform when backend and gateway share the same prefix, as the YARP Configuration route above does.

Pick one convention per project and apply it everywhere. Never use dual-prefix probing logic.

---

## Health and Startup Tasks

- `AddDownstreamHealthCheck` probes the API's health URL (2xx is Healthy; any other status, a timeout or an exception is the registration's failure status).
- Add startup warmup tasks (`IStartupTask`) for token acquisition/dependency checks before live traffic.

---

## Verification

- [ ] YARP routes/clusters load from config
- [ ] `AddDownstreamAuthTransforms(config)` registered; clusters declare `TokenScope` / `RelayUserClaims` metadata; no app token service or relay transform
- [ ] Gateway and API bind the same `ForwardedClaims` section
- [ ] forged-header cases in Forwarded Claims Trust Boundary pass
- [ ] gateway auth section matches intended identity provider config
- [ ] pipeline order is forwarding -> security -> auth -> limiter -> endpoints -> reverse proxy
- [ ] forwarded proto and host are applied before OIDC and YARP; downstream app trusts only its controlled proxy chain
- [ ] CORS origins match UI local/deployed origins
- [ ] path-prefix convention is documented and consistent across UI/gateway/API
- [ ] path-prefixed UI derives `<base href>` and redirect URIs from the effective `PathBase`
- [ ] downstream health check and startup warmup are registered
- [ ] cross-check with [aspire.md](aspire.md) and [iac.md](iac.md)
