# Scalability and Multi-Lane Hosting

Load this file in Phase 2 when scale, high availability, more than one hosting lane, or a non-Azure deployment is in scope. Reload the relevant sections in Phase 5b for runtime wiring and Phase 5d for deployment proof. A scale target is an input to validate, not permission to add every pattern in this file.

## Workload Envelope Before Architecture

Record the smallest measurable envelope that can disprove the design:

- peak requests per second and concurrent connections,
- read/write ratio, payload sizes, and largest streamed result,
- p50, p95, and p99 latency targets,
- data volume, growth, retention, and tenant skew,
- recovery objectives and acceptable degraded behavior,
- expected replica count per host and cost ceiling.

Do not translate "millions of users" directly into services, brokers, CQRS, gRPC, sharding, or Native AOT. A million registered users, concurrent browser sessions, open sockets, and requests per second are different workloads. Keep a single deployable until an independently scaled or isolated boundary is demonstrated.

## Baseline and Conditional Patterns

| Pattern | Scaffold policy |
|---|---|
| Stateless request handling | Baseline for API, gateway, and workers. Persist durable workflow, session, key-ring, and coordination state outside process memory. |
| Async I/O without sync-over-async | Baseline. Do not use `.Result`, `.Wait()`, or blocking waits on request and worker paths. |
| Bounded concurrency | Baseline when independent I/O is parallelized. Sequential loops remain correct for ordered settlement, one `DbContext`, rate-limited dependencies, or bounded memory. |
| Liveness and readiness split | Baseline for every server host. Use the contract below. |
| Transactional outbox and consumer idempotency | Baseline when a database commit must cause at-least-once message delivery. See [../skills/messaging.md](../skills/messaging.md). |
| Provider switch | Baseline only for a provider family with more than one supported arm. Keep one provider for a single-lane app. |
| CQRS, read replicas, cache, gateway, gRPC, binary formats, hedging, distributed locks | Conditional. Add only for a measured workload or explicit topology requirement. |
| Server GC, DATAS, ReadyToRun, source-generated JSON, pooling | Conditional per host or hot path. Prove with a runtime smoke, load test, or benchmark. |
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
aiProviders: [AzureInference, OpenAICompatible, FoundryLocal, None]
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
| AI | `None`, optional `AzureInference` | `None`, optional `OpenAICompatible` or `FoundryLocal` |
| Data Protection | `AzureBlob` | `Redis` |
| Deployment | `ContainerApps` | `DockerCompose` |

Keep `Sql` search and `None` AI as defaults unless that lane provisions and validates the optional provider. `NonAzure` means zero Azure runtime dependencies: reject Azure App Configuration, Key Vault, Azure Data Protection key encryption, and every Azure-owned provider even when supplied through environment variables. A project that intentionally mixes provider families must declare a separately named lane and its compatibility matrix instead of weakening `NonAzure`. `Portable` remains a one-release input alias for `NonAzure`; do not emit it as a canonical lane. `Relational` remains a one-release input alias for the default NonAzure `PostgreSqlJsonb` read model. `MongoDb` is the explicit document-database alternative.

`FoundryLocal` remains conditional for an app that explicitly requires and proves the native runtime. It is never selected because a package, endpoint, or runtime happens to be present, and TaskFlow no longer supplies runnable proof for that arm.

## Statelessness and Stateful Exceptions

- Persist Data Protection keys anywhere more than one replica, restart, or rolling deploy must accept the same cookies or protected cursors.
- Treat in-memory cache, rate limits, locks, channels, and feature flags as per-process unless a distributed backend proves otherwise.
- Blazor Server circuits are stateful. Either use affinity and record its failover ceiling, or choose a stateless UI architecture when transparent replica failover is required.
- In-memory background queues are for disposable work only. Durable work uses a persisted scheduler, outbox, or broker.
- A distributed lock is coordination, not exactly-once proof. Make the protected operation idempotent and use token-checked release. Work-table consumers use leases or atomic claims instead of a global lock.
- Treat a persistent container volume target as stored-data metadata. Before changing an existing PostgreSQL named volume from one image-major mount root to another, require a verified backup plus migration/restore proof or an explicit disposable-volume declaration. Container health against a newly initialized empty cluster does not prove preserved data.

## Data-Path Rules

- Clamp caller page size on the server. High-cardinality or mutation-heavy feeds use keyset/cursor paging with a unique tie-breaker and `Take(limit + 1)` rather than a mandatory `COUNT(*)`.
- Keep read-your-writes on the transaction connection. Route only explicitly stale-tolerant reads to replicas.
- Provision external containers, buckets, tables, and broker topology once in a startup task or deployment step, not on every repository operation.
- Stream large results with `IAsyncEnumerable<T>` or the response body writer only when the API contract supports partial delivery and cancellation. Do not hold one `DbContext` across parallel work.
- Provider-specific features such as `jsonb`, pgvector, SQL-specific hints, or native concurrency tokens remain isolated optional arms with an integration test on that provider.

## Async and Hot-Path Discipline

"Never await in a loop" is not a rule. Use the smallest correct shape:

- sequential `await` for ordered work, shared `DbContext`, broker settlement, or backpressure;
- `Task.WhenAll` for a small known set of independent operations;
- a bounded `Channel<T>`, semaphore, or worker pool for unbounded input;
- one DI scope and one `DbContext` per concurrent unit of work.

Use `ValueTask<T>`, `ArrayPool<T>`, `MemoryPool<T>`, custom serializers, and reused writers only on measured hot paths. Each optimization leaves a benchmark or allocation assertion that compares it with the simpler implementation.

## Runtime Profile Per Host

Record runtime decisions per host, not solution-wide:

- long-lived, high-throughput server hosts may use Server GC with DATAS after container-memory load proof;
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

## Edge, TLS, and Rate Limits

- Terminate public TLS at the declared edge. If every lane uses edge TLS, internal HTTP hosts do not call `UseHttpsRedirection()`; redirection behind a proxy can target an untrusted development certificate or loop. Configure forwarded headers before auth and routing.
- Gateway health uses `/healthz/ready`, bounded activity timeouts, and active plus passive destination health. Add load balancing only when more than one destination exists.
- Use an unauthenticated edge limiter for volumetric protection and an authenticated tenant/account limiter for fairness. State explicitly whether limits are per replica or shared. A fail-open distributed limiter needs an alert; fail-closed needs an availability decision.
- Hedging is opt-in for idempotent reads only. Guard both outcome-triggered and delay-triggered hedges so a slow write cannot be duplicated.

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

TaskFlow implementations and tests are indexed in [taskflow-proof-map.md](taskflow-proof-map.md). The dated evidence and promotion decisions for the September 2026 refactor live in [scaffold-proof-scale-audit-2026-09-04-to-2026-09-09.md](scaffold-proof-scale-audit-2026-09-04-to-2026-09-09.md).
