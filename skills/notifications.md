# Notifications

Reference patterns: [../ai/SKILL.md](../ai/SKILL.md) section Non-Negotiables (pattern index).

## Purpose

Provide multi-channel outbound notifications (email, SMS, web push, app push) through a unified service with pluggable channel providers.

## Deployment Modes

1. **Integrated**: notification infrastructure registered in API host.
2. **Standalone**: separate `{Host}.Notification` host for independent scale/retry/isolation.

Use integrated for low/moderate throughput; standalone for high volume or operational isolation.

## Non-Negotiables

1. Keep channel-specific logic in channel providers, not in unified service.
2. Register providers conditionally from config presence.
3. Use resilience policies for external provider calls.
4. Keep credentials in Key Vault/user-secrets, never inline in appsettings.
5. `Infrastructure.Notification` must not depend on Domain/Application implementation projects.

---

## Structure

### Infrastructure library (always)

```
src/Infrastructure/{Project}.Infrastructure.Notification/
|-- ServiceCollectionExtensions.cs
|-- INotificationService.cs
|-- NotificationService.cs
|-- NotificationServiceSettings.cs
|-- Configuration/NotificationOptions.cs
|-- Model/
|-- Providers/
`-- Exceptions/
```

### Standalone host (optional)

```
src/Host/{Host}.Notification/
|-- Program.cs
|-- RegisterNotificationServices.cs
|-- Endpoints/
|-- Services/
`-- Telemetry/
```

---

## Core Contracts

Per-channel provider interfaces:

- `IEmailProvider`
- `ISmsProvider`
- `IWebPushProvider`
- `IAppPushProvider`

Unified contract:

- `INotificationService`

Unified service coordinates optional provider dependencies. Missing provider => graceful degradation (warn + false/no-op result).

---

## DI Registration Pattern

```csharp
public static IServiceCollection AddNotificationInfrastructure(
    this IServiceCollection services,
    IConfiguration config)
{
    var notificationSection = config.GetSection("Notification");

    // Email provider - register only when config exists
    var emailSection = notificationSection.GetSection("Email");
    if (emailSection.Exists())
    {
        var provider = emailSection.GetValue<string>("Provider") ?? "Smtp";
        services.Configure<EmailProviderOptions>(emailSection.GetSection(provider));

        _ = provider switch
        {
            "Smtp" => services.AddSingleton<IEmailProvider, SmtpEmailProvider>(),
            "SendGrid" => services.AddSingleton<IEmailProvider, SendGridEmailProvider>(),
            "AzureCommunication" => services.AddSingleton<IEmailProvider, AzureCommunicationEmailProvider>(),
            _ => throw new NotSupportedException($"Email provider '{provider}' is not supported.")
        };
    }

    // SMS provider - register only when config exists
    var smsSection = notificationSection.GetSection("Sms");
    if (smsSection.Exists())
    {
        var provider = smsSection.GetValue<string>("Provider") ?? "AzureCommunication";
        services.Configure<SmsProviderOptions>(smsSection.GetSection(provider));

        _ = provider switch
        {
            "Twilio" => services.AddSingleton<ISmsProvider, TwilioSmsProvider>(),
            "AzureCommunication" => services.AddSingleton<ISmsProvider, AzureCommunicationSmsProvider>(),
            _ => throw new NotSupportedException($"SMS provider '{provider}' is not supported.")
        };
    }

    // Unified service - always registered; graceful no-op when providers are absent
    services.AddSingleton<INotificationService, NotificationService>();

    services.AddHttpClient("NotificationClient")
        .AddStandardResilienceHandler();

    return services;
}
```

Integrated mode: call from Bootstrapper.

Standalone mode: register in notification host and expose minimal API endpoints.

---

## Provider Implementation Pattern

Each channel provider implements a single interface and encapsulates all vendor-specific logic.

```csharp
public class SmtpEmailProvider(
    IOptions<EmailProviderOptions> options,
    ILogger<SmtpEmailProvider> logger) : IEmailProvider
{
    public async Task<NotificationResult> SendAsync(EmailMessage message, CancellationToken ct)
    {
        try
        {
            using var client = new SmtpClient();
            await client.ConnectAsync(options.Value.Host, options.Value.Port, SecureSocketOptions.StartTls, ct);
            await client.AuthenticateAsync(options.Value.Username, options.Value.Password, ct);

            var mimeMessage = BuildMimeMessage(message);
            await client.SendAsync(mimeMessage, ct);
            await client.DisconnectAsync(quit: true, ct);

            return NotificationResult.Success(channel: "Email");
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "SMTP send failed for {Recipient}", message.To);
            return NotificationResult.Failed(channel: "Email", reason: ex.Message);
        }
    }
}
```

**Rules for provider implementations:**
1. Catch and wrap vendor exceptions - never let them propagate to `NotificationService`.
2. Return `NotificationResult` (success/failed) - let the caller decide whether to retry.
3. Log at `Warning` for transient failures, `Error` for permanent failures (invalid address, auth failure).
4. Accept cancellation tokens throughout.

---

## Stub Provider for Local Development

