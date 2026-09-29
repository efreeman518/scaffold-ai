# gRPC

Base types (error interceptors, registration helpers) come from the `EF.Grpc` package - see [package-dependencies.md](package-dependencies.md) and the [EF.Packages repo](https://github.com/efreeman518/EF.Packages) for full API details.

## Prerequisites

- [package-dependencies.md](package-dependencies.md) - `EF.Grpc` package types
- [solution-structure.md](solution-structure.md) - project layout
- [bootstrapper.md](bootstrapper.md) - centralized DI registration
- [api.md](api.md) - API endpoint patterns (gRPC complements REST APIs)

## Overview

gRPC support uses `EF.Grpc`, which provides **error interceptors** for both client and service sides and the client registration. The server interceptor maps exceptions through the same `ExceptionClassifier` as the HTTP host, so one mapping serves both transports.

> **When to use gRPC vs REST:** Use gRPC for internal service-to-service communication where performance, streaming, and strong typing matter. Use REST (Minimal APIs) for external/public APIs, browser clients, and third-party integrations.

---

## Package Types

Types and signatures: [../support/ef-packages-optional.md](../support/ef-packages-optional.md) section gRPC (EF.Grpc). Generate no interceptor, status mapper or client-registration helper.

- **`ServiceErrorInterceptor`** (server): intercepts unary and all streaming calls, rethrows a service's own `RpcException` unchanged, and maps every other exception through the shared `ExceptionClassifier` - the same taxonomy and the same `MapExceptions` the HTTP exception handler uses - to a `StatusCode` (`GrpcStatusCodes.For(category)`: `Validation` -> `InvalidArgument`, `NotFound` -> `NotFound`, `PreconditionFailed` -> `FailedPrecondition`, `Forbidden` -> `PermissionDenied`, `Cancelled` -> `Cancelled`, `Timeout` -> `DeadlineExceeded`, `Internal` -> `Internal`). The status detail is the category name; exception text stays in the server log.
- **`ErrorInterceptorSettings`**: one member, `IncludeExceptionMessageInResponse` (default `false`); leave it off outside Development.
- **`ClientErrorInterceptor`** (client): logs the `RpcException` status and detail of a failed call.
- **`AddEFGrpcClient<TClient>(settings, bearerTokenProvider, serverCertificateValidation)`** with `GrpcClientSettings` (`Address`, `MaxConnectionsPerServer`, `HandlerLifetimeSeconds`, `ClientCertificatesBase64`): a `SocketsHttpHandler` primary handler that opens multiple HTTP/2 connections, a per-call bearer token through call credentials, and optional mTLS client certificates as base64 PKCS#12.

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
            errors => throw new RpcException(new Status(StatusCode.InvalidArgument,
                string.Join("; ", errors.Select(e => e.Error)))),
            () => throw new RpcException(new Status(StatusCode.NotFound, "Entity not found")));
    }
}
```

---

## DI Registration

### Service Side (API hosting gRPC)

```csharp
// RegisterApiServices: the host already calls AddExceptionClassifier(MapExceptions) for HTTP.
builder.Services.AddGrpc(options => options.Interceptors.Add<ServiceErrorInterceptor>());
builder.Services.Configure<ErrorInterceptorSettings>(builder.Configuration.GetSection("ErrorInterceptorSettings"));

// Map gRPC services
app.MapGrpcService<{Entity}GrpcService>().RequireAuthorization();
```

### Client Side (Consuming gRPC service)

```csharp
var settings = config.GetSection("GrpcServices:{Entity}").Get<GrpcClientSettings>()
    ?? throw new InvalidOperationException("GrpcServices:{Entity} is required.");
builder.Services.AddEFGrpcClient<{Entity}Service.{Entity}ServiceClient>(settings)
    .AddInterceptor<ClientErrorInterceptor>();
```

### Load Balancing and Deadlines

HTTP/2 multiplexes every call over one long-lived connection, so a layer-4 balancer or direct replica address pins a client to one server. Route through a layer-7 proxy that balances per call (Container Apps ingress, YARP), or configure client-side balancing with a `dns:///` address and a round-robin `ServiceConfig`. Give every call a deadline. A host that is itself serving a gRPC call propagates the incoming deadline and cancellation with `EnableCallContextPropagation()`; any other caller (a Blazor Server circuit, a REST endpoint, a worker) sets an explicit per-call deadline, because call-context propagation throws when there is no incoming gRPC call. Every gRPC call is an HTTP POST, so retry policy follows [resilience.md](resilience.md) section Internal-Call Guidance. Server streams hold a connection and memory per client; count them in the workload envelope ([../support/scalability-and-hosting.md](../support/scalability-and-hosting.md) section Workload Envelope Before Architecture).

---

## Configuration

### appsettings.json

```json
{
  "GrpcServices": {
    "{Entity}": { "Address": "", "MaxConnectionsPerServer": 200 }
  },
  "ErrorInterceptorSettings": {
    "IncludeExceptionMessageInResponse": false
  }
}
```

### appsettings.Development.json

```json
{
  "GrpcServices": {
    "{Entity}": { "Address": "https://localhost:5201" }
  },
  "ErrorInterceptorSettings": {
    "IncludeExceptionMessageInResponse": true
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
- [ ] `ErrorInterceptorSettings.IncludeExceptionMessageInResponse` is `false` in Production; gRPC and HTTP share one `ExceptionClassifier` mapping
- [ ] Service implementations delegate to application layer services (not direct DB access)
- [ ] Typed gRPC clients registered via `AddEFGrpcClient<T>` with a configured `GrpcClientSettings.Address`
- [ ] Cross-references: Aspire service discovery provides gRPC URLs; [api.md](api.md) for REST counterpart
