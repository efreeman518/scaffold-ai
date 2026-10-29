---
name: orchestrated-refactor
description: "Orchestrate a large refactor across files or sessions: scope slices, dispatch model-matched workers in owned worktrees, review, integrate and maintain a tracked handoff. Use for explicit delegated implementation; ordinary one-session changes use the normal branch/PR workflow."
---

# Orchestrated Refactor

Portable Claude Code skill: copy this folder into `<repo>/.claude/skills/` or `~/.claude/skills/`; never over a same-named skill another installer manages. It assumes git and Claude Code; every other tool is detected at run start and used only when present.

The main session only scopes, dispatches, reviews, commits Codex slices, integrates, merges and hands off; workers implement slices. The repo's own CLAUDE.md/AGENTS.md rules bind every worker; carry the essentials in its prompt.

`<root>` is the absolute primary checkout; `<run-id>` is `<slug>-<6 random hex>`, recorded once and reused. Manual worktrees: `<root>/.tmp/worktrees/<run-id>-<slice-id>`. `<state>`: `<root>/.tmp/orchestrated-refactor/<run-id>/<slice-id>/`; an isolated worker's state lives inside its worktree at `.tmp/orchestrated-refactor/<run-id>/<slice-id>/`. Record resolved paths. Slice ids are never `review`. Shell commands here are bash; in PowerShell use 7.4+ (older versions re-encode `>` output). If `.tmp/` is not ignored, append `.tmp/` to `$(git rev-parse --path-format=absolute --git-common-dir)/info/exclude` (local, covers every worktree, no commit); operational state is ignored, the run handoff is tracked.

## Qualify

Use only for refactors spanning many files/projects or sessions, or explicit delegated implementation. Work that fits one session uses the normal workflow.

## Phase 0 - Environment detect

Run once per session before any edit; record results in the handoff's Environment table when Phase 1 creates it. Later sections apply an optional tool only when it was detected here.

| Check | Command / marker | Used for |
| --- | --- | --- |
| Codex | `codex --version`, `codex login status` | Cross-family review lens and optional workers |
| RTK | `rtk --version`; an `rtk` PreToolUse hook in `~/.claude/settings.json` or `.claude/settings*.json` | Worker TOOLING line |
| Graphify | `graphify-out/graph.json` exists and `graphify` on PATH; may be stale, so confirm graph answers against the code | One scoping query |
| GitHub CLI | `gh auth status` | PR creation, CI status |
| Default branch | `git symbolic-ref --short refs/remotes/origin/HEAD` (strip `origin/`); if unset, `gh repo view --json defaultBranchRef -q .defaultBranchRef.name` or `git remote set-head origin --auto` and retry | Worktree base, PR target |
| MCP servers | `claude mcp list` (starts configured servers, including repo-defined ones; run only in a repo you trust) | Tooling line per slice |
| Toolchain | SDK pins, lockfiles, package engines, test runners, Compose files | Slice GATE commands |
| Platform | OS and shell | Worktree serialization, command syntax |

Report required but absent tools with the exact install command and what they unblock. Install nothing and change no global config without the user's yes.

## Phase 1 - Scope (orchestrator)

1. If Graphify was detected, query it once for the affected area; otherwise use targeted search.
2. Slice by explicit paths, spec and runnable finish line, leaving context reserve for tool output and edits. Each slice owns a branch; serialize dependencies and parallelize independent work. Split anything that needs the reserve to fit.
3. At open behavior choices, prefer entity/target-scoped configuration or data policy when it needs no significant redesign; record the policy shape in SCOPE. Where an `engineering-criteria` skill or copy is available, carry the sections a slice touches into its SCOPE and DONE: Tests for any logic change; Scale for data access, outbound calls, background work or shared state; Documentation for public API; Operations for logging, retention or deploy scripts.
4. Create the tracked handoff (repo convention, else `docs/plans/<slug>-refactor.md`): run id, goal, decisions, Environment table, next action, active count, FIFO queue and slice table. Each row records scope, weight, family/model/substitutions, status, branch/PR, worktree, worker/thread id and state path.