Register a stub provider that writes to the console/log instead of calling external services:

```csharp
public class StubEmailProvider(ILogger<StubEmailProvider> logger) : IEmailProvider
{
    public Task<NotificationResult> SendAsync(EmailMessage message, CancellationToken ct)
    {
        logger.LogInformation("[StubEmail] To={To} Subject={Subject} Body={BodyPreview}",
            message.To, message.Subject, message.Body?[..Math.Min(100, message.Body.Length)]);

        return Task.FromResult(NotificationResult.Success(channel: "Email-Stub"));
    }
}
```

Register stubs via a `"Stub"` provider value in configuration:
```json
{
  "Notification": {
    "Email": { "Provider": "Stub" },
    "Sms": { "Provider": "Stub" }
  }
}
```

This eliminates external dependencies during development while preserving the full notification pipeline.

---

## Message-Driven Notifications (Service Bus Integration)

For high-volume or latency-tolerant notifications, decouple with messaging:

```
[API / Event Handler] -> publishes NotifyCommand -> [Service Bus Queue] -> [Notification Handler] -> [Provider]
```

**NotifyCommand message:**
```csharp
public record NotifyCommand(
    string Channel,         // "Email", "Sms", "Push"
    string Recipient,
    string TemplateId,
    Dictionary<string, string> TemplateData);
```

**Service Bus handler (standalone notification host):**
```csharp
public class NotifyCommandHandler(INotificationService notificationService) : IMessageHandler<NotifyCommand>
{
    public async Task HandleAsync(NotifyCommand command, CancellationToken ct)
    {
        // Route to correct channel via unified service
        await notificationService.SendAsync(command, ct);
    }
}
```

**When to use message-driven notifications:**
- Sends triggered by domain events (order confirmed, user registered).
- Batch/bulk sends where throttling matters.
- Standalone notification host deployment mode.

**When to use direct (in-process) notifications:**
- User-initiated sends (password reset, verification code).
- Low volume, latency-sensitive notifications.
- Integrated deployment mode.

---

## Usage Pattern

Typical event-handler usage:

```csharp
public class CallReminderHandler(INotificationService notificationService) : IMessageHandler<CallReminderEvent>
{
    public async Task HandleAsync(CallReminderEvent message, CancellationToken ct)
    {
        await notificationService.SendSmsAsync(new SmsMessage
        {
            To = message.PhoneNumber,
            Body = $"Reminder: your call is scheduled for {message.ScheduledTime:g}"
        }, ct);
    }
}
```

---

## Configuration Surface

`Notification` section should include channel-specific provider settings and optional batch throttling.

Representative keys:

- `Notification:Email:Provider`
- `Notification:Email:Smtp:*`
- `Notification:Sms:Provider`
- `Notification:Sms:Twilio:*`
- `Notification:BatchThrottling:MaxConcurrency`
- `Notification:BatchThrottling:DelayBetweenBatchesMs`

---

## Lite Mode

For `scaffoldMode: lite`:

- skip notifications unless explicitly requested,
- if requested, use integrated + email-only,
- skip batch endpoints/telemetry/extra channels by default.

---

## Operational Rules

1. Keep provider registration configuration-driven.
2. Add retry/circuit-breaker resilience for outbound provider clients.
3. Respect throttling limits for batch sends (provider rate limits).
4. Keep infrastructure library reusable across integrated and standalone modes.
5. Avoid duplicate provider implementations across hosts.

---

## Testing Patterns

### Unit tests (provider logic)

Mock the vendor HTTP client / SDK and verify:
- Correct message mapping (recipient, body, subject).
- `NotificationResult.Success` on 2xx response.
- `NotificationResult.Failed` (not exception) on vendor error.
- Cancellation token is forwarded.

```csharp
[Fact]
public async Task SendAsync_VendorReturns200_ReturnsSuccess()
{
    // Arrange: configure MockHttpMessageHandler to return 200
    var provider = new SendGridEmailProvider(options, httpClientFactory, logger);

    // Act
    var result = await provider.SendAsync(testMessage, CancellationToken.None);

    // Assert
    result.IsSuccess.Should().BeTrue();
    result.Channel.Should().Be("Email");
}
```

### Integration tests (unified service)

Register real `NotificationService` with stub providers. Verify:
- Missing provider => graceful no-op, warning logged, no exception.
- Present provider => delegated correctly.
- Multiple channels in single notification => all providers called.

### Message-driven tests (if using Service Bus)

Use the standard `IMessageHandler<T>` test patterns from the messaging skill:
- Handler deserialises `NotifyCommand` and calls `INotificationService.SendAsync`.
- Failed send => message is not completed (dead-lettered for retry).

---

## Verification

- [ ] infrastructure notification project builds cleanly
- [ ] standalone host (if enabled) builds and starts
- [ ] `INotificationService` is registered in DI
- [ ] channel providers register only when config exists
- [ ] no Domain/Application implementation dependencies in infrastructure notification project
- [ ] secrets are sourced from secure providers (not plain appsettings)
- [ ] resilience policies are enabled for external notification calls