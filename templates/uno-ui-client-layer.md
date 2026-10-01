# UI Client Layer Template (Models + Services)

| | |
|---|---|
| **Files** | `src/UI/{Project}.Uno.Core/Client/{Project}ApiClient.cs`, `Business/Models/{Entity}Model.cs`, `Business/Models/IEntityBase.cs`, `Business/Messages/EntityMessage.cs`, `Business/Services/{Feature}/I{Entity}ApiService.cs`, `Business/Services/{Feature}/{Entity}ApiService.cs` |
| **Depends on** | [data-mapping-template](data-mapping-template.md) (API DTO structure) |
| **Referenced by** | [uno-mvux-model-template](uno-mvux-model-template.md), [ui-uno.md](../skills/ui-uno.md) |

## Models

Client models, DTO wrappers, API clients, business services, and platform-agnostic UI messages live in `src/UI/{Project}.Uno.Core`. MVUX presentation models live in `src/UI/{Project}.Uno.Presentation`. The `src/UI/{Project}.Uno` app head references the presentation library and owns only app startup, routes, XAML views, styles, converters, strings, and platform assets.

### Client-Side Record Model

```csharp
using {Project}.Uno.Core.Client.Models;
using {Entity}Data = {Project}.Uno.Core.Client.Models.{Entity}Data;

namespace {Project}.Uno.Core.Business.Models;

/// <summary>
/// Client-side immutable record for {Entity}.
/// Wraps the Kiota-generated wire DTO ({Entity}Data).
/// </summary>
public partial record {Entity}Model : IEntityBase
{
    /// <summary>
    /// Create from Kiota wire DTO.
    /// </summary>
    internal {Entity}Model({Entity}Data data)
    {
        Id = data.Id;
        Name = data.Name;
        Version = data.Version ?? 0;   // the ETag source for If-Match on PUT/DELETE
        // Map all properties from data -> record
    }

    // Default constructor for create scenarios (Id null until the API assigns it)
    public {Entity}Model() { }

    public Guid? Id { get; init; }
    public string? Name { get; init; }
    public bool IsFavorite { get; init; }
    public long Version { get; init; }
    // ... add all entity properties

    // Computed properties (display helpers)
    // public string DisplayText => $"{Name} - {SomeOtherProp}";

    /// <summary>
    /// Convert back to Kiota wire DTO for POST/PUT requests.
    /// </summary>
    internal {Entity}Data ToData() => new()
    {
        Id = Id,
        Name = Name,
        // Map all properties from record -> data
    };
}
```

### Model Rules

- Use `partial record` with `init` properties - immutable by default
- Name it `{Entity}Model`, the type the MVUX models bind ([uno-mvux-model-template.md](uno-mvux-model-template.md))
- Provide an `internal` constructor that accepts the Kiota wire DTO (`{Entity}Data`)
- Provide a `ToData()` method to convert back to the wire DTO
- Keep computed/display properties as expression-bodied getters
- Implement `IEntityBase` so messaging key selectors work
- Default constructor (parameterless) is needed for create/form scenarios
- Use `using {Entity}Data = ...` alias to avoid naming collisions with the client record

## Services

### Service Interface

The MVUX models ([uno-mvux-model-template.md](uno-mvux-model-template.md)) and the presentation tests call exactly this surface.

```csharp
namespace {Project}.Uno.Core.Business.Services.{Feature};

/// <summary>
/// Client-side service for {Entity} operations via the Gateway API.
/// </summary>
public interface I{Entity}ApiService
{
    ValueTask<IImmutableList<{Entity}Model>> SearchAsync(CancellationToken ct = default);
    ValueTask<{Entity}Model?> GetAsync(Guid id, CancellationToken ct = default);
    ValueTask<{Entity}Model> CreateAsync({Entity}Model model, CancellationToken ct = default);

    /// <summary>Sends If-Match from <c>model.Version</c>; returns the saved record with its new Version.</summary>
    ValueTask<{Entity}Model> UpdateAsync({Entity}Model model, CancellationToken ct = default);

    /// <summary>Sends If-Match from <paramref name="version"/>.</summary>
    ValueTask DeleteAsync(Guid id, long version, CancellationToken ct = default);

    ValueTask FavoriteAsync({Entity}Model model, CancellationToken ct = default);

    // Aggregate children go through the root (GR-15); a removal sends the root's current Version as If-Match:
    // ValueTask<{ChildEntity}Model> Add{ChildEntity}Async(Guid {entity}Id, string body, CancellationToken ct = default);
    // ValueTask Remove{ChildEntity}Async(Guid {entity}Id, Guid {childEntity}Id, long rootVersion, CancellationToken ct = default);
}
```

