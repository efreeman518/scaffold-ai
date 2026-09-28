# Docker Compose Deployment

Canonical owner for the `DockerCompose` deployment target, the default deployment of the `NonAzure` lane: file layout, service rules, edge, secrets, observability, and the release workflow. Load it in Phase 5d when `deployTarget` or a `hostingLaneDefaults` entry is `DockerCompose`. Lane and provider policy stay in [scalability-and-hosting.md](scalability-and-hosting.md) section Lane Presets, the generic release contract in [../skills/cicd.md](../skills/cicd.md) -> *Step order (schema leads code)*, image shape in [../templates/dockerfile-template.md](../templates/dockerfile-template.md), and Azure infrastructure in [../skills/iac.md](../skills/iac.md).

Write the Compose files by hand. Do not publish the AppHost to Compose: it adds a hosting package and generated files that are harder to tune than the stack they replace.

## File Layout

| Path | Contents |
|---|---|
| `deploy/compose/docker-compose.yml` | Canonical stack with a fixed project `name:`: edge, migrator, each deployable host, infrastructure, optional profiles |
| `deploy/compose/docker-compose.override.local.yml` | `local` profile only: `build:` for app images, plain-HTTP Caddy, dev-only credentials, no deployed observability backend |
| `deploy/compose/Caddyfile`, `Caddyfile.local` | ACME TLS edge; plain `:80` variant for CI |
| `deploy/compose/.env.example` | Committed environment contract: lane-owned values plus `CHANGE_ME_` placeholders |
| `deploy/compose/images.env.example` | Shape of the workflow-written digest pins |
| `deploy/compose/static/` | nginx site config and `app-config.json` template for static SPA images |
| `deploy/compose/pgbouncer/` | Opt-in `pooler` profile config and credential template |
| `deploy/compose/README.md` | Operator runbook: first deploy, secret rotation, rollback, logs, single-node ceiling |

Gitignore `.env`, `.env.base`, and `images.env` under `deploy/compose/`.

## Service Rules

