# Scaffold-Proof Maintenance Audit

Audit window: 2026-09-15 through 2026-09-16, inclusive. Evidence repository: `efreeman518/scaffold-proof`, default branch `main`.

## Evidence Boundary

- Base: `d571931` ([PR 18](https://github.com/efreeman518/scaffold-proof/pull/18)), the last proof commit covered by the preceding scaffold promotion.
- [PR 19](https://github.com/efreeman518/scaffold-proof/pull/19), merge `72dac1a`: repaired environment-sensitive Foundry Local, scheduler recurrence, Aspire, and Playwright tests.
- [PR 20](https://github.com/efreeman518/scaffold-proof/pull/20), merge `cd61c28`: repaired the Blazor, React, Uno, and Aspire-backed browser suites and narrowed the DCP pre-launch retry.
- [PR 21](https://github.com/efreeman518/scaffold-proof/pull/21), merge `87c169e`: refreshed central packages and aligned EF runtime, design-time packages, tools, and the repo-local `dotnet-ef` manifest.
- [PR 22](https://github.com/efreeman518/scaffold-proof/pull/22), merge `0300dc3`: removed the fragile native local-AI runtime, refreshed the toolchain and container inventory, changed PostgreSQL persistence, and made Compose CRUD smoke concurrency-aware.
- [PR 23](https://github.com/efreeman518/scaffold-proof/pull/23), merge `b86d8b0`: made Android and browser UI tests runnable from Visual Studio through serialized run settings and test-owned loopback Appium lifecycle.

Proof-reported verification reached 902 fast tests, 213 component tests across the supported data lanes, Playwright 8/8, Android 3/3, NonAzure Aspire 6/6, eight application image builds, and a 12-service NonAzure Compose smoke. These are historical PR reports, not fresh scaffold verification. Azure Aspire remained blocked by an upstream SQL child-database health-ordering defect, live Azure AI required external configuration, and runnable iOS remained macOS-only. Those boundaries are not promoted as green runtime proof.

PR 22 merged after a Copilot `Changes recommended` review without a follow-up commit. Unresolved findings covered AI activation, PostgreSQL volume migration, mobile timeout ordering, executable Azure AI setup, and process-wide Uno reset messages. PR 22 remains useful evidence for unaffected patterns, but those five areas are defect evidence, not proof that the merged implementation is canonical.

## Selection Rule

Promote repeated or severe correctness, security, data-durability, test-trust, and operability lessons. Generalize the invariant and keep app-specific code, copied pins, and framework workarounds out of the baseline.

Classification: `P` promotes a scaffold default, `C` becomes conditional guidance, and `N` rejects a blanket prescription.

## Decisions

| Evidence | Class | Scaffold treatment |
|---|---|---|
| Azure Blob Data Protection selected without a key-file URL or named Blob endpoint/connection | P | Validate the selected persistence arm before host startup. Azure Blob accepts an explicit key-file URL or the lane's named Blob connection/endpoint; Redis requires its named connection. Keep Key Vault encryption independent and fail with the missing configuration key, never a misleading provider/runtime error. |
| Repeat-count assertion used `TimeProvider.System` | P | Inject `TimeProvider`; recurrence, expiry, lease, retry, and retention tests use a fixed instant whenever expected results depend on a time boundary. |
| DCP reported every resource `FailedToStart` before any process or log directory existed | C | Capture named-resource state first. A single fresh-host retry is allowed only for that exact pre-launch, no-exit-code state, with a comment naming the upstream condition and removal criterion. Application exits, unhealthy started resources, and assertion failures remain red. |
| Any Aspire timeout mapped to `Assert.Inconclusive` | N | A timeout alone cannot distinguish unavailable infrastructure from a broken app. Do not generalize the proof's broad timeout classification. |
| Browser tests raced component state and duplicated host startup | P | Reuse one host lifecycle per suite and wait for observable UI/network completion. Do not copy TaskFlow selectors or page order. |
| EF runtime/design/tools and repo-local `dotnet-ef` drifted during a package refresh | P | Keep the EF runtime family, `Microsoft.EntityFrameworkCore.Design`, `Microsoft.EntityFrameworkCore.Tools` when used, and repo-local `dotnet-ef` on one compatible patch. Restore tools, compile, audit vulnerabilities, and update adjacent version comments/docs in the same refresh. |
| Referenced `Testcontainers.*` packages moved together while unrelated feature packages had different valid versions | P | Refresh every referenced Testcontainers package as one family and compile each consuming test project. Do not impose same-version rules across unrelated families; update adjacent compatibility rationale instead. |
| Raw AI endpoint/deployment settings activated AppHost resources and live-test eligibility while runtime DI still selected `None` | P | Make explicit provider selection the sole activation source. Endpoint, deployment, and connection settings validate the selected provider; they never select it. AppHost, runtime DI, status, live-test eligibility, and remediation docs must use the same resolver and name the exact provider token, such as `AzureInference`. Do not copy PR 22's inconsistent implementation. |
| Native Foundry Local introduced RID, lifecycle, model-download, CI, and test-host fragility | N as default; C by explicit requirement | Default local AI to `None`; prefer externally provisioned Azure or OpenAI-compatible endpoints. Generate a native local-model runtime only when explicitly requested and leave a dedicated live provider proof, supported-RID statement, startup bound, and removal/upgrade owner. TaskFlow no longer proves this optional arm. |
| Floating and family-only container tags remained across Compose and emulator constants | P | Inventory every consumed build, runtime, emulator, and infrastructure image. Shared/deployed topology uses a reviewed tag plus digest; local-only topology still uses a concrete tag. Record architecture limits for single-platform digests. |
| PostgreSQL major upgrade changed the image's persistence root | P | Derive the mount from the selected image major and prove data survives container recreation. Before changing an existing named volume target, require a verified backup and migration or declare the volume disposable; a healthy empty replacement cluster is data loss, not success. PostgreSQL 18+ mounts `/var/lib/postgresql`; 17 and earlier mount `/var/lib/postgresql/data` unless `PGDATA` is deliberately overridden. See the [official image guidance](https://github.com/docker-library/docs/blob/master/postgres/README.md#pgdata). |
| Compose smoke deleted a concurrency-protected resource without its ETag | P | For resources with optimistic concurrency, smoke must read the strong ETag and send it in `If-Match` on update/delete. A create/read/delete script that bypasses the public concurrency contract is not representative proof. |
| Appium startup allowed 240 seconds while two methods timed out after 180 seconds | P when mobile is selected | Every outer method, assembly, and lane deadline must exceed its inner startup budget plus assertion and cleanup time. An outer timeout must not cancel the configured startup window first. |
| Visual Studio UI lanes needed explicit serialization and test-owned Appium startup | C | An optional IDE run-settings profile may set `MaxCpuCount=1`, enable mobile tests, build the default Android artifact when no explicit path is supplied, and own only a loopback Appium process. Ordinary CLI acceptance remains dependency-light unless that profile or runner is selected. PR 23 proves the profile through CLI `--settings`; it does not independently prove Visual Studio Test Explorer behavior. |
| Process-wide Uno reset messages reached stale editor models | P | Cross-model change notifications may be process-wide, but editor reset or navigation-scoped messages must carry entity/model correlation or unregister with route lifetime. Never broadcast an uncorrelated editor reset through a singleton messenger. |
| ReadyToRun added to selected request hosts | C | Keep per-host and measurement-backed. Do not copy it to migrators, Functions, UI hosts, or every container by policy. |

## Canonical Owners Updated

- Provider/runtime and data durability: `skills/security.md`, `skills/ai-integration.md`, `support/data-persistence-advanced.md`, and `support/scalability-and-hosting.md`.
- Dependency refresh discipline: `skills/package-dependencies.md` and `support/data-persistence-advanced.md`.
- Test determinism, Aspire diagnosis, browser/mobile execution: `skills/testing.md`, `skills/testing-quality.md`, `templates/test-templates-quality.md`, `support/troubleshooting.md`, and `templates/local-test-stack-template.md`.
- Deployment smoke: `skills/cicd.md`.
- Uno message scope: `skills/ui-uno-mvux.md`.
- Current reference evidence: `support/taskflow-proof-map.md`.