## Model assignment

Routing as of 2026-10; re-check vendor docs and coding benchmarks when a new model ships. Missing evidence is not endorsement.

| Model | Route here | Never route here |
| --- | --- | --- |
| haiku | Extraction, inventory/verification sweeps and doc-only work with explicit paths and cheaply checked results | Coding or large-input recall |
| sonnet | Clear-spec implementation, mechanical multi-file changes, tests with a runnable check; precision-first review | Unmeasured recall-first, long-horizon or toolchain work |
| opus | Hard cross-file/architecture/long-horizon coding; build/dependency/toolchain work; recall-first review | - |
| fable | Reasoning escalation after opus fails; security review | Build, dependency, packaging, toolchain; exploits or attack tooling |
| codex (if detected) | Fat independent coding/test slices with paths, spec and runnable check; cross-family review | Small/correction-heavy slices, or context that cannot be carried in the prompt |
| main session | Scope, dispatch, review, Codex slice commits, integration, merge, handoff | Slice implementation |

Pass family aliases (`haiku`, `sonnet`, `opus`, `fable`), never dated model ids or model-default env overrides. Record the model that actually served each slice. Review never uses a model banned for the subject.

Availability fallback: fable -> opus; opus -> sonnet with a smaller scope; haiku -> sonnet; sonnet -> opus. Record substitutions. Never cross a subject ban; if none is eligible, ask.

## Recommended settings

| Setting | Value |
| --- | --- |
| Orchestrator | opus, `/effort high`; consider a larger autocompact window for long runs and record it in the handoff |
| Workers | Inherit effort unless overridden; use per-call `effort: "high"` when the session runs at xhigh or max and announce it |
| Codex | Newest listed `gpt-<version>-sol` from `codex debug models` (highest version with `visibility: list`) for workers and review, resolved before every worker launch and review lens; a resume keeps its session's model (if no sol model is listed, use the strongest listed non-astra model and record the substitution); explicit `-m` on exec, explicit `-c model_reasoning_effort=<level>` and `-c model_auto_compact_token_limit=230000 -c model_auto_compact_token_limit_scope=total` on every exec/resume (keeps input under the 272K price band). Never `astra` or `ultra` |

## Delegation mechanics

Implementation: `Agent`, `subagent_type: general-purpose`, family `model`, `isolation: "worktree"`, background by default. Search sweeps may use Explore without isolation.

Isolated agents cannot write outside their worktree. When a slice needs that (or the shell hook refuses isolated git), use a non-isolated agent restricted by prompt to a manual worktree. Run `git fetch origin` first, then `git worktree add "<root>/.tmp/worktrees/<run-id>-<slice-id>" -b <type>/<run-id>-<slice-id> origin/<default-branch>`, where `<type>` is `feature`, `fix`, `chore` or `docs`.

On Windows serialize worktree creation, including harness-managed spawns (at most one isolation spawn per message). Before dispatch create manual `<state>` or pass the isolated worker a state path relative to its worktree.

Codex worker (only if detected and logged in): create the manual worktree and `<state>`, resolve the model (Recommended settings), then run in background from bash (every Codex form here; PowerShell 7.3+: pipe `@() |` instead of `< /dev/null` and read prompt files as below):

`codex exec --json -s workspace-write -m <model> -c model_reasoning_effort=<medium|high> -c model_auto_compact_token_limit=230000 -c model_auto_compact_token_limit_scope=total -C "<worktree>" --add-dir "<state>" --output-last-message "<state>/report.md" "$(cat "<state>/prompt.md")" < /dev/null > "<state>/log.jsonl"`

Write each prompt or correction to a file at an absolute path and pass its contents, never inline text: bash `"$(cat "<file>")"`, PowerShell 7.3+ `(Get-Content -Raw -LiteralPath "<file>")` (plain `cat` there joins lines with spaces). Double-quoted inline text is expanded by the shell (`$(...)` and backticks in bash, `$var` and `$(...)` in PowerShell), so quoted PR, issue or diff text could run commands. Quote every path.

