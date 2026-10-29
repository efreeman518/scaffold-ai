# Multi-Agent Orchestration (optional)

Opt-in, harness-gated guidance for running parts of a phase across multiple agents. It changes **how** a single phase executes; it never changes the phase sequence or the human review gates.

> **Harness-gated, never required.** Spawning subagents and isolating their writes in git worktrees depends on the harness: Claude Code (`.claude/agents/`), GitHub Copilot agent surfaces (custom agents under `.github/agents/` run as subagents), and Codex CLI (multi-agent mode) can; generic assistants and older clients usually cannot. If yours cannot, ignore this file and run every phase sequentially - the workflow is designed to work that way first.

## Who owns the mechanics

This file owns only the scaffold rules: what may fan out, when, and which writes stay with the orchestrator. A fan-out runs as one `orchestrated-refactor` run, which owns dispatch, worker prompts, the feedback loop, review rounds and model assignment: use the installed skill when the harness has one, else read [../vendor/orchestrated-refactor/SKILL.md](../vendor/orchestrated-refactor/SKILL.md) in place (never install the vendored copy as a skill). That skill is written for Claude Code; another harness that can spawn subagents follows its scoping, worker prompt, feedback loop and review rules with its own spawn and model mechanism.

Workers carry the Tests, Scale and Operations sections of [../vendor/engineering-criteria/SKILL.md](../vendor/engineering-criteria/SKILL.md) that their slice touches - the vendored copy, so writer and `scaffold-reviewer` hold one bar; documentation follows the templates. Where a scaffold skill or template prescribes the pattern for the same concern, the scaffold file wins, and a conflict is reported as an instruction gap.

The rules below override the skill where they differ and bind every run as SCOPE constraints:

