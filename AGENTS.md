## AI Harness Entry

Single source of truth for the harness entry rules below. Agents that read
root `AGENTS.md` (Codex CLI, GitHub Copilot agent surfaces including VS Code,
Copilot CLI, and other agents using the same discovery convention) load this
file directly; Claude Code loads it through the `@AGENTS.md` import in
`CLAUDE.md`. `.github/copilot-instructions.md` remains a thin stub for older
Copilot clients and non-agent surfaces; the scoped scaffold agents live in
`.github/agents/`.

Do not auto-activate the scaffold workflow for ordinary work - normal coding,
review, docs, and maintenance use regular project context.

### Scaffold workflows

**Path rule:** in an installed app the payload lives under `.instructions/`, so the paths below resolve as written. In this maintenance repo there is no `.instructions/` directory - the same paths are root-relative (`START-AI.md`, `support/vertical-slice-checklist.md`, `ai/adopt-codebase.md`). If `.instructions/` is absent, you are in the maintenance repo: resolve root-relative and do not scaffold here.

- Add an entity/feature slice to an existing scaffolded app: load `.instructions/support/vertical-slice-checklist.md` (Claude Code: `/vertical-slice`).
- Full scaffold, brownfield adopt, or resuming an in-progress scaffold phase: load `.instructions/START-AI.md` and follow the phase router and one-phase-per-session rule (Claude Code: `/scaffold` / `/scaffold-adopt`; scoped commands live in `.claude/commands/`). Brownfield adoption loads `.instructions/ai/adopt-codebase.md` in place of Phase 1.
- Treat installed `.instructions/` files as read-only during scaffold work; record gaps in `.scaffold/INSTRUCTION-GAPS.md` (create `.scaffold/` at project root if absent).

### Agent scratch

Worktrees, session logs, and reports from agents and subagents live under the gitignored repo-root `.tmp/`: worktrees in `.tmp/worktrees/<slug>`, everything else in `.tmp/sessions/<id>/`. After the merge is verified, clean up with `.instructions/scripts/clean-tmp.py --apply`. Rules: `.instructions/support/multi-agent.md` section Agent Scratch.

### Context graph (graphify)

Conditional - active only when `graphify-out/graph.json` exists, inert otherwise.

- For codebase questions (architecture, where/what/how things relate), run `graphify query "<question>"` before grepping or reading raw files; use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for a concept.
- If `graphify-out/wiki/index.md` exists, use it for broad navigation.
- After material code or architecture changes only, refresh with `graphify update .` and regenerate the wiki when needed. Do not refresh graph artifacts for prose-only edits, action pins, formatting, or unrelated changes. Also delete stale dated snapshot folders under `graphify-out/` (see `.instructions/support/context-tooling.md`).