Effort: medium for clear-spec slices, high for cross-file work. Record the thread id from the first `thread.started` event; never read the full JSONL. Correct from `<worktree>` (resume has no `-C` or `-s`): `codex exec resume --json -c sandbox_mode=workspace-write -c 'sandbox_workspace_write.writable_roots=["<state>"]' -c model_reasoning_effort=<level> -c model_auto_compact_token_limit=230000 -c model_auto_compact_token_limit_scope=total --output-last-message "<state>/report.md" <thread-id> "$(cat "<state>/correction.md")" < /dev/null >> "<state>/log.jsonl"`; the session keeps its model. Use forward slashes in `<state>` inside that TOML value. The sandbox cannot write a linked worktree's git metadata, so Codex workers do not commit: their BRANCH line says "leave changes uncommitted", and the orchestrator commits in `<worktree>` after reviewing the diff. The orchestrator commits (`git -C "<worktree>" add -A` after checking `git status` for stray files, then `git commit`) after each reviewed report, before each resume and before abandoning or respawning a stopped worker, so a lost worktree or replacement worker starts from that commit. This overrides any repo rule telling workers to commit. Network is off and writes outside `<worktree>`/`<state>` fail (package caches, SDK first-run state, browser installs): restore/prepare in `<worktree>` before dispatch, or keep such slices on Claude workers. The sandbox still reads anything the user can: trusted slices only.

## Worker prompt template

Adapt this into every prompt, including cold replacement workers:

```
SCOPE: <paths, change, explicit non-goals and chosen policy shape>
DONE: <runnable finish line>
TESTS: each test at the lowest level that fails when the behavior breaks (unit, integration against the real dependency through the repo's existing harness, API/contract, architecture; E2E only for primary journeys); no sleeps, real clocks, unrecorded seeds, real external services, shared mutable state or assertions that cannot fail where they would hide or fake a regression; a new test framework or library justifies itself as a dependency; a new expensive tier (E2E, load, mutation, suites over about 10 minutes) gets manual-dispatch CI only. Source: `engineering-criteria` Tests.
Complete the scope, nothing else. Report pre-existing concerns unless required for this change. Resolve ambiguity from wording and surrounding code; state assumptions. Follow repo test patterns; leave a runnable check for each non-trivial branch or parser.
TOOLING: <shell to use; "a hook rewrites commands through rtk, do not hand-prefix" | "no rtk">. Use native tools for files, targeted reads and surgical edits. MCP/CLIs for this slice: <list>.
GATE: narrowest behavior check. Report command/result, failures and anything that cannot run/why; a failed start or syntax-only substitute is not a pass. No extra review/hardening or reviewer subagents; the orchestrator schedules review.
BRANCH: only <worktree>/<branch>. Commit completed items/resumable checkpoints with plain messages; never merge, push to the default branch or touch another checkout.
STATE: <absolute state path, or isolated relative path resolved against worktree root>.
HANDOFF: create <state>/handoff.md before investigation; update after commits/blockers and before reporting: scope, branch/worktree/worker id, commits, decisions, verification, blockers and exact next action.
CODEX ONLY: replace the BRANCH line with "BRANCH: only <worktree>; leave changes uncommitted; the orchestrator commits." and in HANDOFF/REPORT read "commits" as "changed files".
REPORT: at most about 30 lines covering the whole slice: changes/why, files, actual checks, decisions, risks and last commit. Tool-backed claims only; mark unverified. No transcripts/full diffs.
```

## Feedback loop (orchestrator)

