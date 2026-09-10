# Scaffold-Proof Scale and Hosting Audit

Audit window: 2026-09-04 through 2026-09-09, inclusive. Evidence repository: `efreeman518/scaffold-proof`, default branch `main`.

## Evidence Boundary

- Base: `86908b6` (repository rename merged).
- [PR 10](https://github.com/efreeman518/scaffold-proof/pull/10), merge `6d282f4`: dual EF providers, provider-neutral outbox/inbox, independent provider switches, Azure and Portable lane presets, runtime/health/edge guidance, provider and deployment test matrices.
- [PR 11](https://github.com/efreeman518/scaffold-proof/pull/11), merge `e90b3d6`: removed redundant main-push CI, moved expensive lanes to a lower cadence, and removed Blazor HTTPS redirection that broke behind edge TLS.
- [PR 12](https://github.com/efreeman518/scaffold-proof/pull/12), merge `226bec9`: fixed a stale partition-key test expectation, pinned the remaining SQL image, and captured failure diagnostics while the Aspire graph remained alive.
- Proof-reported verification for PR 10: 52-project zero-warning build, 663 fast tests after follow-up, SQL Server and PostgreSQL integration/E2E/FlowEngine lanes, RabbitMQ transport tests, migration drift checks, Bicep build, and Compose configuration validation. Full Compose/VPS execution remained deployment-only at merge time and is not treated as proven runtime behavior.

## Selection Rule

Promote repeated or severe correctness, security, deployment, and operability lessons. Generalize the invariant and its executable proof. Do not copy TaskFlow-specific providers, topology, or performance tuning into every generated app.

Classification: `P` promotes a scaffold baseline, `C` becomes conditional guidance, `D` defers until a contract/package owner can support it safely, and `N` rejects a blanket prescription.

## Decisions

| Evidence or supplied claim | Class | Scaffold treatment |
|---|---|---|
| Stateless scale-out | P | Server hosts keep durable state outside process memory; stateful UI and key-ring exceptions must be explicit. |
| Independent providers plus Azure/Portable lane | P | Add `hostingLanes`, provider matrices, and lane defaults. A lane seeds defaults only; explicit switches win; invalid values fail startup. |
| Dual relational providers | C | One provider-options branch, one shared model where possible, separate migration assemblies, and the same real-database suite per arm. Do not force two providers on a single-lane app. |
| Transactional outbox, consumer inbox, leases, DLQ | P when a commit must publish | Replace the prior declared-only outbox flag with implementation and replay proof requirements. |
| Cursor paging and page-size clamp | P for high-cardinality feeds | Keep offset paging for small/admin data; require a unique tie-breaker and tamper/tenant validation for cursors. |
| Startup provisioning | P | Create external containers/tables/topology once, not per repository call. |
| Separate live/ready/aggregate probes | P | Canonicalize `/healthz/live`, `/healthz/ready`, and `/healthz`; remove `/readyz` drift. |
| Edge TLS without app redirect | P when TLS terminates upstream | Do not call `UseHttpsRedirection()` on internal hosts; prove forwarded-header and public redirect behavior at the edge. |
| Concrete container tags and release digests | P | No floating `latest`; deployment uses digest-pinned manifests and rollback without rebuild. |
| Diagnostics captured before graph teardown | P for mesh CI | Capture state/logs while resources run; failure-gate on the target step and keep diagnostic commands non-fatal. |
| Per-host runtime profile | C | Long-lived servers may use Server GC/DATAS; migrators use Workstation GC; smoke the actual host/container settings. |
| Source-generated JSON and reused writer | C | Require for trim/AOT or measured serialization hot paths; leave a completeness test or benchmark. |
| `ValueTask`, pools, zero-allocation policy | N as blanket, C per hot path | Use only after measurement. Lifetime mistakes and complexity outweigh speculative allocation savings. |
| "Never invoke async calls in loops" | N | Sequential async is required for ordering, `DbContext`, settlement, and backpressure. Parallelize independent I/O with a bound. |
| CQRS everywhere | N as blanket, C by workload | Use when independent write/read models or team boundaries justify it; it is not a concurrency prerequisite. |
| Mandatory MassTransit | N | Keep the BCL/provider SDK path when it is smaller. Adopt a framework only when it replaces owned infrastructure rather than duplicating it. |
| FusionCache plus Redis everywhere | N as blanket, C for repeated expensive reads | Define freshness, invalidation, stampede, outage, and cross-replica semantics first. |
| Persist only inputs and recompute projections | N as blanket | Materialize expensive or operationally critical projections when SLO, cost, or recovery requires it. |
| gRPC/MessagePack for all internal traffic | N as blanket, C for measured boundaries | Public contracts stay interoperable; choose binary protocols per high-volume internal boundary. |
| PgBouncer, replicas, pgvector, JSONB, partitioning | C | Provider-specific opt-ins with compatibility, fail-fast configuration, and provider integration proof. |
| Redis Redlock as universal lock | N | Prefer atomic claims/leases for work rows. A single Redis token lock is only an optimization around idempotent startup work, not correctness proof. |
| GET hedging | C | Only for idempotent reads with explicit attempt and cost bounds. |
| Dynamic feature flags | C | Use for canary or emergency degradation. Gate at the owning endpoint/consumer and preserve a local configuration fallback. |
| Whole-app Native AOT | D/C | Record dependency compatibility and a measured reason. TaskFlow correctly deferred it because EF and workflow/scheduler dependencies did not support the desired contract. |

## Follow-On Defects That Changed Scaffold Policy

- PR 10's shared runtime profile made SQL-dependent hosts invariant-globalized; `Microsoft.Data.SqlClient` failed only in a live host. Unit and container-backed tests had not imported the host properties. Result: require a live shipped-profile smoke for each host that opens a provider connection.
- PR 11 showed application HTTPS redirection conflicts with edge-owned TLS. Result: the selected lane owns TLS once, and internal hosts do not redirect when every public route crosses that edge.
- PR 12 showed a retention partition-key change left mesh tests querying the old key, while startup SQL logs distracted diagnosis. Result: partition/key contracts need shared helpers or direct contract assertions, and failure diagnostics must be captured before teardown.
- The Portable Compose/VPS path was configuration-validated but not executed on the development machine. Result: classify unexecuted lanes as `deployment-only`; never promote configuration parsing into a runtime-proof claim.

## Canonical Owners Updated

- Phase 1/2 decision and schema: `ai/shared-understanding-interview.md`, `ai/resource-implementation-schema.md`, `schemas/resource-implementation.schema.json`.
- Cross-cutting policy: `support/scalability-and-hosting.md`.
- Data, messaging, probes, and runtime wiring: `skills/data-persistence.md`, `skills/messaging.md`, `skills/observability.md`, `patterns/infrastructure-wiring.md`.
- Concrete proof index: `support/taskflow-proof-map.md`.
- Regression guard: `scripts/validate-instructions.py` plus tooling tests.
