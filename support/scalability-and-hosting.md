# Scalability and Multi-Lane Hosting

Load this file in Phase 2 when scale, high availability, more than one hosting lane, or a non-Azure deployment is in scope. Reload the relevant sections in Phase 5b for runtime wiring and Phase 5d for deployment proof. A scale target is an input to validate, not permission to add every pattern in this file.

## Workload Envelope Before Architecture

Record the smallest measurable envelope that can disprove the design:

- peak requests per second, concurrent connections, and long-lived sockets (SignalR, WebSocket, gRPC streams),
- read/write ratio, payload sizes, and largest streamed result,
- p50, p95, and p99 latency targets,
- data volume, growth, retention, and tenant skew,
- recovery objectives and acceptable degraded behavior,
- expected replica count per host, regions or data-residency constraints, and cost ceiling.

Do not translate "millions of users" directly into services, brokers, CQRS, gRPC, sharding, or Native AOT. A million registered users, concurrent browser sessions, open sockets, and requests per second are different workloads. Keep a single deployable until an independently scaled or isolated boundary is demonstrated. A scale claim is proven by an asserted `Test.Load` run at the envelope rate against the deployed topology ([../templates/test-templates-quality.md](../templates/test-templates-quality.md) section Load Tests (In-House LoadRunner)), not by the patterns adopted.

## Baseline and Conditional Patterns

| Pattern | Scaffold policy |
|---|---|
| Stateless request handling | Baseline for API, gateway, and workers. Persist durable workflow, session, key-ring, and coordination state outside process memory. |
| Async I/O without sync-over-async | Baseline. Do not use `.Result`, `.Wait()`, or blocking waits on request and worker paths. |
| Cancellation propagation | Baseline. Flow `HttpContext.RequestAborted` or the worker `stoppingToken` into every I/O call so abandoned work stops holding connections. |
| Bounded queues and explicit overload | Baseline. Every channel, in-memory queue, and consumer prefetch is bounded. Overload rejects with 429 or 503 plus `Retry-After`; it never buffers without limit. See Overload, Timeouts, and Shutdown. |
| Connection budget | Baseline once a host scales out. See Connection and Capacity Budgets. |
| Bounded concurrency | Baseline when independent I/O is parallelized. Sequential loops remain correct for ordered settlement, one `DbContext`, rate-limited dependencies, or bounded memory. |
| Liveness and readiness split | Baseline for every server host. Use the contract below. |
| Transactional outbox and consumer idempotency | Baseline when a database commit must cause at-least-once message delivery. See [../skills/messaging.md](../skills/messaging.md). |
| Provider switch | Baseline only for a provider family with more than one supported arm. Keep one provider for a single-lane app. |
| CQRS, read replicas, cache, gateway, gRPC, binary formats, hedging, distributed locks, output caching, remote feature-flag service | Conditional. Add only for a measured workload or explicit topology requirement. Every package or service these need passes **GR-04**, including its license cost. |
| GC settings beyond runtime defaults, ReadyToRun, source-generated JSON, pooling, `ValueTask`, buffer pools | Conditional per host or hot path. Prove with a runtime smoke, load test, or benchmark. |
| Native AOT | Decision-recorded evaluation, not a default. Every dependency and generated serialization path must support trimming/AOT. |
| Sharding and partitioning | Deferred until data size, tenant skew, or write contention demonstrates need. Choose tenant-first keys early only when tenancy and distribution requirements justify them. |

## Independent Provider Switches

Each switch owns five things in one module:

1. A closed enum of supported providers.
2. A configuration key and optional environment-variable override.
3. One resolver with precedence `environment > config > lane default > hard default`, followed by lane-compatibility validation.
4. One registration or provider-options branch.
5. Selector and default-arm tests.

Unknown configured values fail startup and name allowed values. Cross-lane configured values also fail startup and name the lane, configuration key, rejected value, and values allowed in that lane. An environment or configuration value can select a same-lane opt-in; it cannot weaken a strict lane boundary. Never silently fall back after an explicit but invalid value. Domain and application code depend on provider-neutral ports; provider namespaces stay in their infrastructure adapter. Database provider branching belongs in one options extension plus provider-specific migration assemblies, not throughout mappings and repositories.

