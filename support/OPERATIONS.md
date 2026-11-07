# Operational Protocols

Single source of truth for the protocols an AI session needs at the boundaries of normal work - when something fails, when state changes, when an assumption breaks, when context limits matter.

The Phase 5 **Decision Table** at the top of [../ai/SKILL.md](../ai/SKILL.md) is the fast-lookup index. This file is the detail.

## Fail-Fast Protocol

After every build:

- **Code-generation issue** (usings/references/DI/wiring/packages): attempt one focused fix pass, rebuild.
- **Deterministic mechanical cascade** (rename ripple, namespace cascade, file-move fallout from a single root cause): one extra pass allowed *only when* the second pass purely propagates the same fix and introduces no new logic. If the second pass surfaces new failure modes, stop and diagnose (Rule below).
- **Missing package in `Directory.Packages.props`**: add at latest stable version, restore, rebuild.
- **Infrastructure issue** (feed auth, env vars, Docker, certs, SQL/cloud access): do not loop fixes. Document the blocker in `HANDOFF.md`, point the engineer to [execution-gates.md](execution-gates.md).

Rule: one fix pass for new errors; one extra pass allowed for mechanical propagation of the same root-cause fix. When the budget is spent on a code failure, diagnose first (the ecosystem `root-cause` skill when available, else by hand): read the primary error, prove the cause, fix it there, with a test that fails without the fix when the failure is behavioral. One diagnosis per failure: write the blocker when the cause is outside the session, stays unproven, or its fix does not turn the gate green. Never mask a failure (catch-and-ignore, sleeps, blanket reruns, skipped or weakened tests).

## Git Checkpoint Protocol

Phases 1-5 share one long-lived scaffold branch, `scaffold/<project>` (`ProjectName` in kebab case), whose `HANDOFF.md` holds the workflow's state. A slice works on its own `feature/<entity>` branch (`Entity` in kebab case; a batch: `feature/batch-<first entity in alphabetical order, kebab case>`). The protocol assumes a GitHub `origin` and a working `gh`. Without them, or wherever a step below does not resolve to one answer, stop and ask the developer.

- **Start every session the same way, before reading `HANDOFF.md`.** Never stash, reset, clean or switch a checkout holding uncommitted changes to tracked files, other than a freshly installed or upgraded payload: ask. Untracked files the session did not write (IDE or tool caches) do not block.
  1. **No commits yet** (`git rev-parse --verify HEAD` fails): `git init -b main` (an existing repository: `git symbolic-ref HEAD refs/heads/main`) and commit only the installed payload, the one direct commit to the default branch; a folder that already holds source code is committed by the developer first. With approval, `git push -u origin main`.
  2. **Find the live scaffold branch**: `python .instructions/scripts/find-scaffold-branch.py` classifies each `scaffold/*` name, local or on `origin`: an open PR, or none yet, means live; a newest PR `MERGED` with nothing after its head means switch off it if checked out and delete its local copy, if any, per the exemption below; anything else (`CLOSED`, two live names, no GitHub `origin`, a failed query): ask (exit 2, reason in its JSON). It stays live through `workflowStatus: complete` until its PR merges.
  3. **A phase session** (Phase 1-5, brownfield adoption, final validation) switches to the live branch and brings it up to date (`git pull --ff-only` when it is on `origin`; diverged: ask), then follows its `HANDOFF.md` as `START-AI.md` describes. With no live branch and `workflowStatus: complete` in the default branch's `HANDOFF.md`, the workflow is terminal: follow `START-AI.md` there. A branch with no `HANDOFF.md` yet is an interrupted Phase 1 or adoption, which restarts. With no live branch, only Phase 1 or adoption creates one: confirm `ProjectName` (a required input), switch to the default branch and `git pull --ff-only` when it is on `origin`, check a green `dotnet build` there for adoption, then `git switch -c scaffold/<project>` before writing any artifact, and set `scaffoldBranch` (name already taken: ask). Any other phase with no live branch asks; a workflow begun before this protocol may have the developer create the branch from its current HEAD. Every `HANDOFF.md` update keeps `scaffoldBranch` and `reviewBase`.
  4. **A slice session** switches to its `feature/` branch when it exists (an interrupted slice resumes there, `review pending` first). Otherwise, when a live scaffold branch exists and its `HANDOFF.md` says `workflowStatus: complete`, it asks the developer to merge that branch first; else it creates the slice branch from the live scaffold branch, brought up to date as in step 3, or with none live from the default branch after `git pull --ff-only`. A slice that needs another unmerged slice asks.
  5. **The payload** is committed first: a fresh install on the branch the session works on; an upgrade installed after switching to the live scaffold branch, or, with none live, on its own `chore/instructions-upgrade` branch and PR, merged before the session continues. Until Phase 4 writes `.gitignore`, commits stage only the paths the session wrote, tool-generated files the build needs included; never `git add -A`.
