# Exception Handler Template

| | |
|---|---|
| **File** | `Host/{Host}.Api/Middleware/DefaultExceptionHandler.cs` |
| **Depends on** | [api.md](../skills/api.md) |
| **Referenced by** | [api.md](../skills/api.md), [api-host-wiring.md](../patterns/api-host-wiring.md) |

## Purpose

Global `IExceptionHandler` that maps unexpected/infrastructure exceptions to `ProblemDetails` responses. This is the **safety net** - not a control-flow mechanism. All expected business outcomes flow through `Result<T>`/`DomainResult<T>`.

## Template

```csharp
// File: Host/{Host}.Api/Middleware/DefaultExceptionHandler.cs
using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Mvc;

namespace {Host}.Api.Middleware;

internal sealed class DefaultExceptionHandler(
    ILogger<DefaultExceptionHandler> logger,
    IHostEnvironment environment,
    IProblemDetailsService problemDetailsService) : IExceptionHandler
{
    public async ValueTask<bool> TryHandleAsync(
        HttpContext httpContext,
        Exception exception,
        CancellationToken cancellationToken)
    {
        // Guard: if the response has already started (e.g. streaming), writing
        // a ProblemDetails body would throw a second exception and mask the original.
        if (httpContext.Response.HasStarted) return true;

        var (statusCode, title) = exception switch
        {
            Microsoft.EntityFrameworkCore.DbUpdateConcurrencyException
                => (StatusCodes.Status409Conflict, "Concurrency conflict"),
            UnauthorizedAccessException
                => (StatusCodes.Status403Forbidden, "Forbidden"),
            OperationCanceledException
                => (499, "Client closed request"),   // 499 = nginx convention
            ArgumentException or FormatException
                => (StatusCodes.Status400BadRequest, "Bad request"),
            _
                => (StatusCodes.Status500InternalServerError, "Internal server error")
        };

        logger.LogError(exception, "Unhandled exception: {ExceptionType} - {Message}",
            exception.GetType().Name, exception.Message);

        var problemDetails = new ProblemDetails
        {
            Status = statusCode,
            Title = title,
            Detail = environment.IsDevelopment() || environment.IsStaging()
                ? exception.ToString()
                : exception.Message,
            Instance = httpContext.Request.Path
        };

        httpContext.Response.StatusCode = statusCode;
        return await problemDetailsService.TryWriteAsync(new ProblemDetailsContext
        {
            HttpContext = httpContext,
            ProblemDetails = problemDetails
        });
    }
}
```

## Registration

Register in `RegisterApiServices.cs`:

```csharp
services.AddExceptionHandler<DefaultExceptionHandler>();
services.AddProblemDetails(options =>
{
    options.CustomizeProblemDetails = context =>
    {
        var activity = System.Diagnostics.Activity.Current;
        context.ProblemDetails.Extensions.Remove("activityId");
        context.ProblemDetails.Extensions["requestId"] = context.HttpContext.TraceIdentifier;
        if (activity is null)
        {
            context.ProblemDetails.Extensions.Remove("traceId");
            context.ProblemDetails.Extensions.Remove("spanId");
            return;
        }

        context.ProblemDetails.Extensions["traceId"] = activity.TraceId.ToString();
        context.ProblemDetails.Extensions["spanId"] = activity.SpanId.ToString();
    };
});
```

Add to pipeline in `WebApplicationBuilderExtensions.cs` (before routing):

```csharp
app.UseExceptionHandler();
```

## Exception-to-Status Mapping

| Exception Type | HTTP Status | Title |
|---|---|---|
| `DbUpdateConcurrencyException` | 409 Conflict | Concurrency conflict |
| `UnauthorizedAccessException` | 403 Forbidden | Forbidden |
| `OperationCanceledException` | 499 | Client closed request |
| `ArgumentException` / `FormatException` | 400 Bad Request | Bad request |
| All others | 500 Internal Server Error | Internal server error |

## Rules

- **Safety net only** - business validation errors must use `Result<T>` / `DomainResult<T>`, never exceptions.
- Stack traces: include full `exception.ToString()` in Development/Staging; show only `exception.Message` in Production.
- Always log at `Error` level with structured placeholders.
- Return `true` to indicate the exception is handled and prevent further pipeline propagation.
- Write through `IProblemDetailsService` so the same correlation customizer applies to exception and typed endpoint errors.
- Add new exception mappings as needed (e.g., `HttpRequestException` -> 502 for downstream failures).
- **Always check `httpContext.Response.HasStarted` before writing the response body.** Writing to an already-started response throws a second exception and masks the original.
- **`OperationCanceledException` from EF Core is best caught in the service method**, not here. The VS debugger breaks at the throw site before this handler runs, so the handler alone cannot suppress break-on-exception dialogs. Catch it in the service and return an empty/default result; let this handler remain a true last-resort fallback.

## Verification Checklist

- [ ] Registered via `AddExceptionHandler<DefaultExceptionHandler>()` in `RegisterApiServices.cs`
- [ ] `UseExceptionHandler()` called in pipeline before routing
- [ ] `AddProblemDetails(...)` registered with separate `requestId`, W3C `traceId`, and `spanId`
- [ ] Typed errors and exception errors both exercise the correlation contract
- [ ] Stack traces gated by environment (not exposed in Production)
- [ ] All mapped exceptions return correct HTTP status codes
- [ ] Logging uses structured placeholders, not string interpolation
- [ ] No business logic errors handled here - those use `Result<T>` pattern
