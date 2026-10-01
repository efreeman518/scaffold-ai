# Resilience

> **When to read:** Phase 5b, when wiring any outbound HTTP client (external API, gateway-to-API, service-to-service) or reviewing retry/circuit/timeout behavior.
> **Skip if:** the app makes no outbound HTTP calls beyond Aspire service discovery defaults, or the current task is pure domain/data work.

Resilience policy for outbound calls: what the scaffold applies by default, when to customize, and what to leave alone. Packages: `Microsoft.Extensions.Http.Resilience` (ServiceDefaults standard handler) and EF.Http.Resilience (read hedging, client custom resilience).

## Standard Resilience Handler (default path)

Every `HttpClient` registered through `AddServiceDefaults()` gets `AddStandardResilienceHandler()` automatically, with retries disabled for unsafe methods (`POST`, `PATCH`, `PUT`, `DELETE`, `CONNECT`) - see [../patterns/infrastructure-wiring.md](../patterns/infrastructure-wiring.md) section ServiceDefaults Configuration. The standard pipeline bundles, in order: rate limiter, total-request timeout, retry (exponential + jitter), circuit breaker, and per-attempt timeout. Service-discovery internal calls (API -> API, Gateway -> API) therefore need **no additional wiring** - the default is the policy.

## Custom Per-Client Pipelines

Use a named `AddResilienceHandler` only for external third-party APIs whose failure profile differs from internal traffic (aggressive provider rate limits, slow cold starts, flaky sandboxes). The canonical Refit + settings-driven example lives in [external-api.md](external-api.md) section DI + Refit + Resilience - do not duplicate that code; bind the knobs through `{ServiceName}Settings`.

Default knobs (aligned with the `{ServiceName}Settings` shape):

| Knob | Default | Notes |
|---|---|---|
| `RetryCount` | 3 | Exponential backoff, `UseJitter = true` |
| `CircuitBreakerThreshold` (`MinimumThroughput`) | 5 | `FailureRatio` 0.5 over a 30s sampling window |
| Break duration | 15s | Probe half-open after this |
| Per-attempt timeout | 10s | Inside the pipeline |
| `TimeoutSeconds` (client total) | 30 | `HttpClient.Timeout` is the outer bound |

Keep the client total timeout larger than `retries x per-attempt timeout` budget or retries get cut off mid-flight.

## Internal-Call Guidance

- **Never stack pipelines.** A client that already has the standard handler (via ServiceDefaults) must not also get a custom `AddResilienceHandler` - double retry multiplies load during incidents. Replace it instead: `RemoveAllResilienceHandlers()` then the one custom handler for that client (hedging included; see Hedging).
- Retries are safe for idempotent calls (GET, PUT with full payload, DELETE). **Do not retry non-idempotent POSTs** unless the endpoint is idempotency-keyed ([data-persistence.md](data-persistence.md) section Idempotent Create); a retried create duplicates data. The ServiceDefaults `DisableForUnsafeHttpMethods()` enforces this; a client that re-enables unsafe-method retry for an idempotency-keyed endpoint records why.
- **Every gRPC call is an HTTP POST**, so `DisableForUnsafeHttpMethods()` removes all retries from a gRPC client. A read-only gRPC client registers its own standard handler without that filter and records that it serves only idempotent calls; a gRPC client that carries writes keeps retries off.

### Hedging

Hedging (EF.Http.Resilience `AddReadHedging`; [../support/ef-packages-optional.md](../support/ef-packages-optional.md) section Client Resilience) sends a parallel attempt when the first is slow, which cuts tail latency but multiplies load. It is opt-in per client for idempotent reads only, under the policy in [../support/scalability-and-hosting.md](../support/scalability-and-hosting.md) section Edge, TLS, and Rate Limits. One shape is valid, and it is packaged: `AddReadHedging(configuration)` from EF.Http.Resilience on a dedicated read client; generate no hedging extension.

```csharp
// Section Resilience:Hedging: Enabled (true), DelayMs (250), MaxHedgedAttempts (1..10)
builder.Services.AddHttpClient<I{Project}ReadApi, {Project}ReadApi>(c => c.BaseAddress = apiBaseUri)
    .AddReadHedging(builder.Configuration);
```

- Only the standard hedging pipeline snapshots the `HttpRequestMessage` for each attempt. A custom `AddResilienceHandler(...).AddHedging(...)` sends the same request instance concurrently; never build hedging that way or nest it inside the standard handler.
- `AddReadHedging` removes every resilience handler the client already has (the ServiceDefaults one included) and installs the standard hedging handler guarded to GET/HEAD on both the transient-outcome trigger and the latency trigger, so a slow POST is never duplicated. Attempt timeout, per-endpoint circuit breaker, and total timeout come from the hedging options, and GET retries become hedges. Apply it to a read-only client; a client that also writes keeps the standard handler.
- A UI or console client outside ServiceDefaults that needs the standard handler with excluded status codes uses `AddCustomResilience(excludedStatusCodes, ...)` (EF.Http.Resilience), which never retries unsafe methods unless `retryUnsafeMethods: true`.
- The package's tests prove a slow POST is sent once and hedged attempts use distinct `HttpRequestMessage` instances; the app proves only that the read client, and no write client, carries it.

- In-process calls (service -> repository, domain methods) get no resilience wrapper - failures there are bugs or store outages, surfaced through `Result<T>`/exceptions, not retried.

## What NOT to Wrap

| Dependency | Why no HTTP resilience pipeline |
|---|---|
| EF Core / SQL | `EnableRetryOnFailure` on the provider owns transient retry - see [data-persistence.md](data-persistence.md) |
| Service Bus / Azure SDK clients | The SDKs ship built-in retry policies; configure via client options, not a wrapper |
| FusionCache-backed reads | Fail-safe serves stale entries under dependency failure - see [caching.md](caching.md); adding HTTP retry underneath delays the fail-safe path |
| Scaffold no-op stubs | Stubs never fail; wrapping them hides nothing and adds noise |

## Verification

- [ ] Internal clients rely on ServiceDefaults only (no custom pipeline stacked on the standard handler)
- [ ] Each external client has exactly one named pipeline with settings-bound knobs
- [ ] No retry on non-idempotent POSTs without an idempotency key; ServiceDefaults keeps `DisableForUnsafeHttpMethods()`
- [ ] A hedged client is a read-only client with `AddReadHedging(configuration)`; no app hedging extension and no write client carries it
- [ ] Read-only gRPC clients keep retries explicitly; gRPC clients carrying writes do not retry
- [ ] Client total timeout exceeds the retry budget
- [ ] Circuit-breaker open state surfaces as a `Result` failure / `ProblemDetails`, not an unhandled exception (see [api.md](api.md) section Error Handling Strategy)