### Service Implementation

```csharp
using {Project}.Uno.Core.Business.Models;
using {Project}.Uno.Core.Client;
using {Project}.Uno.Core.Business.Messages;

namespace {Project}.Uno.Core.Business.Services.{Feature};

/// <summary>
/// Calls the Gateway API via Kiota-generated client.
/// Maps wire DTOs to client-side records.
/// Sends EntityMessage on mutations for MVUX auto-refresh.
/// </summary>
public class {Entity}ApiService(
    {Project}ApiClient api,
    IMessenger messenger) : I{Entity}ApiService
{
    public async ValueTask<IImmutableList<{Entity}Model>> SearchAsync(CancellationToken ct = default)
    {
        var data = await api.Api.{Entity}.GetAsync(cancellationToken: ct);
        return data?.Select(d => new {Entity}Model(d)).ToImmutableList()
            ?? ImmutableList<{Entity}Model>.Empty;
    }

    public async ValueTask<{Entity}Model?> GetAsync(Guid id, CancellationToken ct = default)
    {
        var response = await api.Api.{Entity}[id].GetAsync(cancellationToken: ct);
        return response?.Item is { } item ? new {Entity}Model(item) : null;
    }

    public async ValueTask<{Entity}Model> CreateAsync({Entity}Model model, CancellationToken ct = default)
    {
        var response = await api.Api.{Entity}.PostAsync(model.ToData(), cancellationToken: ct);
        var created = new {Entity}Model(response!.Item!);   // server-assigned Id and Version
        messenger.Send(new EntityMessage<{Entity}Model>(EntityChange.Created, created));
        return created;
    }

    public async ValueTask<{Entity}Model> UpdateAsync({Entity}Model model, CancellationToken ct = default)
    {
        var response = await api.Api.{Entity}[model.Id!.Value].PutAsync(model.ToData(),
            rc => rc.Headers.Add("If-Match", EntityTags.ForVersion(model.Version).ToString()), ct);
        var updated = new {Entity}Model(response!.Item!);   // the saved Version, so the next PUT is not a 412
        messenger.Send(new EntityMessage<{Entity}Model>(EntityChange.Updated, updated));
        return updated;
    }

    public async ValueTask DeleteAsync(Guid id, long version, CancellationToken ct = default)
    {
        await api.Api.{Entity}[id].DeleteAsync(
            rc => rc.Headers.Add("If-Match", EntityTags.ForVersion(version).ToString()), ct);
        messenger.Send(new EntityMessage<{Entity}Model>(EntityChange.Deleted, new {Entity}Model { Id = id }));
    }

    public async ValueTask FavoriteAsync({Entity}Model model, CancellationToken ct = default)
    {
        var updated = model with { IsFavorite = !model.IsFavorite };
        await api.Api.{Entity}.Favorited.PostAsync(q =>
        {
            q.QueryParameters.{Entity}Id = updated.Id;
        }, cancellationToken: ct);
        messenger.Send(new EntityMessage<{Entity}Model>(EntityChange.Updated, updated));
    }
}
```

### Service Rules