- One service per deployable host (migrator, API, Gateway, Scheduler, each UI) plus its infrastructure. Runtime hosts merge one YAML anchor that sets `Hosting__Lane: NonAzure` and every lane-owned provider value; the strict lane resolver rejects anything else. Function apps have no Compose service.
- The migrator runs with `restart: "no"`. Every app service waits on `migrator: condition: service_completed_successfully` (**GR-17**) and `service_healthy` for each infrastructure dependency; optional-profile dependencies use `required: false`.
- Infrastructure containers carry native `healthcheck:` probes (`pg_isready`, authenticated `redis-cli ping`, `rabbitmq-diagnostics -q check_running`, the object store's unauthenticated health endpoint). Chiseled app images have no shell or `curl`, so app services carry no `healthcheck:`: Caddy active upstream checks on `/healthz/ready` gate traffic ([scalability-and-hosting.md](scalability-and-hosting.md) section Health Probe Contract). Never add `curl` to a runtime image to satisfy a probe.
- Only Caddy publishes ports (80, 443). Put Caddy and each service it proxies on a bridge `edge` network; app, data, cache, and telemetry networks are `internal: true`, and each service joins only what it calls. Gateway and UI containers get no data-plane credentials.
- Set `deploy.resources.limits` for CPU and memory on every long-running service.
- Set `Hosting__ShutdownTimeoutSeconds` below Compose's 10 s default stop grace (TaskFlow: 8) so hosted services finish before SIGKILL; raise `stop_grace_period` instead when a host needs longer. The readiness drain delay stays 0.
- Optional topology is a Compose profile (`pooler`, alternative read model). The deploy workflow derives `COMPOSE_PROFILES` from the provider settings; operators never set it.

## Edge and Static UIs

- Caddy terminates TLS with automatic ACME for `{$CADDY_DOMAIN}`; DNS must resolve before the first `up`. `/api/*` and health paths go to the Gateway, other paths to a server-rendered UI, and each static UI and the browser-facing object-store host get their own site block. A presigned URL signs its Host, so the object-store public URL must be a browser-reachable origin.
- The Gateway trusts exactly one forwarded hop (`Proxy__ForwardedHeaders__ForwardLimit=1`). Edge TLS rules: [scalability-and-hosting.md](scalability-and-hosting.md) section Edge, TLS, and Rate Limits.
- Blazor Server above one replica needs a sticky upstream policy first.
- Static SPA images run unprivileged nginx with `static/default.conf`: an extension path that misses returns 404 (never the SPA shell), extensionless routes fall back to `index.html`, `index.html` is `no-cache`, and `app-config.json` is `no-store` and rendered at container start from `GATEWAY_BASE_URL`, so one image digest serves any gateway origin.

## Secrets and Image Pins

- The operator copies `.env.example` to `.env.base` on the host (mode 600, never committed, never baked into an image). The workflow writes `images.env`. Compose interpolates only from `.env`, so every deploy and rollback regenerates `.env` from `.env.base` plus `images.env`; nobody edits `.env`. Required values use `${VAR:?message}` so a missing secret fails `docker compose config`.
- The deploy refuses a `.env.base` that contains a `CHANGE_ME_` value, image variables, `COMPOSE_PROFILES`, or `OTEL_EXPORTER_OTLP_ENDPOINT`.
- Centralize tags: infrastructure images carry a reviewed tag plus digest inline in `docker-compose.yml` and change only by deliberate edit; app images change only through digest refs in `images.env`. Pin policy: [scalability-and-hosting.md](scalability-and-hosting.md) section Deployment and Verification Matrix.
- The private package-feed credential reaches the image build only as a BuildKit secret, never through `.env` or an image layer.

## Observability

- Local runs use the Aspire Dashboard; the `local` profile excludes the deployed backend and clears OTLP settings.
- Deployed: OpenObserve OSS single-node (AGPL-3.0; record the choice in `.scaffold/DESIGN-DECISIONS.md`) on a persistent volume, UI bound to `127.0.0.1` for an SSH tunnel, OTLP gRPC internal to the telemetry network. Hosts export logs and traces directly with `OTEL_EXPORTER_OTLP_ENDPOINT=http://openobserve:5081`, `OTEL_EXPORTER_OTLP_PROTOCOL=grpc`, and headers `Authorization=Basic <base64 org:ingestion-token>`, `organization`, `stream-name`. Hosts get an organization ingestion token, never root credentials. `OpenTelemetry__MetricsEnabled=false` by default; retention is operator-set with a guarded minimum. Add a Collector only for measured tail-sampling need.

## Deploy Workflow

`.github/workflows/deploy-vps.yml` applies the [../skills/cicd.md](../skills/cicd.md) release contract to one SSH host:

1. `workflow_dispatch` only, inputs `operation` (`deploy` | `rollback`) and a full `commit_sha`; a concurrency group without `cancel-in-progress`, because a half-applied stack costs more than the run.
2. Entry job: the exact SHA has a successful required CI check and no failed checks.
3. A reusable image-build workflow (`workflow_call`) builds every image once and outputs digest refs.
4. Deploy job in a protected environment: SSH with pinned `known_hosts` (never `StrictHostKeyChecking=no`), reject any ref without `@sha256:`, write `images.env`, copy the compose file, Caddyfile, and `.env.example` (as `.env.base.example`), run the `.env.base` guards, regenerate `.env`, then `docker compose config -q`, `pull`, `up -d --wait`.
5. Verify observability health and one exported log and trace, then public `/healthz/ready`, one create/read/delete round trip, and each static UI's `app-config.json`.
6. Record a release manifest artifact with every digest and the previous manifest id. Rollback restores the previous manifest's digests and reruns steps 4-5 without a rebuild or migration; migrations stay forward-applied and backward compatible.

Ordinary CI renders the base file and base plus local override with `docker compose config -q` against a temporary `.env` built from the two committed templates (command: [execution-gates.md](execution-gates.md) section 5d - Quality Gates + Delivery). The full local-profile build and CRUD smoke run only on manual dispatch.

Single node is the ceiling: `up -d` recreates in place (seconds of downtime) and the node is the failure domain. The upgrade path is k3s, then a second node: `.env` becomes a Secret and `images.env` the manifest image tags.

## Proof

TaskFlow: `deploy/compose/` (all files above), `.github/workflows/deploy-vps.yml`, `.github/workflows/build-images.yml`, the compose steps in `.github/workflows/ci.yml`, and `tests/Test.Unit/Infrastructure/DeploymentWorkflowContractTests.cs`; decisions D-036, D-060, D-061, D-064 in its `.scaffold/DESIGN-DECISIONS.md`. Contract tests and Compose rendering are not evidence of a live host deploy.
