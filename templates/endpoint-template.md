# Endpoint Template

> **When to read:** Phase 5b, when generating the Minimal API endpoint group for an entity - CRUD + search routes mapped through the entity's service.
> **Skip if:** No API host in scope; entity is internal-only (no public surface); endpoint group already exists.

| | |
|---|---|
| **File** | `Host/{Host}.Api/Endpoints/{Entity}Endpoints.cs` |
| **Depends on** | [service-template](service-template.md), [data-mapping-template](data-mapping-template.md) |
| **Referenced by** | [api.md](../skills/api.md), [test-templates-endpoint.md](test-templates-endpoint.md), [test-templates.md](test-templates.md) |

## File: Host/{Host}.Api/Endpoints/{Entity}Endpoints.cs

Endpoint templates map relative routes only. The API host owns the outer route group and versioning decision, for example `/api/v1/{entity}` for public domain endpoints. Do not bake `/api`, `/v1`, tenant segments, gateway prefixes, health routes, or admin routes into entity endpoint classes.

> **Aggregate-internal children get no standalone write endpoint (GR-15).** This template's `Create` / `Update` / `Delete` routes apply to **aggregate roots** only. If the entity is an internal child of a root (a 1:N owned entity or M:N junction - e.g. a comment or checklist item on a task), do **not** generate a `{Child}Endpoints` write surface. Instead expose the child writes as **nested sub-resource routes on the root's** endpoint class, calling the root's domain methods through a loaded aggregate:
>
> ```csharp
> // In {Root}Endpoints - children are mutated only through the root (GR-15):
> g.MapPost("/{id:guid}/{children}", Add{Child});                       // -> root.Add{Child}(...)
> g.MapPut("/{id:guid}/{children}/{childId:guid}", Update{Child});       // -> child.Update(...)
> g.MapDelete("/{id:guid}/{children}/{childId:guid}", Remove{Child});    // -> root.Remove{Child}(...)
> g.MapPost("/{id:guid}/tags/{tagId:guid}", AssociateTag);              // -> root.AssociateTag(tagId)  (M:N)
> g.MapDelete("/{id:guid}/tags/{tagId:guid}", RemoveTag);               // -> root.RemoveTag(tagId)
> ```
>
> Each nested handler loads the root via its transactional repository, calls the matching `Add*`/`Update`/`Remove*` method, and saves the aggregate in one transaction (a missing root returns `NotFoundError`, 404). A child read endpoint (`GetById`/`Search`) is still allowed because reads may cross aggregate boundaries. See [../skills/domain-model.md](../skills/domain-model.md) section Aggregate Roots vs Internal Children.

```csharp
using EF.AspNetCore;
using EF.AspNetCore.Concurrency;
using Microsoft.AspNetCore.Mvc;

namespace {Host}.Api.Endpoints;

public static class {Entity}Endpoints
{
    public static IEndpointRouteBuilder Map{Entity}Endpoints(this IEndpointRouteBuilder group)
    {
        var g = group.MapGroup("/{entities}").WithTags("{Entities}")
            .WithETag()   // strong ETag from DefaultResponse.ETagVersion, 304 on If-None-Match
            .ProducesProblem(StatusCodes.Status403Forbidden);   // tenant boundary: ForbiddenError

        g.MapPost("/search", Search)
            .Produces<PagedResponse<{Entity}Dto>>(StatusCodes.Status200OK)
            .WithSummary("Search {Entities} with paging, filters, and sorts");

        g.MapGet("/lookup", Lookup)
            .Produces<StaticList<StaticItem<Guid, Guid?>>>(StatusCodes.Status200OK)
            .WithSummary("Lookup list for autocomplete");

        g.MapGet("/{id:guid}", GetById)
            .Produces<DefaultResponse<{Entity}Dto>>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status404NotFound)
            .WithSummary("Get a single {Entity}");

        g.MapPost("/", Create)
            // Idempotent create only: Idempotency-Key -> stored UUIDv7 body Id (data-persistence.md, Idempotent Create)
            .WithIdempotencyKey<{Entity}Dto>(_ => "{entity}.create")
            .Produces<DefaultResponse<{Entity}Dto>>(StatusCodes.Status201Created)
            .ProducesValidationProblem()
            .ProducesProblem(StatusCodes.Status409Conflict)
            .WithSummary("Create a new {Entity}");

        // RequireIfMatch: 428 without If-Match, 400 malformed, 412 + current ETag on PreconditionFailedException; `*` binds ExpectedVersion null.
        g.MapPut("/{id:guid}", Update)
            .RequireIfMatch()
            .Produces<DefaultResponse<{Entity}Dto>>()
            .ProducesValidationProblem()
            .ProducesProblem(StatusCodes.Status404NotFound)
            .ProducesProblem(StatusCodes.Status422UnprocessableEntity)   // only when a domain rule can fail (RuleError)
            .WithSummary("Update an existing {Entity}");

        g.MapDelete("/{id:guid}", Delete)
            .RequireIfMatch()
            .Produces(StatusCodes.Status204NoContent)
            .ProducesValidationProblem()
            .WithSummary("Delete a {Entity}");

        return group;
    }

    private static async Task<IResult> Search(
        [FromServices] I{Entity}Service service,
        [FromBody] SearchRequest<{Entity}SearchFilter> request,
        CancellationToken ct)
    {
        var items = await service.SearchAsync(request, ct);
        return TypedResults.Ok(items);
    }

    private static async Task<IResult> Lookup(
        [FromServices] I{Entity}Service service,
        [FromQuery] Guid? tenantId,
        [FromQuery] string? search,
        CancellationToken ct)
    {
        var items = await service.LookupAsync(tenantId, search, ct);
        return TypedResults.Ok(items);
    }

    private static async Task<IResult> GetById(
        [FromServices] I{Entity}Service service, Guid id,
        CancellationToken ct)
    {
        var result = await service.GetAsync(id, ct);
        return result.ToHttp(response => TypedResults.Ok(response));
    }

    private static async Task<IResult> Create(
        HttpContext httpContext,
        [FromServices] I{Entity}Service service,
        [FromBody] DefaultRequest<{Entity}Dto> request,
        CancellationToken ct)
    {
        var result = await service.CreateAsync(request, ct);
        return result.ToHttp(response => TypedResults.Created($"{httpContext.Request.Path}/{response.Item?.Id}", response));
    }

    private static async Task<IResult> Update(
        [FromServices] I{Entity}Service service,
        Guid id,
        IfMatch ifMatch,
        [FromBody] DefaultRequest<{Entity}Dto> request,
        CancellationToken ct)
    {
        if (request.Item.Id != null && request.Item.Id != id)
            return TypedResults.Problem(ProblemDetailsHelper.Create(
                StatusCodes.Status400BadRequest, $"{ErrorConstants.ERROR_URL_BODY_ID_MISMATCH}: {id} <> {request.Item.Id}"));

        var result = await service.UpdateAsync(request, ifMatch.ExpectedVersion, ct);
        return result.ToHttp(response => TypedResults.Ok(response));   // missing row: the service's NotFoundError
    }

    private static async Task<IResult> Delete(
        [FromServices] I{Entity}Service service, Guid id, IfMatch ifMatch,
        CancellationToken ct)
    {
        var result = await service.DeleteAsync(id, ifMatch.ExpectedVersion, ct);
        return result.ToHttp(_ => TypedResults.NoContent());
    }
}
```

