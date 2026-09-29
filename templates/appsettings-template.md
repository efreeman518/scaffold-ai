# appsettings.json Reference Template

| | |
|---|---|
| **Files** | `appsettings.json` per host (API, Gateway, Scheduler, Functions) |
| **Depends on** | [configuration-secrets.md](../skills/configuration-secrets.md) |
| **Referenced by** | [api.md](../skills/api.md), [gateway.md](../skills/gateway.md), [bootstrapper.md](../skills/bootstrapper.md) |

## API appsettings.json

This is a complete reference of all configuration sections used across the solution. Customize values per project.

```json
{
  "AppName": "{Host}.Api",
  "AuthMode": "Scaffold",

  "ConnectionStrings": {
    "{Project}DbContextTrxn": "Host=localhost;Port=35432;Database={project}db;Username=postgres;Password={postgres-password}",
    "{Project}DbContextQuery": "Host=localhost;Port=35432;Database={project}db;Username=postgres;Password={postgres-password}",
    "Redis1": "localhost:6379"
  },

  "CacheSettings": [
    {
      "Name": "Default",
      "DurationMinutes": 30,
      "DistributedCacheDurationMinutes": 60,
      "FailSafeMaxDurationMinutes": 120,
      "FailSafeThrottleDurationSeconds": 60,
      "RedisConnectionStringName": "Redis1",
      "BackplaneChannelName": "cache-sync"
    },
    {
      "Name": "StaticData",
      "DurationMinutes": 1440,
      "DistributedCacheDurationMinutes": 2880,
      "FailSafeMaxDurationMinutes": 4320,
      "FailSafeThrottleDurationSeconds": 300,
      "RedisConnectionStringName": "Redis1",
      "BackplaneChannelName": "cache-sync-static"
    }
  ],

  "AzureAd": {
    "Instance": "https://login.microsoftonline.com/",
    "TenantId": "{entra-tenant-id}",
    "ClientId": "{api-client-id}",
    "Audience": "api://{api-client-id}"
  },

  "Proxy": {
    "ForwardedHeaders": { "Enabled": false, "ForwardLimit": 1, "KnownProxies": [], "KnownNetworks": [], "AllowedHosts": [] },
    "PathBase": ""
  },

  "ForwardedClaims": {
    "HeaderName": "X-Forwarded-User-Claims",
    "ClaimTypes": [ "tenant_id" ],
    "TrustedCallerIds": [ "{gateway-service-client-id}" ]
  },

  "Cors": {
    "AllowedOrigins": [ "http://localhost:5173" ],
    "AllowCredentials": false
  },

  "RateLimiting": {
    "Tenants": {
      "TenantClaimType": "tenant_id",
      "DefaultTier": "standard",
      "Tiers": { "standard": { "PermitLimit": 100, "WindowSeconds": 60 } },
      "Budgets": { "export": { "PermitLimit": 5, "WindowSeconds": 60 } }
    }
  },

  "OpenTelemetry": {
    "MetricsEnabled": true,
    "Tracing": { "SampleRatio": 1.0 }
  },

  "Messaging": {
    "Inbox": { "ClaimLease": "00:01:00", "RenewalInterval": "00:00:20" }
  },

  "DataProtection": {
    "Persistence": "{DataProtectionPersistence}",
    "AzureBlob": {
      "ContainerName": "data-protection",
      "BlobName": "keys.xml"
    }
  },
  "DataProtectionKeysFileUrl": "",
  "DataProtectionEncryptionKeyUrl": "",

  "AiServices": {
    "Provider": "None",
    "UseSearch": false,
    "UseAgents": false,
    "UseVectorSearch": false,
    "DevStubContent": false,
    "Endpoint": "",
    "ChatModel": "",
    "EmbeddingModel": "",
    "FoundryEndpoint": "",
    "AgentModelDeployment": "",
    "EmbeddingModelDeployment": "",
    "SearchEndpoint": "",
    "SearchIndexName": "",
    "FoundryResourceName": "",
    "FoundryResourceGroup": "",
    "FoundryProjectEndpoint": "",
    "FoundryAgentName": ""
  },

  "OpenApiSettings": {
    "Enable": true
  },

  "EnforceHttpsRedirection": false,

  "Logging": {
    "LogLevel": {
      "Default": "Information",
      "Microsoft.AspNetCore": "Warning",
      "Microsoft.EntityFrameworkCore.Database.Command": "Warning"
    }
  },

  "AllowedHosts": "*"
}
```

## Gateway appsettings.json