- Use **primary constructor** injection (C# 12+)
- All methods return `ValueTask` or `ValueTask<T>`
- Always accept `CancellationToken ct` as the last parameter
- Return `IImmutableList<T>` (never `List<T>` or `IEnumerable<T>`)
- Map Kiota wire DTOs -> client records via constructor: `new {Entity}Model(data)`
- Map client records -> wire DTOs via `model.ToData()` for POST/PUT
- Send `EntityMessage<T>` via `IMessenger` after every mutation (create, update, delete)
- PUT and DELETE send `If-Match` from the record's `Version` (`EntityTags.ForVersion`, EF.UI.Client); the API answers 428 without it and 412 on a stale one. The client record carries `Version` from the DTO
- Register as singleton in `App.xaml.host.cs` -> `ConfigureServices`

### Client Contract Rules

- Prefer shared contract types where available: `DefaultRequest<T>`, `DefaultResponse<T>`, `SearchRequest<TFilter>`, and `PagedResponse<T>`.
- Do not hand-roll client-side envelope DTOs when the shared application/common contract package is already referenced.
- POST/PUT bodies use `DefaultRequest<T>` with an `Item` property.
- Single-item GET/create/update responses unwrap `DefaultResponse<T>.Item`.
- Search responses use `PagedResponse<T>` and its `Data` collection; search requests are not wrapped in `DefaultRequest<T>`.
- Browser-WASM clients use a source-generated `JsonSerializerContext`; reflection-based JSON is not a valid published-Release dependency.

```csharp
using System.Text.Json;
using System.Text.Json.Serialization;

namespace {Project}.Uno.Core.Client;

[JsonSourceGenerationOptions(JsonSerializerDefaults.Web)]
[JsonSerializable(typeof(DefaultRequest<{Entity}Dto>))]
[JsonSerializable(typeof(DefaultResponse<{Entity}Dto>))]
[JsonSerializable(typeof(PagedResponse<{Entity}Dto>))]
[JsonSerializable(typeof(SearchRequest<{Entity}SearchFilter>))]
[JsonSerializable(typeof(List<{Entity}Dto>))]
internal partial class {Project}ApiJsonContext : JsonSerializerContext;
```

Use the generated `JsonTypeInfo<T>` overload at every `HttpClientJsonExtensions` call, for example:

```csharp
await http.PostAsJsonAsync(uri, request, {Project}ApiJsonContext.Default.DefaultRequest{Entity}Dto, ct);
var response = await content.ReadFromJsonAsync(
    {Project}ApiJsonContext.Default.DefaultResponse{Entity}Dto,
    ct);
```

The generated property names depend on the closed generic type names. Compile once, then use the emitted property exactly. Inventory internal envelopes read inside client methods as well as public parameters and returns.

## Client Plumbing (EF.UI.Client)

Busy tracking, notifications, problem+json translation, the UI dispatcher contract and the runtime base URL are EF.UI.Client ([../support/ef-packages-optional.md](../support/ef-packages-optional.md) section UI Client); generate no busy tracker, notification service, delegating handler, problem-details payload or runtime-config loader.

```csharp
// App.xaml.host.cs -> UseHttp: busy outermost, problem details innermost, both before any resilience handler
services.AddHttpClient<{Project}ApiClient>(c => c.BaseAddress = new Uri(gatewayUrl))
    .AddBusyTracking()
    .AddProblemDetailsNotifications();

// ConfigureServices: the platform dispatcher first; AddUiClient registers IBusyTracker and INotificationService
services.AddSingleton<IUiDispatcher>(new DispatcherQueueUiDispatcher(dispatcherQueue))
        .AddUiClient();
```

`DispatcherQueueUiDispatcher` is the app's one adapter (`HasThreadAccess`, `Post` over `DispatcherQueue.TryEnqueue`); a missing dispatcher fails at resolution. Tests register `IUiDispatcher.Inline`. The WASM head loads its gateway URL with `RuntimeClientConfiguration.LoadBaseUrlAsync(http)` from `/app-config.json` before building the host.

## Shared Interfaces

### IEntityBase

```csharp
namespace {Project}.Uno.Core.Business.Models;

/// <summary>
/// Marker interface for entities with a Guid Id (null before the API assigns it).
/// Used by EntityMessage<T> and messenger-based refresh.
/// </summary>
public interface IEntityBase
{
    Guid? Id { get; }
}
```

### EntityMessage and EntityChange

```csharp
namespace {Project}.Uno.Core.Business.Messages;

public enum EntityChange { Created, Updated, Deleted }

/// <summary>
/// Broadcast via IMessenger when an entity is mutated.
/// MVUX models using .Observe() auto-refresh on receipt.
/// </summary>
public record EntityMessage<T>(EntityChange Change, T Entity);
```

## Client-Side Flow

The complete flow for a mutation (e.g., Create) through the client layer:

1. **Model** -- The caller builds an `{Entity}Model` record (immutable, `init` properties)
2. **Service** -- `{Entity}ApiService.CreateAsync()` converts the record to a wire DTO via `model.ToData()`
3. **API call** -- The Kiota-generated client sends the DTO to the Gateway API
4. **Messaging** -- On success, the service sends `EntityMessage<{Entity}Model>(EntityChange.Created, created)` via `IMessenger`
5. **Refresh** -- MVUX models subscribed via `.Observe()` receive the message and auto-refresh their state

For reads, the flow is reversed at the mapping step:

1. **API call** -- Kiota client returns `{Entity}Data` (wire DTO)
2. **Model** -- Service wraps data via `new {Entity}Model(data)` constructor
3. **Return** -- `IImmutableList<{Entity}Model>` returned to the presentation layer
