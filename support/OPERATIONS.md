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

Every session works on its own branch, so a checkpoint is a plain commit.

- **Branch first, from a clean default branch.** Each phase, sub-phase and slice session starts on a clean checkout of the default branch: `git switch <default-branch>`, `git pull --ff-only` when it has an upstream, then `git switch -c <type>/<slug>` (`feature/`, `fix/`, `chore/`, `docs/`). Three cases differ:
  - **Greenfield.** In a folder that is not a repository yet, run `git init -b main`. While the default branch has no commits, commit the installed payload (with `.gitignore`) to it as its first commit - the one direct commit to the default branch - then branch.
  - **Resume.** When the last session stopped before its gate (`HANDOFF.md` still names its phase, with a blocker or a `WIP:` checkpoint), continue on its `sessionBranch`.
  - **Not ready.** When the checkout holds uncommitted work, or the previous session's branch (for a slice, a slice it depends on) is not merged yet - the developer confirms it, or `gh pr view <branch> --json state` shows `MERGED`; without a remote, merged locally - stop and ask the developer. Never stash, reset, clean or switch a checkout holding uncommitted work.
- **Commit at every gate**: each green gate (sub-phase gate, TDD GREEN step, slice validation gate) and the TDD RED test-only commit, with a plain-text message stating intent. A phase or sub-phase session updates `HANDOFF.md` (`sessionBranch` included) before its gate commit, so the commit carries it; a slice leaves `HANDOFF.md` alone and names its branch in its report. The branch belongs to the session, so a commit needs no approval.
- **Review, then a pull request.** A session that wrote code (Phase 4, 5a-5e, a slice) is reviewed before its PR: the ecosystem `independent-review` skill when installed, with `scaffold-reviewer` as its ground-rule lens; else `scaffold-reviewer` alone; else [prompt-catalog.md](prompt-catalog.md) section Fresh-Session Review. Fix or rebut every finding (none at HIGH or MEDIUM stays open), then rerun the gate. Phases 1-3 are reviewed by the developer at their gate. Then the developer's approval decides pushing (unattended: section Unattended Runs): push the branch and open one PR to the default branch, which the developer merges. Without approval, stop with the branch committed and give its push command in the final report. Without a remote, the approval merges it locally instead (`git switch <default-branch>`, then `git merge --ff-only <branch>`). A session branch whose PR shows `MERGED` may be deleted (`git branch -D`) without further approval.
- Destructive commands (`reset --hard`, `checkout .`, `clean`, `branch -D`, `push --force`) need the developer's explicit approval.

If a sub-phase fails after the fix-pass budget (and the diagnosis above):

- keep the last green commit as the checkpoint: commit the failing work as `WIP: <what fails>` on top of it, never into a green-gate commit,
- log the blocker in `HANDOFF.md`, naming the last green commit,
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
   - **Structural error** (wrong entity shape, missing relationship, bad inheritance): ask the developer before discarding work. Start a recovery branch from the last green checkpoint (`git switch -c <type>/<slug>-redo-<suffix> <checkpoint>`, a new 6-hex suffix), record it as `sessionBranch` in `HANDOFF.md` and open the PR from it, keeping the WIP branch for reference until that PR merges, then delete it with the developer's approval; or `git revert` the affected commits. Never `reset --hard` a branch that holds the work.
   - **Domain misunderstanding** (entity purpose is wrong): go back to Phase 1 output, clarify with the user, update `.scaffold/domain-specification.yaml`, `.scaffold/UBIQUITOUS-LANGUAGE.md`, and `.scaffold/DESIGN-DECISIONS.md`, then re-scaffold the slice from scratch.
5. **Document in HANDOFF.md:** Record what was rolled back and why, so the next session doesn't repeat the mistake.
6. **Re-enter at the corrected sub-phase** using the Phase 5 file table in `ai/SKILL.md`.

> **Rule:** Never patch-fix a structural error across 3+ files. It is faster and safer to rollback and re-scaffold than to chase cascading fixes.

## Unattended Runs

An issue-driven loop with no developer present (the ecosystem's autotriage feature loop, for one) may run `/vertical-slice` or a fan-out from an approved specification. The loop's own instructions win wherever they and a scaffold rule differ: they own the run's branch and worktree (Branch first does not apply), continuing a pushed branch, pushing, review lenses, asking, merging, deploying and the files it may not change. The scaffold's human touchpoints map onto it:

- **Stop and ask becomes the loop's question.** A missing required input, a blocking `[OPEN QUESTION]` (GR-10), an assumption the checklist does not allow, or an unavailable required model tier is posted where the loop asks (the linked issue), and the run stops. Never guess past it.
- **The approved specification stands in for the developer's phase-gate approval** to push the run's branch and open the PR. The developer's PR review is the gate; the loop never merges.
- **Gates the run cannot execute go to CI.** A gate that needs Docker, Testcontainers, Aspire or a database runs in the PR's CI; the PR body names each such gate and the CI job that runs it. A gate with no CI job is reported as not run, never as passed.
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
