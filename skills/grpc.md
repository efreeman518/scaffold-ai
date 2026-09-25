# gRPC

Base types (error interceptors, registration helpers) come from the `EF.Grpc` package - see [package-dependencies.md](package-dependencies.md) and the [EF.Packages repo](https://github.com/efreeman518/EF.Packages) for full API details.

## Prerequisites

- [package-dependencies.md](package-dependencies.md) - `EF.Grpc` package types
- [solution-structure.md](solution-structure.md) - project layout
- [bootstrapper.md](bootstrapper.md) - centralized DI registration
- [api.md](api.md) - API endpoint patterns (gRPC complements REST APIs)

## Overview

gRPC support uses `EF.Grpc` which provides **error interceptors** for both client and service sides. These interceptors standardize error handling across gRPC calls - catching exceptions, mapping to gRPC status codes, and surfacing structured error information.

> **When to use gRPC vs REST:** Use gRPC for internal service-to-service communication where performance, streaming, and strong typing matter. Use REST (Minimal APIs) for external/public APIs, browser clients, and third-party integrations.

---

## Package Types

### Client Error Interceptor

Intercepts gRPC client calls and translates `RpcException` into structured error responses:

```csharp
// Provided by package - catches RpcException on client calls
// and logs structured error details
public class ClientErrorInterceptor : Interceptor
{
    // Wraps unary, client streaming, server streaming, and duplex calls
    // Catches RpcException and logs StatusCode, Detail, and trailers
}
```

### Service Error Interceptor

Intercepts incoming gRPC service calls and translates unhandled exceptions into appropriate gRPC status codes:

```csharp
// Provided by package - catches exceptions in service methods
// and maps to gRPC StatusCode with structured details
public class ServiceErrorInterceptor : Interceptor
{
    // Maps exceptions:
    // - ValidationException -> StatusCode.InvalidArgument
    // - NotFoundException -> StatusCode.NotFound
    // - UnauthorizedAccessException -> StatusCode.PermissionDenied
    // - OperationCanceledException -> StatusCode.Cancelled
    // - Other -> StatusCode.Internal
}
```

### Error Interceptor Settings

```csharp
public class ErrorInterceptorSettings
{
    public bool IncludeExceptionDetails { get; set; } = false;  // true in Development only
}
```

### Service Collection Extensions

```csharp
// Provided by package for easy DI registration
public static class IServiceCollectionExtensions
{
    public static IServiceCollection AddGrpcClientInterceptors(this IServiceCollection services);
    public static IServiceCollection AddGrpcServiceInterceptors(this IServiceCollection services);
}
```

---

## gRPC Service Setup

### Proto File

Define service contracts in `.proto` files:

```protobuf
syntax = "proto3";

option csharp_namespace = "{Project}.Grpc";

package {project};

service {Entity}Service {
  rpc Get{Entity} (Get{Entity}Request) returns ({Entity}Response);
  rpc Search{Entities} (Search{Entities}Request) returns (Search{Entities}Response);
  rpc Create{Entity} (Create{Entity}Request) returns ({Entity}Response);
  rpc Update{Entity} (Update{Entity}Request) returns ({Entity}Response);
  rpc Delete{Entity} (Delete{Entity}Request) returns (DeleteResponse);
}

message Get{Entity}Request {
  string id = 1;
}

message {Entity}Response {
  string id = 1;
  string name = 2;
  string description = 3;
  google.protobuf.Timestamp created_date = 4;
}

// ... additional messages
```

### Service Implementation

```csharp
namespace {Project}.Api.Grpc;

public class {Entity}GrpcService(
    I{Entity}Service entityService,
    ILogger<{Entity}GrpcService> logger) : {Entity}Service.{Entity}ServiceBase
{
    public override async Task<{Entity}Response> Get{Entity}(
        Get{Entity}Request request, ServerCallContext context)
    {
        var result = await entityService.GetAsync(Guid.Parse(request.Id), context.CancellationToken);

        return result.Match(
            entity => new {Entity}Response
            {
                Id = entity.Id.ToString(),
                Name = entity.Name,
                Description = entity.Description
            },
            errors => throw new RpcException(new Status(StatusCode.NotFound,
                string.Join("; ", errors))),
            () => throw new RpcException(new Status(StatusCode.NotFound, "Entity not found")));
    }
}
```

---

## DI Registration

### Service Side (API hosting gRPC)

```csharp
// In Program.cs or Bootstrapper
builder.Services.AddGrpc(options =>
{
    options.Interceptors.Add<ServiceErrorInterceptor>();
    options.EnableDetailedErrors = builder.Environment.IsDevelopment();
});

builder.Services.Configure<ErrorInterceptorSettings>(options =>
{
    options.IncludeExceptionDetails = builder.Environment.IsDevelopment();
});

// Map gRPC services
app.MapGrpcService<{Entity}GrpcService>();
```

### Client Side (Consuming gRPC service)

```csharp
// Register typed gRPC client with error interceptor
builder.Services.AddGrpcClient<{Entity}Service.{Entity}ServiceClient>(options =>
{
    options.Address = new Uri(config["GrpcServices:{Entity}ServiceUrl"]!);
})
.AddInterceptor<ClientErrorInterceptor>();
```

### Load Balancing and Deadlines

HTTP/2 multiplexes every call over one long-lived connection, so a layer-4 balancer or direct replica address pins a client to one server. Route through a layer-7 proxy that balances per call (Container Apps ingress, YARP), or configure client-side balancing with a `dns:///` address and a round-robin `ServiceConfig`. Give every call a deadline and propagate it from the incoming call with `EnableCallContextPropagation()`, so a cancelled caller cancels its downstream work. Server streams hold a connection and memory per client; count them in the workload envelope ([../support/scalability-and-hosting.md](../support/scalability-and-hosting.md) section Workload Envelope Before Architecture).

---

## Configuration

### appsettings.json

```json
{
  "GrpcServices": {
    "{Entity}ServiceUrl": ""
  },
  "ErrorInterceptorSettings": {
    "IncludeExceptionDetails": false
  }
}
```

### appsettings.Development.json

```json
{
  "GrpcServices": {
    "{Entity}ServiceUrl": "https://localhost:5201"
  },
  "ErrorInterceptorSettings": {
    "IncludeExceptionDetails": true
  }
}
```

---

## Aspire Integration

```csharp
// AppHost/Program.cs
var grpcService = builder.AddProject<Projects.{Project}_GrpcService>("{project}-grpc")
    .WithReference(sqlDb);

var api = builder.AddProject<Projects.{Project}_Api>("{project}-api")
    .WithReference(grpcService);  // Service discovery provides the URL
```

---

## Verification

After generating gRPC code, confirm:

- [ ] `.proto` files define service contracts with appropriate message types
- [ ] `ServiceErrorInterceptor` registered on server-side gRPC pipeline
- [ ] `ClientErrorInterceptor` registered on client-side gRPC channel
- [ ] `ErrorInterceptorSettings.IncludeExceptionDetails` is `false` in Production
- [ ] Service implementations delegate to application layer services (not direct DB access)
- [ ] Typed gRPC clients registered via `AddGrpcClient<T>` with service discovery URL
- [ ] Cross-references: Aspire service discovery provides gRPC URLs; [api.md](api.md) for REST counterpart
