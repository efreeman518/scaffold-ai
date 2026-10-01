# Exception Handler Template

| | |
|---|---|
| **File** | `Host/{Host}.Api/RegisterApiServices.cs` (exception-handling registration and the app's `MapExceptions`) |
| **Depends on** | [api.md](../skills/api.md) |
| **Referenced by** | [api.md](../skills/api.md), [api-host-wiring.md](../patterns/api-host-wiring.md) |

## Purpose

The global exception handler is the EF.AspNetCore `ProblemDetailsExceptionHandler`, registered by `AddEfProblemDetails()`; the app generates no `IExceptionHandler`. Its status comes from the EF.Common `ExceptionClassifier`, the one exception taxonomy the HTTP handler and the gRPC `ServiceErrorInterceptor` share. The app adds only its own mappings. This is the **safety net** - not a control-flow mechanism. All expected business outcomes flow through `Result<T>`/`DomainResult<T>`.

## Template

```csharp
// File: Host/{Host}.Api/RegisterApiServices.cs (excerpt)
using EF.AspNetCore.ExceptionHandling;
using EF.Common.Exceptions;
using EF.Data.Contracts;
using Microsoft.EntityFrameworkCore;

private static void AddExceptionHandling(IServiceCollection services)
{
    services.AddEfProblemDetails();
    services.AddExceptionClassifier(MapExceptions);
}

/// <summary>
/// The app's additions to the shared taxonomy. Map only exception types the app owns for caller input;
/// framework ArgumentException, FormatException and InvalidOperationException stay unmapped (500).
/// </summary>
internal static void MapExceptions(ExceptionClassifierOptions options) => options
    // A policy-free save's lost update: 412 without an ETag (the exception middleware clears it).
    .Map<DbUpdateConcurrencyException>(ExceptionCategory.PreconditionFailed)
    // [AI] .Map<EF.AI.EFAIDisabledException>(ExceptionCategory.Unavailable)   // 503
    // Caller input the app rejects: its own request exception and the cursor codec's InvalidCursorException.
    .Map<InvalidRequestException>(ExceptionCategory.Validation)
    .Map<InvalidCursorException>(ExceptionCategory.Validation);
```

`InvalidRequestException` is the app's own caller-input exception (for example a page size outside the allowed range), declared in `Application.Contracts` and deriving from `Exception`. `MapExceptions` is `internal` so the endpoint tests build the same registration.

Add to pipeline in `WebApplicationBuilderExtensions.cs` (after `UseProxyForwarding` and `UseCorrelationId`, before routing):

```csharp
app.UseExceptionHandler();
```

## Exception-to-Status Mapping

| Exception Type | HTTP Status | Source |
|---|---|---|
| `OperationCanceledException` while `HttpContext.RequestAborted` is cancelled | 499 (no body) | package |
| Any other `OperationCanceledException`, `TimeoutException` | 504 Gateway Timeout | package |
| `ValidationException` (EF.Common), `InvalidRequestException`, `InvalidCursorException` | 400 Bad Request | package / app map |
| `BadHttpRequestException` | its own status (400, 408, 413, 431) | package |
| `UnauthorizedAccessException` | 403 Forbidden | package |
| `NotFoundException`, `KeyNotFoundException` | 404 Not Found | package |
| `ConflictException` | 409 Conflict | package |
| `PreconditionFailedException` | 412 Precondition Failed | package |
| `DbUpdateConcurrencyException` | 412 Precondition Failed (no ETag) | app map |
| `PreconditionRequiredException` | 428 Precondition Required | package |
| `EFAIDisabledException` | 503 Service Unavailable | app map, AI in scope |
| All others, including `ArgumentException`, `FormatException`, `InvalidOperationException` | 500 Internal Server Error | package |

## Rules

- **Safety net only** - business validation errors must use `Result<T>` / `DomainResult<T>`, never exceptions.
- **Map only the app's own client-input exceptions to 400.** Framework exceptions (table above) are server bugs: a 4xx would hide them and echo their text. Input the app rejects by exception uses its own type, mapped here.
- Detail: full `exception.ToString()` in Development only (`ExceptionHandlingOptions.IncludeExceptionDetails`). Outside Development a 5xx carries no exception text; SQL, connection, and internal messages belong in the log.
- 499 only when `HttpContext.RequestAborted` is cancelled. Any other cancellation is a server-side timeout: 504.
- A 412 from the handler never carries an ETag: `ExceptionHandlerMiddleware` clears the ETag and cache headers before any handler runs. The stale-`If-Match` 412 with the current ETag comes from the `RequireIfMatch()` endpoint filter ([../skills/data-persistence.md](../skills/data-persistence.md) section Provider Branch and Concurrency Discipline).
- Every problem carries `instance`, `requestId` (the correlation id) and the W3C `traceId` / `spanId`; do not register a second `CustomizeProblemDetails` that rewrites them.
- The gRPC host passes the same `ExceptionClassifier` to `ServiceErrorInterceptor`, so one mapping change applies to both transports.
- Services and handlers never catch `OperationCanceledException`: cancellation and request timeouts propagate to the handler, which maps them. An empty result for a cancelled read hides timeouts and can be cached as a real answer.

## Verification Checklist

- [ ] `AddEfProblemDetails()` and `AddExceptionClassifier(MapExceptions)` registered in `RegisterApiServices.cs`; no app `IExceptionHandler` and no second `AddProblemDetails` customizer
- [ ] `UseExceptionHandler()` called in pipeline before routing
- [ ] Exception text gated by environment and every mapped status **proved by `tests/Test.Endpoints/Middleware/ExceptionMappingTests.cs`** - generate it from [test-templates-endpoint.md](test-templates-endpoint.md) section Exception Mapping Tests
- [ ] No business logic errors handled here - those use `Result<T>` pattern