- **Commit at every gate**: each green gate (sub-phase gate, TDD GREEN step, slice validation gate) and the TDD RED test-only commit, with a plain-text message stating intent. A phase session updates `HANDOFF.md` and `.scaffold/INSTRUCTION-GAPS.md` before its gate commit, so the commit carries them; a slice leaves `HANDOFF.md` to its orchestrator, if any. A code phase (Phase 4, 5a-5e) whose `reviewBase` is empty, once any review carried over from the previous session is closed, records HEAD there before writing its own work, so an interrupted session's work stays in its review. The branch belongs to the workflow, so a commit needs no approval.
- **Review, then push.** A code session (a code phase or a slice) is reviewed after its gate commit over `reviewBase..HEAD` (a slice: `<branch it started from>...HEAD`), `.instructions/` excluded. Use the ecosystem `independent-review` skill when installed, with `scaffold-reviewer` as its ground-rule lens; else `scaffold-reviewer` alone, given that diff's file list (it runs no git); else [prompt-catalog.md](prompt-catalog.md) section Fresh-Session Review, which the developer runs in a new session: record `review pending` with the filled prompt in `HANDOFF.md` Blockers (a slice: in its report and as an empty commit `review pending: <prompt>` on its branch), commit and stop. The next session asks the developer for that report and fixes its findings before anything else. Fix or rebut every finding (none at HIGH or MEDIUM stays open), rerun the gate, and commit with the gate evidence updated and `reviewBase` cleared (a slice: a message starting `review done:`), a closing commit of its own when nothing needed fixing. Phases 1-3 are reviewed by the developer at their gate.
- **One pull request per branch.** With approval (unattended: section Unattended Runs) push the branch, and first the branch it started from (the default branch, or a slice's scaffold branch) when `origin` lacks it or is behind. The scaffold branch's first push opens its PR to the default branch as a draft (no draft PRs on the repository's plan: ask); each later phase pushes onto it, so the developer sees every phase as it lands. A slice PR targets the branch it started from. Without approval, give the push command in the final report.
- **Completion check** (final validation, before `workflowStatus: complete`): `HANDOFF.md` has no `review pending` blocker, no open PR targets the scaffold branch (`gh pr list --base <branch> --state open`), and every branch `git branch --no-merged <branch> --list 'feature/*'` lists is a merged PR's head (delete it per the exemption below) or one the developer confirms is unrelated. Then set `complete`, commit, push, mark the PR ready (`gh pr ready`) and wait for its CI checks, if any; a failure, or a fix the developer asks for on the PR, is made on the scaffold branch.
- **Discovered work** outside the session's scope goes to `HANDOFF.md` or `.scaffold/INSTRUCTION-GAPS.md`, except a security or data-exposure defect, which goes only to the developer (unattended: in the run's result to the loop), never into a tracked file, PR or issue.
- Destructive commands (`reset --hard`, `checkout .`, `clean`, `branch -D`, `push --force`) need the developer's explicit approval, except `git branch -d` (it refuses unmerged work) and deleting a branch whose PR shows `MERGED` and which holds nothing beyond it (`git log <headRefOid>..<branch>` is empty).

If a sub-phase fails after the fix-pass budget (and the diagnosis above):

- log the blocker in `HANDOFF.md`, naming the last green commit,
- keep that commit as the checkpoint: commit the failing work and `HANDOFF.md` as `WIP: <what fails>` on top of it, never into a green-gate commit,
- continue only with non-blocked work.

Mid-session checkpoint trigger: 15+ generated files **or** 3+ build/fix cycles. Update `HANDOFF.md`, then commit (a `WIP:` commit when not green) immediately - do not wait for the gate.

## Missing-Inputs Protocol

When domain inputs are absent or ambiguous:

- **Required** (`ProjectName`, `customNugetFeeds`, at least one entity): ask before proceeding.
- **Defaults** (modes/profiles/flags): use [../ai/resource-implementation-schema.md](../ai/resource-implementation-schema.md) **Canonical Defaults**; note assumptions inline.
- **Partial entity definitions**: scaffold what is defined; emit `// TODO` stubs for missing properties/rules.

### Phase 3 Pre-Flight: Custom NuGet Feeds

At Phase 3 start: ask for custom/private NuGet feed URLs and auth method. Update `nuget.config`, run `dotnet restore`, and require exit code 0 before Phase 4.

## Mid-Session Rollback Protocol

When the AI discovers a fundamental assumption error (wrong entity design, incorrect relationship, misunderstood domain rule) after multiple files have been generated:

1. **Stop generating.** Do not continue building on a flawed assumption.
2. **Assess scope:** Identify all files generated since the last git checkpoint that are affected by the error.
3. **Checkpoint recovery prep:** commit the current work so nothing is lost, then find the last green checkpoint. Never `git stash`: the stash stack is shared by every worktree and session of the repository.
   ```powershell
   git status  # stage only the files this session generated, never stray local config or secrets
   git add <generated paths>; git commit -m "WIP: <the flawed assumption>"
   git log --oneline -5  # find the last green checkpoint
   ```
4. **Decide recovery path:**
   - **Isolated error** (affects 1-2 files): fix the affected files on top of the WIP commit, rebuild and re-test; the next green commit becomes the checkpoint (the WIP commit stays in the branch history).
   - **Structural error** (wrong entity shape, missing relationship, bad inheritance): ask the developer before discarding work, then `git revert` the commits after the last green checkpoint, newest first (`-m 1` for a merge commit), so the branch keeps its name, its PR and the history of what was tried. Never `reset --hard` a branch that holds the work.
   - **Domain misunderstanding** (entity purpose is wrong): go back to Phase 1 output, clarify with the user, update `.scaffold/domain-specification.yaml`, `.scaffold/UBIQUITOUS-LANGUAGE.md`, and `.scaffold/DESIGN-DECISIONS.md`, then re-scaffold the slice from scratch.
5. **Document in HANDOFF.md:** Record what was rolled back and why, so the next session doesn't repeat the mistake.
6. **Re-enter at the corrected sub-phase** using the Phase 5 file table in `ai/SKILL.md`.

> **Rule:** Never patch-fix a structural error across 3+ files. It is faster and safer to rollback and re-scaffold than to chase cascading fixes.

## Unattended Runs

An issue-driven loop with no developer present (the ecosystem's autotriage feature loop, for one) may run `/vertical-slice` or a slice batch from an approved specification. The loop's own instructions win wherever they and a scaffold rule differ: they own the run's branch and worktree (Start every session does not apply), continuing a pushed branch, pushing, review lenses, asking, merging, deploying and the files it may not change. The scaffold's human touchpoints map onto it:

- **Stop and ask becomes the loop's question.** A missing required input, a blocking `[OPEN QUESTION]` (GR-10), an assumption the checklist does not allow, or an unavailable required model tier is posted where the loop asks (the linked issue), and the run stops. Never guess past it.
- **The approved specification stands in for the developer's phase-gate approval** to push the run's branch and open the PR. Merging follows the loop's instructions.
- **Gates the run cannot execute go to CI.** A gate that needs Docker, Testcontainers, Aspire or a database counts only when a CI job runs it on the PR; the PR body names each such gate and that job. A gate no PR job runs (a `workflow_dispatch`-only tier included) is reported as not run, never as passed.
- **Phase-1 artifact updates** the slice needs (GR-01) land in the same PR, before the code.
- **Instruction gaps** are appended to `.scaffold/INSTRUCTION-GAPS.md` as usual and listed in the PR body. `.instructions/` stays read-only (GR-07); the loop's gate also rejects a PR that changes it.

## Mixed-Store Slice Gate

For slices spanning SQL + Cosmos/Table/Blob + messaging:

- Explicit consistency boundary (authoritative store + projection store).
- Reconciliation handler/job with replay-safe correction logic.
- Drift detection check in post-generation verification.

Until all three are present, the slice is incomplete regardless of `dotnet build` / `dotnet test` status.

## Context Budgets (advisory)

Target <=30K tokens of instruction context per Phase 5 sub-phase, <=16K in compact-mode harnesses. On 200K+ context models with no harness constraint, treat as a focus signal - load the curated set in the **Phase 5 file table** in `ai/SKILL.md`, add files only when the current sub-phase clearly needs them. Lost-in-the-middle is real even at 200K, so loading every skill hurts output quality.