1. Read the completion report and the real diff, not just the self-report. Done means diff reviewed and narrow checks green; update the slice table immediately.
2. Send corrections to the same worker (SendMessage, or Codex resume) with a phase excerpt, handoff and diff. First confirm its worktree still exists; never resume into a removed worktree, since the worker may fall back into the primary checkout. Respawn only if unreachable or the worktree is gone.
3. Usage-limit or auth errors are not failures to retry: queue the slice for that family's reset or route it to another eligible family, and record it. Mechanical failure: one same-config retry with the primary error. Reasoning failure: re-dispatch one tier up (haiku -> sonnet -> opus -> fable unless banned; Codex medium -> high, then stop). At the top eligible model, stop with evidence. At most two escalations.
4. Open items without a blocker get a concrete continue, not a respawn. After two continues treat as reasoning failure. Background commands/agents still running mean not done.
5. For long slices schedule a fresh verifier against SCOPE. Read only relevant errors/bounded log tails on failure.

## Review path

Every lens gets fresh context, an immutable diff and read access, never the authoring conversation; it reports only. `<review>` = `<root>/.tmp/orchestrated-refactor/<run-id>/review/`. Inputs go in `<review>/in/`, reports in `<review>/out/review-<short-sha>-<lens>-<n>.md` (check absent first; never overwrite a live one). Freeze inputs with `git diff --output="<review>/in/<sha>.diff" <base>...<head>` (delta: `git diff --output="<review>/in/<sha>-delta.diff" <prev-head>..<head>`) and review from `git worktree add --detach "<root>/.tmp/worktrees/<run-id>-review-<short-sha>" <head>`; remove that checkout once its last reviewer ends.

Classes: risky = security, money, migration, infrastructure, dependency or agent-policy (instructions, skills, scripts). Logic-bearing = any other diff that changes a branch, loop, parser, state, cleanup or error path, or a value other code reads. Trivial = non-risky wording, comments, formatting or inert data. Exempt only prose-only docs or typo/comment fixes; record the exemption.

Severity: HIGH = data loss, security exposure or broken primary path in a realistic scenario; MEDIUM = wrong behavior in a realistic secondary scenario; LOW = edge cases, wording, docs, style. Every finding needs file:line and a concrete failure scenario.

Reviewer forms (run from the review checkout, in background, in parallel):
- Claude: `claude -p "$(cat "<prompt-file>")" --model opus --tools "Read,Grep,Glob" --strict-mcp-config --permission-mode default --add-dir "<review>/in" > "<report>"`; the prompt file ends "Put your complete report in your final message; you cannot write files." Only if the CLI is unavailable, use an `Agent` general-purpose reviewer (no isolation) alone, and compare `git rev-parse HEAD` and `git status --porcelain` of the checkouts before/after, since it is read-only only by prompt (writes to ignored paths go undetected).
- Codex (if detected): `codex exec --json -s read-only -m <model> -c model_reasoning_effort=<low|medium|high by size/risk> -c model_auto_compact_token_limit=230000 -c model_auto_compact_token_limit_scope=total -C "<checkout>" --output-last-message "<report>" "$(cat "<prompt-file>")" < /dev/null > "<report-stem>.jsonl"`. No `--add-dir` (it grants writes); name the diff path in the prompt.
- Success: exit 0 and a nonempty report ending in a coverage line (sweep) or verdict (intent, delta). On failure read the primary error and retry once; a usage-limit/auth error or second failure records the lens unavailable for that head, never clean.

Prompts:
- Intent: diff, PR intent and claims. Ask for bugs, security issues, missed edge cases, unintended changes, and whether the design holds (claims vs behavior, guards weakened, callers and scope missed). Ends with a verdict.
- Unanchored sweep (no intent): "Report-only line-by-line sweep of <diff> in <checkout>. Judge behavior against the code's own claims. Read every hunk and its dependencies; check A-J; search every removed/renamed identifier. One finding per line: [class] SEVERITY file:line - defect. Scenario: input/state -> wrong outcome. End with files covered/total." Checklist: A atomicity/races; B comments, docs or messages that describe behavior the code lacks; C parity between things that must match (prod/test hosts, config/defaults, write/read validation); D leftovers of removed identifiers; E swallowed or replaced exceptions, retries hiding failures; F null/empty/zero/overflow/culture/missing-config inputs; G disposal and unbounded growth; H vacuous tests, or new non-trivial logic with no check that would fail; I secrets, authz bypass, injection; J code no requirement needs.
- Delta: the delta diff, current full diff, checkout and the findings being fixed. Read every changed block and its callers; verify each fix and ask what it broke (cleanup paths, error handling, test isolation, defaults other callers reach, docs made untrue). Ends with a verdict.