## Lane Presets

A lane owns a compatible provider profile and deployment topology. It is not a second branch point: the shared resolver selects provider values, validates them against the lane, and returns canonical settings. Outside that resolver and the AppHost topology map, code reads only its own provider switch.

Single-lane projects keep the default compact:

```yaml
hostingLanes: [Azure]
deployTargets: [ContainerApps]
```

Multi-lane projects declare every supported arm and the lane defaults:

```yaml
hostingLanes: [Azure, NonAzure]
hostingLaneDefaults:
  Azure:
    databaseProvider: SqlServer
    messagingProvider: ServiceBus
    storageProvider: AzureBlob
    readModelProvider: Cosmos
    auditProvider: AzureTable
    searchProvider: Sql
    aiProvider: None
    dataProtectionPersistence: AzureBlob
    deploymentTarget: ContainerApps
  NonAzure:
    databaseProvider: PostgreSql
    messagingProvider: RabbitMq
    storageProvider: S3
    readModelProvider: PostgreSqlJsonb
    auditProvider: Relational
    searchProvider: Sql
    aiProvider: None
    dataProtectionPersistence: Redis
    deploymentTarget: DockerCompose

storageProviders: [AzureBlob, S3]
readModelProviders: [Cosmos, PostgreSqlJsonb, MongoDb]
auditProviders: [AzureTable, Relational]
searchProviders: [AzureAiSearch, PgVector, Sql]
aiProviders: [AzureInference, OpenAICompatible, None]
dataProtectionPersistence: [AzureBlob, Redis, None]
deployTargets: [ContainerApps, DockerCompose]
```

`Azure` and `NonAzure` are strict profiles. Their default and permitted opt-in arms are:

| Switch | Azure | NonAzure |
|---|---|---|
| Database | `SqlServer` | `PostgreSql` |
| Messaging | `ServiceBus` | `RabbitMq` |
| Storage | `AzureBlob` | `S3` |
| Read model | `Cosmos` | `PostgreSqlJsonb`, optional `MongoDb` |
| Audit | `AzureTable` | `Relational` |
| Search | `Sql`, optional `AzureAiSearch` | `Sql`, optional `PgVector` |
| AI | `None`, optional `AzureInference` | `None`, optional `OpenAICompatible` |
| Data Protection | `AzureBlob` | `Redis` |
| Deployment | `ContainerApps` | `DockerCompose` |

Keep `Sql` search and `None` AI as defaults unless that lane provisions and validates the optional provider. `NonAzure` means zero Azure runtime dependencies: reject Azure App Configuration, Key Vault, Azure Data Protection key encryption, and every Azure-owned provider even when supplied through environment variables. A project that intentionally mixes provider families must declare a separately named lane and its compatibility matrix instead of weakening `NonAzure`. `Portable` remains a one-release input alias for `NonAzure`; do not emit it as a canonical lane. `Relational` remains a one-release input alias for the default NonAzure `PostgreSqlJsonb` read model. `MongoDb` is the explicit document-database alternative.

## Statelessness and Stateful Exceptions

- Persist Data Protection keys anywhere more than one replica, restart, or rolling deploy must accept the same cookies or protected cursors.
- Treat in-memory cache, rate limits, locks, channels, and feature flags as per-process unless a distributed backend proves otherwise.
- Blazor Server circuits are stateful. Either use affinity and record its failover ceiling, or choose a stateless UI architecture when transparent replica failover is required.
- In-memory background queues are for disposable work only. Durable work uses a persisted scheduler, outbox, or broker.
- A distributed lock is coordination, not exactly-once proof. Make the protected operation idempotent and use token-checked release. Work-table consumers use leases or atomic claims instead of a global lock.
- A lease can expire while its holder is paused (GC, network, throttling). When a stale holder could corrupt data, the protected write checks a monotonically increasing fencing token or a conditional version update. Redlock across independent Redis nodes does not remove that need; prefer one store's lease plus a fencing check, or a database row lease. PostgreSQL advisory locks behind a transaction-mode pooler must be transaction-scoped (`pg_advisory_xact_lock`); see Connection and Capacity Budgets.
- SignalR and other long-lived connections are per-replica state. More than one replica needs a backplane or managed service, and non-WebSocket transports need affinity. Record connections per replica in the envelope.
- Treat a persistent container volume target as stored-data metadata. Before changing an existing PostgreSQL named volume from one image-major mount root to another, require a verified backup plus migration/restore proof or an explicit disposable-volume declaration. Container health against a newly initialized empty cluster does not prove preserved data.

