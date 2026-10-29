---
description: "Add a new entity vertical slice to an existing C#/.NET solution. Use when: add entity, new entity, vertical slice, add feature, add resource, add endpoint, extend application, new table, new API endpoint."
argument-hint: "<Entity> <target project directory>"
disable-model-invocation: true
---

<!-- per-harness -->
# Add Vertical Slice

Add a new entity vertical slice (domain -> data -> application -> API -> tests) to an existing C#/.NET solution scaffolded with this instruction set.

**Entity and target:** $ARGUMENTS
<!-- /per-harness -->

If no entity or target was supplied, ask the developer for both before loading anything.

All instruction files live under `.instructions/` in the project root. All file references below are relative to that folder.

> **Maintenance-repo note:** This workflow is designed to run in a target app where the instruction set has been installed at `.instructions/`. If `.instructions/` is missing in the current working directory, you are likely inside the scaffold-ai maintenance repo itself - stop and confirm with the developer rather than trying to add a slice here.

## Bootstrap

1. Read `.instructions/support/vertical-slice-checklist.md` - it is the primary execution guide (fast-path section).
2. Read `.instructions/ai/placeholder-tokens.md` for naming conventions.
3. Load the templates listed in the checklist's "Load Set for Slice" section (under `.instructions/templates/`).
4. Confirm `scaffoldMode` and `testingProfile` from `.scaffold/resource-implementation.yaml`. If that file is absent, ask the developer for both rather than assuming defaults.

## Pre-Flight

Before generating any files:

- [ ] Verify the solution builds clean: `dotnet build`
- [ ] Locate existing `RegisterServices.cs`, both DbContext files, and `WebApplicationBuilderExtensions.cs`
- [ ] If adding to a domain with existing entities, review their patterns for consistency
- [ ] If this slice introduces a new domain term, role, event, custom action, or design decision, append it to `.scaffold/UBIQUITOUS-LANGUAGE.md` / `.scaffold/DESIGN-DECISIONS.md` and update `.scaffold/domain-specification.yaml` **before** generating code (see `.instructions/README.md` section Phase-1 Artifact Lifecycle)

## Execution Order

Follow the canonical Slice Execution Order in `.instructions/support/vertical-slice-checklist.md`. Do not duplicate or override it here.

## Validation Gate

See `.instructions/support/execution-gates.md` section Core Loop. Scope test filter to the new entity (`FullyQualifiedName~{Entity}`).

After the gate passes, optionally dispatch the read-only `scaffold-reviewer` agent over the slice's files and resolve its `blocker`/`major` findings before reporting.

## Several Entities

This workflow adds one entity per session. For several independent entities, run one `orchestrated-refactor` run per `.instructions/support/multi-agent.md`, one slice per entity. Before dispatch the orchestrator completes every entity's Pre-Flight, including its `.scaffold/*` updates, and commits them; workers never write `.scaffold/*`. Each worker follows this file's Execution Order and Constraints for its entity in its own worktree: in shared files (DI registration, endpoint mapping, DbContext, catalogs, parity and architecture tests, UI route or host registration) it adds only its own entity's lines. Its migration is run-local: generated for its gate's test containers and never applied to a shared or persistent database (no `dotnet ef database update`, migrator run or AppHost start against the dev database). It reports instruction gaps in its result instead of writing `.scaffold/INSTRUCTION-GAPS.md`. Its DONE is the Validation Gate above for its entity. The orchestrator integrates the slices one at a time, keeping every entity's lines where shared files conflict; drops the run-local migrations by deleting their files and restores each provider's model snapshot from the dispatch base (`git checkout <base> -- <snapshot>`, never `migrations remove`); they were never shared, so GR-13's never-drop rule does not cover them; generates one additive migration per `databaseProviders` entry from the integrated model and runs each provider's `has-pending-model-changes` check; appends the reported gaps; and reruns the Validation Gate for every entity. An entity that references another is not independent: it waits for a later run started from the integrated result.

## Constraints

- Do not modify the solution structure or shared infrastructure - only add entity-specific files and make the registration and mapping edits the checklist requires.
- Do not skip DI registration or endpoint mapping steps.
- Do not modify files under `.instructions/` - generate/edit production files in `src/`, test files in sibling `tests/`, and required solution/config changes at project root.
- Do not create new projects unless the entity requires a workload not yet in the solution.
- Follow existing code patterns in the project for consistency.

## Instruction Gaps

If any instruction behavior turned out missing, ambiguous, or wrong this session - a checklist step that did not cover the case, a template token with no definition, a gate that misfired - append a one-line entry to `.scaffold/INSTRUCTION-GAPS.md` (create `.scaffold/` at project root if absent) before reporting done.

## Output

Report which files were created, which wiring steps completed, and the gate result (`dotnet build` + `dotnet test`).