Rounds:
- Round 1 before PR, in parallel on full `base...head`: opus intent plus opus unanchored sweep. Risky and logic-bearing diffs add a cross-family unanchored sweep from the family that did not author it: Codex on Claude-authored work if detected. On all-Codex authorship the Claude lenses are already cross-family; record that. Mixed authorship or the other family unavailable: record cross-family unavailable; same-family lenses gate.
- Verify and deduplicate every finding against the code, LOW/nits included; fix as one set or rebut with evidence (cite the type, caller or guard). Send fixes to the owning worker while its worktree exists, otherwise a new worker/branch from default.
- Round 1 fixes that change logic (LOW-only included) get one delta; fixes that are only code comments or human-facing docs do not (in agent instructions and skills, wording is logic). Another delta only after a confirmed HIGH/MEDIUM in the preceding delta. A fix set that replaces an approach gets its delta plus a full unanchored sweep, counted together as one delta. Cap: round 1 plus 2 deltas.
- Merge-head pass, outside the cap, at most once: if logic changed after round 1 on a risky PR, or on a logic-bearing PR where a cross-family lens raised a confirmed HIGH/MEDIUM, run one full unanchored sweep of the final head, cross-family when available. HIGH/MEDIUM from it gets a delta, which counts as extra if the cap is spent.
- No PR merges with an open HIGH or MEDIUM, even past the cap. Deltas past the cap count as extra; if a HIGH/MEDIUM is confirmed by the second extra delta or any later review, stop and report the open findings, fix history and suspected design cause to the user; merge waits for their decision. Every LOW and nit is fixed or explicitly rebutted.
- Record every round (head, lenses/models, findings, dispositions, unavailable lenses, fixes no reviewer read) in the PR body's review table and the tracked handoff.

## Integrate and merge

Only the orchestrator opens and merges PRs. Integrate slice branches onto one branch, run the full affected checks locally, and run Review path round 1 on the integrated diff (slice checks never substitute). Then `git push -u origin <branch>` and open one PR (via `gh` if detected) stating what, why, validation and the review table; later rounds follow on the PR. Before merge, audit the full `base...head`: intended scope only, no secrets or stray artifacts (`.tmp/`, test output, logs), no unintended dependency, lockfile, migration, CI workflow or infrastructure change; record the audit in the PR. Merge only with local checks passing, required CI green, review done/exempt with no open HIGH/MEDIUM, and the audit clean. Never push to the default branch directly or force-push shared branches. Confirm with the user before any merge that deploys, publishes, migrates data or changes credentials. If Graphify was detected and the change is material, offer a graph refresh as its own commit.

After a verified merge, preserve useful worker decisions in the tracked handoff. Stop the dev servers, watchers, test hosts, build servers and background shells this run started before removing its clean slice worktrees, remaining review checkouts, branches and state, so nothing holds a file handle. Leave every entry outside this run's slice table and review checkouts alone.

## Session handoff

Before ending, update active count, queue, slices, paths, decisions, checks, Environment table and exact next action. List every deliberately kept worktree/state/review input. Never unlock, remove or reuse another session's entries. A later session resumes from the tracked handoff alone; replacement workers use their own handoff and last commit.

## Token discipline

- Prefer a few complete slices to tiny spawns.
- Scope and retrieve better instead of raising tier/effort for long prompts.
- Read completion reports and diffs, never full transcripts or JSONL logs.

<!-- reconciled-with: claude/orchestrated-refactor/SKILL.md sha256:52bfd62d7b2fdd580d9136a4d3aa9db99db6ffbb1a9a4665cb3fe2b5a78ef82a -->
<!-- reconciled-with: common/engineering-criteria/SKILL.md sha256:dd087563c23eb5e9efa2a75dfacd85c92c74336c27a3d7ee9ec22a435e43211d -->