```json
{
  "AppName": "{Gateway}.Gateway",
  "AuthMode": "Scaffold",

  "Gateway_EntraExt": {
    "Instance": "https://{tenant-name}.ciamlogin.com/",
    "TenantId": "{entra-external-tenant-id}",
    "ClientId": "{gateway-client-id}",
    "Audience": "{gateway-client-id}"
  },

  "Proxy": {
    "ForwardedHeaders": { "Enabled": false, "ForwardLimit": 1 },
    "PathBase": ""
  },

  "ForwardedClaims": {
    "HeaderName": "X-Forwarded-User-Claims",
    "ClaimTypes": [ "tenant_id" ],
    "TrustedCallerIds": [ "{gateway-service-client-id}" ]
  },

  "RateLimiting": {
    "Edge": { "Enabled": true, "TokensPerPeriod": 200, "ReplenishmentSeconds": 1, "QueueLimit": 0, "MaxConcurrentRequests": 1000 }
  },

  "AggregateHealthCheck": {
    "{Project}ApiHealthUrl": "https+http://{project}api/healthz/ready",
    "TokenScope": "",
    "TimeoutSeconds": 5
  },

  "ReverseProxy": {
    "Routes": {
      "api-route": {
        "ClusterId": "api-cluster",
        "AuthorizationPolicy": "Default",
        "Match": {
          "Path": "/api/{**catch-all}"
        },
        "Transforms": [
          { "PathRemovePrefix": "/api" }
        ]
      }
    },
    "Clusters": {
      "api-cluster": {
        "Destinations": {
          "api": {
            "Address": "https://localhost:7065"
          }
        },
        "Metadata": {
          "TokenScope": "api://{api-client-id}/.default",
          "RelayUserClaims": "true"
        }
      }
    }
  },

  "CorsSettings": {
    "AllowedOrigins": ["https://localhost:44318", "http://localhost:5173"],
    "AllowCredentials": true
  },

  "Logging": {
    "LogLevel": {
      "Default": "Information",
      "Microsoft.AspNetCore": "Warning",
      "Yarp": "Information"
    }
  }
}
```

## Scheduler appsettings.json (sections beyond the shared ones)

```json
{
  "OutboxDispatcher": { "MaxAttempts": 10 },
  "Scheduling": {
    "UsePersistence": true,
    "MaxConcurrency": 5,
    "PollIntervalSeconds": 30,
    "Retention": { "OccurrenceRetention": "7.00:00:00" },
    "Health": { "StallThreshold": "12:00:00" }
  }
}
```

## appsettings.Development.json (API)

```json
{
  "ConnectionStrings": {
    "{Project}DbContextTrxn": "Host=localhost;Port=35432;Database={project}db;Username=postgres;Password={postgres-password}",
    "{Project}DbContextQuery": "Host=localhost;Port=35432;Database={project}db;Username=postgres;Password={postgres-password}"
  },
  "OpenApiSettings": {
    "Enable": true
  },
  "Logging": {
    "LogLevel": {
      "Default": "Debug",
      "Microsoft.EntityFrameworkCore.Database.Command": "Information"
    }
  }
}
```

## Notes

- Connection string names must match what the Bootstrapper expects: `{Project}DbContextTrxn` and `{Project}DbContextQuery`
- Connection strings show the default `NonAzure` lane (PostgreSQL). The `Azure` lane uses the SQL Server form `Server=localhost,38433;Database={project}db;User Id=sa;Password={sql-password};TrustServerCertificate=True`, with `;ApplicationIntent=ReadOnly` on the Query string only. Supply real passwords through user secrets, never committed config
- With Aspire, connection strings are **injected automatically** via `.WithReference(projectDb, connectionName: ...)` - no manual config needed in development
- Redis connection string name (`Redis1`) must match the `RedisConnectionStringName` in `CacheSettings`
- `CacheSettings` is an array bound by EF.Cache `AddTypedCache` - each entry creates a named cache instance; `KeyNamespace` (default: the host environment name), `SchemaVersion`, `Serializer` and `Profiles` are optional per entry, and code decisions (schema version, profile durations) go in the `configure` callback
- `FailSafeThrottleDurationSeconds` - note the unit is **seconds** (passed to `TimeSpan.FromSeconds()`)
- `ForwardedClaims` is one section bound by both the API (`AddForwardedClaimsTransformation`) and the Gateway (`AddDownstreamAuthTransforms`), so the relay header name and claim allowlist match. `TrustedCallerIds` lists the gateway service-token `azp`/`appid` values the API trusts; an empty list disables the relay (fail closed)
- Phase 2 maps `hostingLaneDefaults.<active>.dataProtectionPersistence` to runtime `DataProtection:Persistence`; `TASKFLOW_DATAPROTECTION_PERSISTENCE` is the environment override. `AzureBlob` requires either `DataProtectionKeysFileUrl` or the `BlobStorage1` endpoint/connection used to derive it; `Redis` requires `Redis1`; `None` is limited to isolated development/test hosts. Key Vault encryption is independent and optional. Tests that select a persistence arm must inject that arm's required input. See [security.md](../skills/security.md#data-protection). Supply credentials through managed identity, never URL query strings.
- A Gateway cluster's `Metadata:TokenScope` gets a downstream token from `AccessTokenCache`; `Metadata:RelayUserClaims` adds the relay header. A cluster without `TokenScope` passes the inbound `Authorization` header through unchanged
- `Proxy`, `Cors`/`CorsSettings`, `RateLimiting:Tenants`, `RateLimiting:Edge`, `OpenTelemetry`, `Messaging:Inbox`, `OutboxDispatcher` and `Scheduling` are validated at registration or host start by their EF packages; an invalid value fails startup
- `OutboxDispatcher:MaxAttempts` defaults to 5 when unset
- `AuthMode` belongs on each auth-owning host and must be one validated value (`Scaffold`, `Local`, or `Entra`); production hosts use the same intended mode across the chain
- `AiServices:Provider` is the sole activation source. Endpoint, deployment, and connection values validate the selected provider but never activate it. Default to `None`. `OpenAICompatible` additionally requires `AiServices:ApiKey`, supplied only through user secrets or an environment/secret store.
- For production/Azure: use Key Vault references or App Configuration for secrets