`IfMatch` and `RequireIfMatch()` come from EF.AspNetCore (`EF.AspNetCore.Concurrency`); do not generate `If-Match` parsing, an ETag filter, or an OpenAPI transformer - the host calls `AddConcurrencyOpenApiContract()` once. `ifMatch.ExpectedVersion` throws when no header was bound, so a route that binds `IfMatch` without `RequireIfMatch()` fails loudly instead of skipping the check. `ToHttp` answers any `Error` with its category's problem body ([../skills/api.md](../skills/api.md) section Endpoint Contract); unexpected exceptions are the exception handler's job ([exception-handler-template.md](exception-handler-template.md)).

## Custom Action Routes (Optional)

Include only when `.scaffold/domain-specification.yaml` declares a `customActions` entry on `{Entity}` (e.g. `Reschedule`, `Approve`, `Cancel`). Map the action route inside the same `Map{Entity}Endpoints` extension so each entity's surface stays co-located. See [../skills/api.md](../skills/api.md) section Custom Action Endpoints for routing conventions and the request/response contract.

```csharp
// Inside Map{Entity}Endpoints - add alongside the CRUD routes above:
g.MapPost("/{id:guid}/{action-name}", {ActionName})
    .Produces<DefaultResponse<{Entity}Dto>>(StatusCodes.Status200OK)
    .ProducesValidationProblem()
    .ProducesProblem(StatusCodes.Status404NotFound)
    .ProducesProblem(StatusCodes.Status422UnprocessableEntity)
    .WithSummary("{ActionName} a {Entity}");

private static async Task<IResult> {ActionName}(
    HttpContext httpContext,
    [FromServices] I{Entity}Service service,
    Guid id,
    [FromBody] {ActionName}Request request,
    CancellationToken ct)
{
    var result = await service.{ActionName}Async(id, request, ct);
    return result.ToHttp(response => TypedResults.Ok(response));
}
```

The handler shape mirrors `GetById` / `Update` deliberately - same `ToHttp` mapping, same `CancellationToken` placement. An action that changes a versioned aggregate adds `.RequireIfMatch()` and passes `ifMatch.ExpectedVersion` like `Update`. The service method invokes the entity's domain method (e.g. `entity.{ActionName}(...)`) and emits `afterAction({ActionName})` per the event model.

## Registration in Pipeline

In `WebApplicationBuilderExtensions.cs`, add to `SetupApiEndpoints`:

```csharp
// Simple pattern (default)
app.MapGroup("/api").RequireAuthorization().Map{Entity}Endpoints();

// Versioned pattern (api.md section Pipeline + Versioned Groups)
api.Map{Entity}Endpoints();
```

For kebab-case route segments, use `{entity-route}` in route definitions.

---

**TaskFlow proof (local):** `../scaffold-proof/src/Host/TaskFlow.Api/Endpoints/TaskItemEndpoints.cs`
**TaskFlow proof (remote fallback):** <https://github.com/efreeman518/scaffold-proof/blob/main/src/Host/TaskFlow.Api/Endpoints/TaskItemEndpoints.cs>

## CQRS Endpoint Variant

When `applicationStyle` is `cqrs` or `switch`, keep route and DTO contracts aligned with the service endpoint, but inject `IRequestHandler<TRequest,TResponse>` for the specific command/query. Do not inject `I{Entity}Service` from CQRS endpoints and do not add a central dispatch step; this keeps route -> request -> handler flow visible at the endpoint.
