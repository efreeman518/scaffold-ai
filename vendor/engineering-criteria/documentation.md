# Documentation

Part of `engineering-criteria`: its Principles (`SKILL.md`) apply to everything here.

Code is documented for humans and AI agents alike; gaps are defects, not style. This covers product code; generated code and test projects are out of scope.

- Every class (or the language's equivalent type) and every public or protected member carries API doc comments in the language's standard form (XML docs in C#, JSDoc/TSDoc, docstrings, KDoc and the like): a summary of purpose and behavior, every parameter, the return value, and exceptions callers must handle. In C#, include `<param>` for each parameter, `<returns>`, `<exception>` where thrown, and `<typeparam>` for generics. Private members are documented as needed, where intent or a non-obvious constraint is not clear from the name. Docs state contract and intent, not a restatement of the signature.
- Missing docs are aggregated per project or module (count, sample locations, and the path list), never one per member.
- Every change that adds or changes public API documents it in the same change.
- Where the toolchain can enforce part of it (for example .NET `GenerateDocumentationFile` with missing-doc warnings as errors, which covers visible members only, or the linter's doc rule), a change whose scope is closing a project's doc gaps turns that enforcement on once they are closed, never before; review covers what it cannot enforce.
- A README at the repository root and per deployable project or package: purpose, architecture in brief, how to build, test, configure and run, and where to look next. Agent instruction files (AGENTS.md, CLAUDE.md) stay accurate where present.
- Docs that contradict the code are correctness defects, more urgent than missing docs.
