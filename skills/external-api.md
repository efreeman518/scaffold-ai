# External API Integration

> **Shared infrastructure pattern:** External APIs and messaging services both follow the same integration chain: **Settings class -> Named client/auth handler -> DI extension method (the client inherits the ServiceDefaults resilience handler) -> Wrapper service**. This file shows the pattern for external APIs. For messaging-specific adapters (Service Bus, Event Grid, Event Hub), see [messaging.md](messaging.md) which follows the same structural conventions.

Use one infrastructure project per external API: `Infrastructure.{ServiceName}`.

## Structure

```text
src/Infrastructure/{Project}.Infrastructure.{ServiceName}/
  I{ServiceName}Api.cs
  {ServiceName}Service.cs
  {ServiceName}Settings.cs
  ServiceCollectionExtensions.cs
  Handlers/{ServiceName}AuthHandler.cs
  Models/*Request.cs
  Models/*Response.cs
```

Rule: Application layer depends on `I{ServiceName}Service` (contracts), not Refit types.

---

## Packages

```xml
<PackageReference Include="Refit.HttpClientFactory" />
<PackageReference Include="Microsoft.Extensions.Options.ConfigurationExtensions" />
```

Version all packages in `Directory.Packages.props`.

---

## Refit Contract

```csharp
public interface I{ServiceName}Api
{
    [Post("/v1/charges")]
    Task<CreateChargeResponse> CreateChargeAsync([Body] CreateChargeRequest request, CancellationToken ct = default);

    [Get("/v1/charges/{chargeId}")]
    Task<ChargeResponse> GetChargeAsync(string chargeId, CancellationToken ct = default);

    [Post("/v1/refunds")]
    Task<RefundResponse> CreateRefundAsync([Body] CreateRefundRequest request, CancellationToken ct = default);
}
```

Keep Refit models provider-shaped (snake_case, provider fields), not domain-shaped.

---

## Settings + Auth Handler

```csharp
public class {ServiceName}Settings
{
    public const string ConfigSectionName = "{ServiceName}";
    public string BaseUrl { get; set; } = null!;
    public string ApiKey { get; set; } = null!;
}

public class {ServiceName}AuthHandler(IOptions<{ServiceName}Settings> settings) : DelegatingHandler
{
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
    {
        request.Headers.Authorization = new("Bearer", settings.Value.ApiKey);
        return base.SendAsync(request, ct);
    }
}
```

---

## DI + Refit + Resilience

The client takes the standard resilience handler every `HttpClient` inherits from `AddServiceDefaults()` (retry on safe methods only, circuit breaker, attempt and total timeouts) and adds nothing to it. Policy, the override for a provider the defaults do not fit, and what not to wrap: [resilience.md](resilience.md).

```csharp
public static class ServiceCollectionExtensions
{
    public static IServiceCollection Add{ServiceName}(this IServiceCollection services, IConfiguration configuration)
    {
        var section = configuration.GetSection({ServiceName}Settings.ConfigSectionName);
        services.Configure<{ServiceName}Settings>(section);
        var settings = section.Get<{ServiceName}Settings>()!;

        services.AddTransient<{ServiceName}AuthHandler>();

        // Resilience: the standard handler inherited from ServiceDefaults. It does not retry a POST, so a
        // payment or other non-idempotent call is sent once.
        services
            .AddRefitClient<I{ServiceName}Api>()
            .ConfigureHttpClient(c => c.BaseAddress = new Uri(settings.BaseUrl))
            .AddHttpMessageHandler<{ServiceName}AuthHandler>();

        services.AddScoped<I{ServiceName}Service, {ServiceName}Service>();
        return services;
    }
}
```

---

## Wrapper Service Pattern

```csharp
public class {ServiceName}Service(
    I{ServiceName}Api api,
    ILogger<{ServiceName}Service> logger) : I{ServiceName}Service
{
    public async Task<DomainResult<PaymentResultDto>> ProcessPaymentAsync(PaymentRequestDto request, CancellationToken ct = default)
    {
        try
        {
            var response = await api.CreateChargeAsync(new CreateChargeRequest
            {
                AmountInCents = request.AmountInCents,
                Currency = request.Currency,
                PaymentSourceToken = request.SourceToken
            }, ct);

            return DomainResult<PaymentResultDto>.Success(new PaymentResultDto
            {
                ExternalId = response.Id,
                Status = MapStatus(response.Status),
                AmountInCents = response.AmountInCents
            });
        }
        catch (ApiException ex)
        {
            logger.LogError(ex, "External API failure");
            return DomainResult<PaymentResultDto>.Failure("External provider request failed.");
        }
    }
}
```

Rules:
1. Map provider models to app DTOs in wrapper service.
2. Catch `ApiException`; log detail, return sanitized failure message.
3. Never expose provider internals directly to callers.

---

## Bootstrapper

```csharp
services.Add{ServiceName}(config);
```

---

## Testing

- Unit-test wrapper by mocking `I{ServiceName}Api`.
- Integration tests replace Refit registration with mock service client.
- Validate mapping and sanitized error handling. Retries belong to the inherited handler, which a mocked `I{ServiceName}Api` does not run; assert none here.

### Webhook / Callback Contract (if provider pushes events)

When an external provider posts callbacks into your system:

- validate signature header(s) and timestamp tolerance
- reject and audit invalid or replayed payloads
- deduplicate by provider event ID before state transitions
- publish internal events only after validation and dedup succeed

---

## Verification

- [ ] `Infrastructure.{ServiceName}` contains contract, handler, settings, wrapper, DI extension
- [ ] Refit package declared centrally
- [ ] The client inherits the ServiceDefaults standard handler and adds no second one; an override follows [resilience.md](resilience.md) section Per-Client Override.
- [ ] Wrapper implements `Application.Contracts` abstraction
- [ ] No raw `HttpClient` usage in app/domain layers

---

## Required vs Enrichment Calls

Classify every external call at the call site: **required** (the operation cannot succeed without it) or **enrichment** (adds optional data). Enrichment failures log and degrade to the unresolved value - they never propagate into the primary operation's status. A geocoding 401 must not turn a profile save into a 500. Cancellation still propagates; work that depends on the missing enrichment skips rather than throws.

## Stubbing Unresolved External APIs

When an external API is not yet configured (no credentials, no base URL, or provider not chosen). Canonical stub shapes, safe-default table, and `// TODO: [CONFIGURE]` placement: [../templates/no-op-stub-template.md](../templates/no-op-stub-template.md).

1. **Generate a compilable stub** - implement `I{ServiceName}Service` as a no-op that returns `DomainResult.Success()` with placeholder data
2. **Mark all integration points** with `// TODO: [CONFIGURE] {ServiceName} - replace stub with real implementation`
3. **Include comments** in `appsettings.json` sections indicating placeholder values
4. The project must **build and run** with stubs in place (no exceptions, graceful no-ops)

```csharp
// Stub implementation - replace when external provider is configured
public class {ServiceName}ServiceStub : I{ServiceName}Service
{
    // TODO: [CONFIGURE] {ServiceName} - replace this stub with the real {ServiceName}Service implementation
    public Task<DomainResult<PaymentResultDto>> ProcessPaymentAsync(PaymentRequestDto request, CancellationToken ct = default)
        => Task.FromResult(DomainResult<PaymentResultDto>.Success(new PaymentResultDto
        {
            ExternalId = "stub-" + Guid.NewGuid().ToString("N")[..8],
            Status = "Pending",
            AmountInCents = request.AmountInCents
        }));
}
```