## Data-Path Rules

- Clamp caller page size on the server. High-cardinality or mutation-heavy feeds use keyset/cursor paging with a unique tie-breaker and `Take(limit + 1)` rather than a mandatory `COUNT(*)`.
- Keep read-your-writes on the transaction connection. Route only explicitly stale-tolerant reads to replicas.
- Provision external containers, buckets, tables, and broker topology once in a startup task or deployment step, not on every repository operation.
- Stream large results with `IAsyncEnumerable<T>` or the response body writer only when the API contract supports partial delivery and cancellation. A stream holds its database connection for as long as the slowest client reads, and an error after the first byte cannot become a clean status code, so bounded pages remain the default for interactive APIs. Do not hold one `DbContext` across parallel work.
- Compute projections, totals, and derived metrics on read while their cost at the envelope rate fits the latency budget. Past that, materialize a projection with an owned rebuild or replay path. A cache is a copy; never make it the only home of derived data that cannot be recomputed.
- Set-based writes (`ExecuteUpdateAsync`/`ExecuteDeleteAsync`), split queries, and dirty reads follow [../skills/data-persistence.md](../skills/data-persistence.md) section Set-Based Writes and Query Shape.
- High-churn work, queue, and outbox tables: PostgreSQL `DELETE` and `UPDATE` leave dead tuples that only vacuum reclaims, so hard deletes alone do not prevent bloat. Tune autovacuum per hot table, prevent long-running and idle-in-transaction sessions that pin the vacuum horizon, and implement time-based retention as time partitions that are detached or dropped instead of a mass `DELETE`. On SQL Server, purge in small batches to stay under lock escalation, or switch out partitions.
- Provider-specific features such as `jsonb`, pgvector, SQL-specific hints, or native concurrency tokens remain isolated optional arms with an integration test on that provider. Index only the `jsonb` paths or vector columns a query actually filters on, and prove the index with that provider's query plan.

## Async and Hot-Path Discipline

"Never await in a loop" is not a rule. Use the smallest correct shape:

- sequential `await` for ordered work, shared `DbContext`, broker settlement, or backpressure;
- `Task.WhenAll` for a small known set of independent operations;
- a bounded `Channel<T>`, semaphore, or worker pool for unbounded input;
- one DI scope and one `DbContext` per concurrent unit of work.

Use `ValueTask<T>`, `ArrayPool<T>`, `MemoryPool<T>`, custom serializers, and reused writers only on measured hot paths. Each optimization leaves a benchmark or allocation assertion that compares it with the simpler implementation. A `ValueTask` is awaited exactly once and never stored; a rented buffer is returned in `finally` and never touched after return.

Thread-pool starvation is the usual symptom of hidden sync-over-async under load: latency climbs while CPU stays low and the thread-pool queue length grows (`dotnet-counters monitor System.Runtime`). Fix the blocking call; raising `ThreadPool.SetMinThreads` only hides it.

## Runtime Profile Per Host

Record runtime decisions per host, not solution-wide:

- ASP.NET Core (Web SDK) hosts run Server GC by default, and the current runtime enables DATAS by default under Server GC, so neither needs an explicit property. Worker SDK hosts default to Workstation GC; a high-throughput worker opts into `ServerGarbageCollection` only after measurement. A process limited to one logical CPU always runs Workstation GC regardless of settings. Change GC mode or heap count, or disable DATAS, only after a load test at the container limit shows a regression, for example allocation waits during a burst while DATAS grows from its single starting heap;
- in a container the GC heap hard limit defaults to 75% of the memory limit and Server GC sizes heaps from the CPU limit, so every host declares explicit CPU and memory limits. Log `GCSettings.IsServerGC` and the effective heap limit at startup so the running configuration is evidence, not assumption;
- short-lived migrator and bootstrap jobs normally use Workstation GC;
- ReadyToRun trades larger images for startup latency and is useful only when scale-out startup matters;
- source-generated JSON is required for trimmed/AOT code and for a benchmark-proven serialization hot path, not every internal DTO by policy;
- a host that opens `Microsoft.Data.SqlClient` connections must not run with invariant globalization and a base image missing ICU.

Run at least one live host smoke with the shipped runtime properties and final container base. Unit and Testcontainers tests can miss host-level MSBuild properties and native/globalization failures.

## Health Probe Contract

Map the same unauthenticated paths on every server host:

| Path | Meaning | Contents |
|---|---|---|
| `/healthz/live` | Restart decision | Process self-check only. No database, broker, cache, or downstream calls. |
| `/healthz/ready` | Traffic decision | Critical dependencies and required schema/startup completion for this host. |
| `/healthz` | Operator aggregate | All registered checks for diagnosis. Never use as liveness. |

Readiness is host-specific. A broker consumer host can require its database, outbox/inbox schema, scheduler store, and broker. A cache that has a proven L1 or direct-store fallback should report degraded telemetry without removing the host from traffic. Tests must prove a critical dependency failure makes readiness unhealthy while liveness stays healthy.

## Overload, Timeouts, and Shutdown

- Give every endpoint a request timeout (`AddRequestTimeouts` with named policies). Budgets shrink per hop - edge > gateway > API > downstream call - so an inner call never outlives the caller that will abandon it.
- Shed load before collapse. A global concurrency limiter rejects with 503 plus `Retry-After` when in-flight work exceeds measured capacity; rate limits (429) protect fairness and are a separate control. Set Kestrel request-size and minimum-data-rate limits deliberately on public hosts.
- Retry at one layer only. ServiceDefaults already retries safe internal calls ([../skills/resilience.md](../skills/resilience.md)); the gateway, the caller, and the broker must not all retry the same operation. Clients honor `Retry-After`.
- Graceful shutdown: on SIGTERM readiness fails first, the host stops accepting work, and in-flight requests finish within `HostOptions.ShutdownTimeout`, which stays shorter than the orchestrator's termination grace period. Consumers stop fetching and complete or abandon in-flight messages so the broker redelivers; durable work never lives only in memory at shutdown. Scale-in depends on this path.
- Use the orchestrator's startup probe for slow warm-up instead of loosening liveness thresholds.

## Connection and Capacity Budgets

- Database budget: `max replicas × hosts × pools per host × max pool size` stays below the database connection limit minus a reserve for the migrator, operators, and replication. Each distinct connection string is its own ADO.NET pool, so separate Trxn and Query connection strings double the count. Derive autoscaler max replicas from this budget, not the reverse.
- PostgreSQL behind a transaction-mode pooler (PgBouncer or a managed equivalent): session state does not survive between transactions. Session advisory locks, `SET`, `LISTEN/NOTIFY`, temporary tables, and reliance on `search_path` break. Keep Npgsql automatic preparation off unless the pooler's prepared-statement support is configured and tested. Runtime hosts connect through the pooler; the migrator connects directly because DDL and session features need a dedicated connection.
- SQL Server has no external pooler; the per-replica ADO.NET pools are the budget, bounded by the service tier's session and worker limits.
- Outbound HTTP uses `IHttpClientFactory` clients configured by ServiceDefaults; never create an `HttpClient` per call. Redis uses one `IConnectionMultiplexer` per process.
- Consumer concurrency and prefetch draw on the same database budget. Ordered processing needs a partition or session key; parallel consumers on one queue give no ordering guarantee.
- Autoscale on the signal that saturates first: HTTP concurrency or CPU for API hosts, queue depth or consumer lag for workers (KEDA scalers on Container Apps). Hosts with an availability target run at least two replicas.
- gRPC over HTTP/2 multiplexes calls on one long-lived connection, so a layer-4 balancer pins each client to one replica. See [../skills/grpc.md](../skills/grpc.md) section Load Balancing and Deadlines.

