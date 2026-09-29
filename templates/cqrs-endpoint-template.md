# CQRS Endpoint Template

Use for `applicationStyle: cqrs` or `switch`. Endpoints keep the same HTTP routes and DTO contracts as service endpoints, but inject the specific command/query handler instead of `I{Entity}Service`.

Map relative routes only. The API host owns the outer route group and versioning decision, for example `/api/v1/{entity}` for public domain endpoints. Operational, health, gateway, Functions host-health, and package-owned admin endpoints stay outside the entity/CQRS endpoint template unless they are explicit business API contracts.

Import request types from the feature namespace, for example `using {Project}.Application.Cqrs.Features.{EntityPlural};`.

Keep `[FromServices]` on every injected handler parameter; see [api.md](../skills/api.md) section Endpoint Contract for the route-discovery body-inference failure this prevents.

```csharp
group.MapPost("/", async (
    HttpContext httpContext,
    [FromServices] IRequestHandler<Create{Entity}Command, Result<DefaultResponse<{Entity}Dto>>> handler,
    [FromBody] DefaultRequest<{Entity}Dto> request,
    CancellationToken ct) =>
{
    var result = await handler.HandleAsync(new Create{Entity}Command(request), ct);
    return result.Match<IResult>(
        response => TypedResults.Created($"{httpContext.Request.Path}/{response.Item?.Id}", response),
        errors => TypedResults.Problem(ProblemDetailsHelper.FromErrors(errors)));
});

group.MapPut("/{id:guid}", async (
    [FromServices] IRequestHandler<Update{Entity}Command, Result<DefaultResponse<{Entity}Dto>>> handler,
    Guid id,
    IfMatch ifMatch,
    [FromBody] DefaultRequest<{Entity}Dto> request,
    CancellationToken ct) =>
{
    var result = await handler.HandleAsync(new Update{Entity}Command(request, ifMatch.ExpectedVersion), ct);
    return result.Match(
        response => response.Item is null ? Results.NotFound(id) : TypedResults.Ok(response),
        errors => TypedResults.Problem(ProblemDetailsHelper.FromErrors(errors)));
})
.RequireIfMatch();
```

`IfMatch`, `RequireIfMatch()` and the group-level `WithETag()` are EF.AspNetCore (`EF.AspNetCore.Concurrency`), wired exactly as in [endpoint-template.md](endpoint-template.md). Correlation is added centrally by `AddEfProblemDetails()`; see [exception-handler-template.md](exception-handler-template.md). Do not pass `HttpContext.TraceIdentifier` as `traceId`.

For `applicationStyle: switch`, register only one endpoint set at runtime:

```csharp
var style = ApplicationStyleResolver.Resolve(config[ApplicationStyleResolver.ConfigKey]);
if (style == ApplicationStyle.Cqrs)
    api.Map{Entity}CqrsEndpoints();
else
    api.Map{Entity}Endpoints();
```

Keep CQRS endpoint files in `Host/{Host}.Api/Endpoints/Cqrs/{Entity}CqrsEndpoints.cs`; only application request/handler code moves into `Application.Cqrs/Features/{Entity}`.