- **The developer's gates own git.** Worker branches start from the current branch's HEAD, not `origin/<default-branch>`, in the skill's manual worktrees under `.tmp/worktrees/`. The orchestrator integrates the slice branches into the current branch locally and stops there: commits follow [OPERATIONS.md](OPERATIONS.md) section Git Checkpoint Protocol, and nothing is pushed, opened as a PR or merged into the default branch without the developer's approval at the phase gate.
- **Its tracked handoff is a run section in `HANDOFF.md`**, written by the orchestrator only; the phase's gate evidence stays where [execution-gates.md](execution-gates.md) puts it.
- **One slice per independent work-item.** A host slice's DONE is its standalone gate from [execution-gates.md](execution-gates.md); tests that need the AppHost registration go green in the orchestrator's mesh gate. An entity slice's DONE is the one in the vertical-slice workflow's Several Entities section.
- **Shared writes stay with the orchestrator** (below), so every slice's SCOPE names its disjoint write paths and lists the frozen shared layer as read-only.
- **Shared-core writes run at the Reasoning tier** ([../README.md](../README.md#model-tier-by-phase)), and so does `scaffold-reviewer`, from a different model family than the writer when the harness offers one. The skill's availability fallback never lowers them: if that tier is unavailable, stop and ask the developer.

## What does not change

- **Phases stay strictly ordered and human-gated.** 1 -> 2 -> 3 -> 4 -> 5a..5e. Each phase ends in a developer review gate. Multi-agent work never crosses a phase boundary, because phase N consumes phase N-1's reviewed artifact.
- **State lives in files, not in an agent.** `HANDOFF.md` + `.scaffold/*` remain the single source of truth. There is no long-lived super-orchestrator holding state in context across phases. The "orchestrator" is just the current phase's main session, re-instantiated each phase from the files.
- **One agent owns all shared writes.** The orchestrator is the only writer of `HANDOFF.md`, `.scaffold/*`, and shared wiring (`RegisterServices`, the two `DbContext`s, `Directory.Packages.props`, the Aspire AppHost). Subagents return structured results; they do not edit the blackboard.

## The model: orchestrator + work-item workers + independent reviewer

The developer-facing agent is the orchestrator. It dispatches subagents, collects their results, performs the merge and the gate itself, then updates `HANDOFF.md` and closes. Subagents never talk to the developer.

Decompose work **by independent work-item (fan-out), not by role.**

- **Fan-out by work-item** = N workers, same job, different data (one per host, one per entity, one per slice). This is the parallelism that pays.
- **Role pipelines** (separate code agent / test agent / review agent) mostly do not fit here. The specialization is already the *phase + its load-set*, not a persona, and every role handoff pays a context re-brief tax. The one role split that helps is an **independent reviewer** (below).

| Role | Separate agent? | Why |
|---|---|---|
| Orchestrator | Yes - it is the existing phase session | Owns the developer relationship, gate authority, and every shared write |
| Worker (per host / entity / slice) | Yes, by work-item | Independent units; each does its *whole* slice |
| Reviewer / verifier | Yes - ships as `scaffold-reviewer` (`.github/agents/`, `.claude/agents/`) | Independence is the point: a fresh agent that did not write the code is a better adversary for ground-rule and architecture-test compliance. Read-only, so no write conflict. Its findings join the run's review round as an extra lens |
| Separate "test agent" vs "code agent" | No | The workflow is TDD ([../ai/tdd-protocol.md](../ai/tdd-protocol.md)). The same reasoning writes the failing test and makes it pass; splitting them breaks the red-green loop and the shared understanding of intent |

## The precondition: fan out only the leaves, after the shared core is frozen

You can only parallelize the **leaves** of the dependency graph at a given level. Any node the parallel workers share must be **complete and frozen first**, then treated as read-only. Before fanning out, the orchestrator's job is not "split into hosts" - it is "complete every shared dependency, freeze it, then dispatch the consumers that only read it."

The phase ordering already encodes the coarse barrier - the shared backend the UIs consume is built before the host layer:

- shared base types (`EntityBase`, `DbContextBase`, `DomainResult`, `IRepositoryBase`) - from packages/feed, fixed before Phase 4;
- contracts / DTOs / interfaces - Phase 4;
- domain model + repositories - Phase 5a;
- application services + the API endpoints UIs call - Phase 5b.

That is *why* Phase 5c (optional hosts) is the natural fan-out phase and 5a/5b are not.

There is also a **finer barrier inside the host layer**: anything shared *across* the target hosts must be built once before fan-out, or parallel workers will each invent and collide on it -

- a shared contracts assembly or generated/typed API client the UIs reference,
- a shared component / design-token / theme library (if admin and public share UI primitives),
- common client-side wiring (the HTTP/auth client setup pattern they reuse).

The orchestrator completes and freezes these, then dispatches the per-host workers read-only.

### Two consequences

- **Stub shared dependencies rather than block on them.** Identity/auth is Phase 5e - *after* 5c - so UIs are scaffolded against an auth stub and 5e wires the real provider. This is the external-dependency-mode pattern (GR-05/GR-06) applied to ordering: freeze a placeholder so consumers can fan out, fill it in later.
- **A fan-out unit is an independent deployable host, not a target or route of one.** Uno "browser and mobile" is multi-*targeting* within a single project (one head, many TFMs) - which is why Uno is already one dedicated session, not splittable. Admin-vs-public is a fan-out unit only if they are separate deployables; if they are role-gated routes in one app, they are not.

## Worked example: Phase 5c with three enabled hosts

1. Orchestrator (the phase session, talking to the developer) reads `HANDOFF.md` + `.scaffold/resource-implementation.yaml`, confirms the 5a/5b gates passed, and enumerates the enabled hosts.
2. It completes and freezes any artifact shared across those hosts (shared contracts/client, shared component lib, common client wiring).
3. It starts one `orchestrated-refactor` run with **one slice per host**: SCOPE is that host's disjoint files with the frozen shared layer read-only, DONE is the host's standalone gate (TDD where applicable).
4. Workers finish; the orchestrator integrates the slices, performs the single serialized Aspire AppHost registration pass itself, and runs the mesh gate (`dotnet run` + health) per [execution-gates.md](execution-gates.md).
5. The run's review round covers the integrated result, with `scaffold-reviewer` as an extra read-only lens for ground-rule / architecture-test compliance.
6. Orchestrator updates `hostGates` in `HANDOFF.md`, records gate evidence per [execution-gates.md](execution-gates.md) section Verification Evidence Rule, removes the merged worker worktrees per section Agent Scratch, and closes. The next phase is a fresh orchestrator.

## Pre-dispatch checklist

Before the orchestrator spawns any worker:

- [ ] The shared backend phases for this work (5a/5b) passed their gates.
- [ ] The developer approved committing, which a fan-out needs: worker branches start from commits and return their work as commits.
- [ ] Every artifact shared *across* the target work-items is complete, frozen and committed on the current branch, so every worker branch contains it (shared contracts/client, shared component/theme library, common wiring).
- [ ] Each fan-out unit is an independent deployable host (or a genuinely independent entity/slice), not a target or route within one host.
- [ ] Workers are constrained to disjoint write paths; all shared writes are reserved for the orchestrator's serialized merge step.
- [ ] `.tmp/` is gitignored, so worker worktrees and run state stay out of every diff.

## Agent Scratch

All agent and subagent scratch lives under the repo-root `.tmp/`, which the app `.gitignore` excludes (see [../skills/solution-structure.md](../skills/solution-structure.md)). Scratch never goes in sibling directories of the repo, the system temp folder, or the repo root. The one exception is a throwaway *app workspace* that must not inherit this repo's instruction files (the maintainer golden-path run): it lives in the system temp folder, its report under `.tmp/` records the path, and cleanup deletes both together.

| What | Where |
|---|---|
| Worker worktree | `.tmp/worktrees/<slug>` on its own branch from the up-to-date default branch: `git worktree add .tmp/worktrees/<slug> -b <type>/<slug> origin/<default-branch>` |
| `orchestrated-refactor` run state (slice handoffs, review inputs and reports) | `.tmp/orchestrated-refactor/<run-id>/`, removed by that run once its integration passes the phase gate; `clean-tmp.py` does not touch it, so an abandoned run's folder is removed by hand after its worktrees are gone |
| Worker logs, prompts, handoff notes, reports outside a run | `.tmp/sessions/<session-id>/` - outside every worktree, so they never enter a diff |
| Tool output with an owning project (`TestResults/`, `StrykerOutput/`, benchmark artifacts) | Under that project, not `.tmp/` - see [../skills/testing-quality.md](../skills/testing-quality.md) |

Cleanup runs after the merge is verified, never before:

1. Confirm the work merged: PR state `MERGED`, or the worktree `HEAD` is an ancestor of the default branch.
2. `git worktree remove .tmp/worktrees/<slug>` without `--force`. A worktree with uncommitted or untracked changes stays and is reported.
3. `git worktree prune`, then delete `.tmp/sessions/<session-id>/` once every worktree it served is gone.

[../scripts/clean-tmp.py](../scripts/clean-tmp.py) applies the same rules: run it bare for a dry-run report, then with `--apply`.

- A worktree carries its own `global.json`, `Directory.Build.props`, `Directory.Packages.props`, and `.editorconfig`, so .NET lookups stop at the worktree root. NuGet merges every `nuget.config` up the tree, so the main checkout's copy also applies - harmless while both are the same file.
- Harnesses that load instruction files from parent directories also see the main checkout's `AGENTS.md` / `CLAUDE.md`. When a work-item edits those files, tell the worker its worktree copy wins.

## When it is not worth it

For a `lite` / `api-only` app, or a slice with 2-3 entities and one host, the orchestration and merge overhead exceeds the wall-clock saving - run sequentially. One vertical slice always stays in its own session. Fan-out pays off at scale: many entities, several independent optional hosts, or a batch of independent vertical slices. The scaffold is a one-time, high-leverage effort; never trade output confidence for parallelism. Read-only review/research fan-out is the safe default that adds value without write-conflict risk at any size.
