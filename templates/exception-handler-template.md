# Exception Handler Template

| | |
|---|---|
| **File** | `Host/{Host}.Api/Middleware/DefaultExceptionHandler.cs` |
| **Depends on** | [api.md](../skills/api.md) |
| **Referenced by** | [api.md](../skills/api.md), [api-host-wiring.md](../patterns/api-host-wiring.md) |

> **Token vs log placeholder:** `{ExceptionType}` and `{Message}` in the `LogError` template below are **log property names** bound to the trailing arguments, not scaffold tokens - leave them verbatim. Only `{Host}` on this page is substituted. Rule: [../ai/placeholder-tokens.md](../ai/placeholder-tokens.md) section Disambiguating Tokens From Logging And Interpolation.

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
    private const int StatusClientClosedRequest = 499;   // nginx convention
    private const string ServerErrorDetail = "An unexpected error occurred.";

    public async ValueTask<bool> TryHandleAsync(
        HttpContext httpContext,
        Exception exception,
        CancellationToken cancellationToken)
    {
        // Guard: if the response has already started (e.g. streaming), writing
        // a ProblemDetails body would throw a second exception and mask the original.
        if (httpContext.Response.HasStarted) return true;

        // Only a cancellation the caller caused is a 499. A downstream timeout or an internal token
        // also surfaces as OperationCanceledException and must stay visible as a server failure.
        if (exception is OperationCanceledException && httpContext.RequestAborted.IsCancellationRequested)
        {
            logger.LogInformation("Request cancelled by the client.");
            httpContext.Response.StatusCode = StatusClientClosedRequest;
            return true;
        }

        var (statusCode, title) = exception switch
        {
            // A lost update between load and save. No ETag here: the middleware clears it.
            Microsoft.EntityFrameworkCore.DbUpdateConcurrencyException
                => (StatusCodes.Status412PreconditionFailed, "Precondition failed"),
            UnauthorizedAccessException
                => (StatusCodes.Status403Forbidden, "Forbidden"),
            BadHttpRequestException
                => (StatusCodes.Status400BadRequest, "Bad request"),
            OperationCanceledException when HasTimeoutInChain(exception)
                => (StatusCodes.Status504GatewayTimeout, "Gateway timeout"),
            _
                => (StatusCodes.Status500InternalServerError, "Internal server error")
        };

        logger.LogError(exception, "Unhandled exception: {ExceptionType} - {Message}",
            exception.GetType().Name, exception.Message);

        var problemDetails = new ProblemDetails
        {
            Status = statusCode,
            Title = title,
            Detail = environment.IsDevelopment() ? exception.ToString()
                : statusCode >= StatusCodes.Status500InternalServerError ? ServerErrorDetail
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

    private static bool HasTimeoutInChain(Exception exception)
    {
        for (var inner = exception.InnerException; inner is not null; inner = inner.InnerException)
        {
            if (inner is TimeoutException) return true;
        }

        return false;
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
| `OperationCanceledException` while `HttpContext.RequestAborted` is cancelled | 499 (no body) | - |
| `DbUpdateConcurrencyException` | 412 Precondition Failed (no ETag) | Precondition failed |
| `UnauthorizedAccessException` | 403 Forbidden | Forbidden |
| `BadHttpRequestException` | 400 Bad Request | Bad request |
| `OperationCanceledException` with a `TimeoutException` in the inner chain | 504 Gateway Timeout | Gateway timeout |
| All others, including any other `OperationCanceledException` | 500 Internal Server Error | Internal server error |

## Rules

- **Safety net only** - business validation errors must use `Result<T>` / `DomainResult<T>`, never exceptions.
- Detail: full `exception.ToString()` in Development only. Outside Development a 5xx carries the fixed generic `ServerErrorDetail`, never exception text; SQL, connection, and internal messages belong in the log.
- 499 only when `HttpContext.RequestAborted` is cancelled. Any other cancellation is a server-side timeout or fault: 504 when a `TimeoutException` is in the chain, otherwise 500.
- A 412 from this handler never carries an ETag: `ExceptionHandlerMiddleware` clears the ETag and cache headers before any handler runs, so a header set here never reaches the client. The stale-`If-Match` 412 with the current ETag comes from the endpoint filter/Result path ([../skills/data-persistence.md](../skills/data-persistence.md) section Provider Branch and Concurrency Discipline).
- Beyond the rows above, only app-owned exception types map to 4xx. Framework `ArgumentException`, `FormatException`, `InvalidOperationException`, and `KeyNotFoundException` stay 500 unless an app type wraps them: the same type thrown by a library is a server fault, not the caller's mistake.
- Always log at `Error` level with structured placeholders.
- Return `true` to indicate the exception is handled and prevent further pipeline propagation.
- Write through `IProblemDetailsService` so the same correlation customizer applies to exception and typed endpoint errors.
- **Always check `httpContext.Response.HasStarted` before writing the response body.** Writing to an already-started response throws a second exception and masks the original.
- Services and handlers never catch `OperationCanceledException`: cancellation and request timeouts propagate to this handler, which maps them. An empty result for a cancelled read hides timeouts and can be cached as a real answer.

## Verification Checklist

- [ ] Registered via `AddExceptionHandler<DefaultExceptionHandler>()` in `RegisterApiServices.cs`
- [ ] `UseExceptionHandler()` called in pipeline before routing
- [ ] `AddProblemDetails(...)` registered with separate `requestId`, W3C `traceId`, and `spanId`
- [ ] Typed errors and exception errors both exercise the correlation contract
- [ ] Exception text gated by environment (stack trace in Development only, fixed generic 5xx detail elsewhere), **proved by both arms of `tests/Test.Endpoints/Middleware/DefaultExceptionHandlerTests.cs`** - generate it from [test-templates-endpoint.md](test-templates-endpoint.md) section Exception Handler Tests
- [ ] All mapped exceptions return correct HTTP status codes
- [ ] Logging uses structured placeholders, not string interpolation
- [ ] No business logic errors handled here - those use `Result<T>` pattern