## Edge, TLS, and Rate Limits

- Terminate public TLS at the declared edge. If every lane uses edge TLS, internal HTTP hosts do not call `UseHttpsRedirection()`; redirection behind a proxy can target an untrusted development certificate or loop. Configure forwarded headers before auth and routing.
- Gateway health uses `/healthz/ready`, bounded activity timeouts, and active plus passive destination health. Add load balancing only when more than one destination exists.
- Use an unauthenticated edge limiter for volumetric protection and an authenticated tenant/account limiter for fairness. State explicitly whether limits are per replica or shared: in-process `System.Threading.RateLimiting` limiters are per replica, so the effective limit is the configured limit times the replica count. Global quotas belong at the edge or in a shared store. A fail-open distributed limiter needs an alert; fail-closed needs an availability decision.
- Cacheable GETs return `ETag` and `Cache-Control`, and conditional requests return 304. Output caching across replicas needs a shared store, and a response that varies by tenant or user either varies the cache key or is not cached. Static assets go through a CDN.
- Hedging is opt-in for idempotent reads only. Guard both outcome-triggered and delay-triggered hedges so a slow write cannot be duplicated. Registration: [../skills/resilience.md](../skills/resilience.md) section Hedging.
- Binary payload formats (MessagePack, Protobuf outside gRPC) for cache values or queue messages need measured size or CPU gain over System.Text.Json, pass **GR-04**, run in the serializer's untrusted-input mode, use explicit versioned member keys, and prove a mixed-version rolling deploy reads both shapes.

## Messaging and Trace Continuity

Persist the full versioned envelope in the outbox. Carry message id, tenant or partition key, correlation id, event type/version, occurred time, and W3C `traceparent`/`tracestate`. Producers inject trace context into transport headers; consumers extract it and start a consumer activity from that parent. Retries and malformed payloads follow the broker's retry/dead-letter contract; never catch and acknowledge a failed message as success.

## Deployment and Verification Matrix

Every declared lane leaves executable proof at the cheapest useful level:

| Contract | Minimum proof |
|---|---|
| Resolver precedence | Pure unit tests for hard default, lane default, config, env override, and unknown-value failure. |
| DI default arm | Resolve each provider-neutral contract from an empty/default configuration. |
| Topology | Source/model test for included resources and per-host environment keys. |
| Strict lane | Exact default-profile test, same-lane opt-in test, cross-lane rejection matrix, zero-Azure NonAzure test across configuration and environment sources, and unknown-lane/provider diagnostics. |
| Deployment ownership | Each lane maps to one declared target; Compose rejects non-`NonAzure` input and Azure IaC rejects non-`Azure` input. |
| Database/provider behavior | Same integration and E2E suite against every `databaseProviders` arm, including migration drift. |
| Broker semantics | Publish/consume, retry, dead-letter, inbox replay, and trace-parent tests per transport. |
| Compose or equivalent | Configuration parse on ordinary CI; full image and CRUD smoke in an explicit expensive lane. Concurrency-protected cleanup reads a strong ETag and sends `If-Match`. |
| Runtime image | Live connection and port-bind smoke using final host properties and base image. |
| Deployment | Digest-pinned release manifest, database-first rollout, readiness plus CRUD smoke, and rollback without rebuild. |

Pin shared CI and deployed images with both a reviewed tag and immutable digest. A concrete reviewed tag alone is acceptable only for explicitly local-only or unresolved cross-architecture topology. Record when a digest covers one architecture rather than a manifest list. Never consume a floating `latest` tag. Capture container state and logs while the failed graph is still alive, gate diagnostics on the failing step's conclusion, and redact environment values.

## Proof

TaskFlow implementations and tests are indexed in [taskflow-proof-map.md](taskflow-proof-map.md).
