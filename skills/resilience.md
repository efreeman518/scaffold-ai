# Resilience

> **When to read:** Phase 5b, when wiring any outbound HTTP client (external API, gateway-to-API, service-to-service) or reviewing retry/circuit/timeout behavior.
> **Skip if:** the app makes no outbound HTTP calls beyond Aspire service discovery defaults, or the current task is pure domain/data work.

Resilience policy for outbound calls: what the scaffold applies by default, when to customize, and what to leave alone. Package: `Microsoft.Extensions.Http.Resilience` (already part of the reference-app stack via ServiceDefaults).

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
- Retries are safe for idempotent calls (GET, PUT with full payload, DELETE). **Do not retry non-idempotent POSTs** unless the endpoint is idempotency-keyed; a retried create duplicates data. The ServiceDefaults `DisableForUnsafeHttpMethods()` enforces this; a client that re-enables unsafe-method retry for an idempotency-keyed endpoint records why.
- **Every gRPC call is an HTTP POST**, so `DisableForUnsafeHttpMethods()` removes all retries from a gRPC client. A read-only gRPC client registers its own standard handler without that filter and records that it serves only idempotent calls; a gRPC client that carries writes keeps retries off.

### Hedging

Hedging sends a parallel attempt when the first is slow, which cuts tail latency but multiplies load. It is opt-in per client for idempotent reads only, under the policy in [../support/scalability-and-hosting.md](../support/scalability-and-hosting.md) section Edge, TLS, and Rate Limits. One shape is valid: replace the client's handler with the standard hedging handler, guarded to GET/HEAD on both `ShouldHandle` and `DelayGenerator`.

```csharp
using Polly;

public static IHttpClientBuilder AddReadHedging(this IHttpClientBuilder builder)
{
#pragma warning disable EXTEXP0001 // RemoveAllResilienceHandlers is [Experimental]; the hedging handler must replace the ServiceDefaults handler. Remove this pragma when the API is no longer experimental.
    builder.RemoveAllResilienceHandlers();
#pragma warning restore EXTEXP0001

    builder.AddStandardHedgingHandler().Configure(options =>
    {
        var transient = options.Hedging.ShouldHandle;
        var delay = options.Hedging.Delay;

        // Outcome-triggered hedges: the standard transient predicate, narrowed to reads.
        options.Hedging.ShouldHandle = args =>
            IsRead(args.Context) ? transient(args) : ValueTask.FromResult(false);

        // Latency-triggered hedges consult no outcome, so they need their own guard.
        options.Hedging.DelayGenerator = args =>
            ValueTask.FromResult(IsRead(args.Context) ? delay : Timeout.InfiniteTimeSpan);
    });

    return builder;
}

private static bool IsRead(ResilienceContext context) =>
    context.GetRequestMessage()?.Method is { } method
    && (method == HttpMethod.Get || method == HttpMethod.Head);
```

- Only the standard hedging pipeline snapshots the `HttpRequestMessage` for each attempt. A custom `AddResilienceHandler(...).AddHedging(...)` sends the same request instance concurrently; never build hedging that way or nest it inside the standard handler.
- The standard hedging handler replaces the client's standard handler: attempt timeout, per-endpoint circuit breaker, and total timeout come from the hedging options, and GET retries become hedges. Guarding only `ShouldHandle` still duplicates a slow POST through the delay path.
- `RemoveAllResilienceHandlers` is marked `[Experimental("EXTEXP0001")]`. Each call site, here or in a replaced custom pipeline, carries the scoped pragma above with its reason and removal criterion; never a project-wide `NoWarn`.
- Tests prove a slow POST is sent exactly once and hedged attempts use distinct `HttpRequestMessage` instances. Proof: TaskFlow `src/Host/Aspire/ServiceDefaults/ReadHedgingExtensions.cs` and `tests/Test.Unit/Hosting/ReadHedgingTests.cs`.

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
- [ ] A hedged client replaced its handler with the GET/HEAD-guarded standard hedging handler, and tests prove a slow POST is sent once and each hedged attempt gets its own request instance
- [ ] Read-only gRPC clients keep retries explicitly; gRPC clients carrying writes do not retry
- [ ] Client total timeout exceeds the retry budget
- [ ] Circuit-breaker open state surfaces as a `Result` failure / `ProblemDetails`, not an unhandled exception (see [api.md](api.md) section Error Handling Strategy)
