# C# Language Rules

> **When to read:** any Phase 5 sub-phase or slice, before modelling a closed set of types (results, events, commands, states) or when the build reports a pattern-matching, collection-expression or contextual-keyword diagnostic.
> **Skip if:** the current task changes no C# code.

The scaffold targets the latest stable TFM and its default C# language version. This file owns how generated code uses the language features that version brings. `Result<T>` and `Error` belong to [ef-packages-reference.md](../support/ef-packages-reference.md); the domain-event hierarchy to [messaging.md](messaging.md) section Event Boundary Rule. The full language reference (every rule, trap and diagnostic) is the `csharp-15` agent skill packed in the `EF.Domain.Contracts` package: `~/.nuget/packages/ef.domain.contracts/<version>/csharp-15/SKILL.md`.

## Language Version

- No `<LangVersion>` anywhere: the TFM's default is the language version. Never `latest` or `preview`.
- Preview-only features (the memory-safety model: `unsafe(expr)`, `safe`, requires-unsafe members) stay off.
- Roslyn-based tooling that parses source (architecture tests, analyzers, scripting) references a `Microsoft.CodeAnalysis` package family that knows the SDK's language version and parses with `LanguageVersion.Latest`, so `union` and `closed` parse. Every `Microsoft.CodeAnalysis.*` package in the solution stays on one version.

## Closed Sets: `closed` or `union`

| Model | Use | Example |
|---|---|---|
| `closed record` base with `sealed` leaves | a family of types the app owns that share members | domain events, command sets, workflow states |
| `union` | alternatives that are unrelated or not the app's | `union PaymentSource(CardToken, BankAccountRef)` |
| `Result<T>` | every operation that can fail for a reason the caller handles | never declare another result type |

- A `closed` base's direct subtypes live in its assembly. Mark each leaf `sealed` (`closed` is not transitive) and make every direct subtype as accessible as the base: an `internal` subtype makes switches in other projects non-exhaustive.
- The subtype list is public contract: adding a subtype breaks every exhaustive switch over the base, which is the point. Never close an extension point other projects implement (handlers, plugins).
- A generated `union` is a struct that boxes value-type cases; its `default` holds null contents. Put data in case records, not in the union body.

## Exhaustive Switches

- A switch expression over a closed base, a union or `Result<T>` lists every case and has **no `_` or `var` arm**, so a new case fails the build (CS8509 under warnings-as-errors) at every consumer.
- A generated union switch gets a `null` arm wherever a default value can arrive (fields, arrays, deserialization): without it a default throws `SwitchExpressionException` at run time. `Result<T>` never holds null (its default holds an `Error`), so its switches have no `null` arm.
- A nullable input (`Event?`) needs a `null` arm. A switch that deliberately handles a subset uses an explicit base-type arm, not `_`.
- Switch on the union or base itself, never on `.Value` or `object`. On a union, type patterns test the contents; `{ }` always matches a struct union, so test for contents with `is not null`.
- Anything keyed by type (version maps, destinations, status codes, wire names) is an exhaustive switch over the closed base, not a dictionary or `if` chain.

## Collections, Loops, Locks

- Construct-then-fill with a capacity or comparer is a collection expression: `List<T> items = [with(capacity: n), .. source];`, `HashSet<string> keys = [with(StringComparer.OrdinalIgnoreCase), .. names];`. `with(...)` comes first; never on arrays or spans; the arguments do not pick overloads or infer type arguments (CS0121/CS0411), so assign to a typed local before passing it. Dictionaries keep their constructors.
- Nested loops exit with labeled `break`/`continue` (`rows: foreach (...) { ... continue rows; }`), one distinct label per loop, instead of flag variables or `goto`. Extract a method when that reads cleaner.
- A private lock object is `System.Threading.Lock`, unless it is used with `Monitor.Wait`/`Pulse`.
- One-off comparers are `EqualityComparer<T>.Create(...)`.
- Extension properties and indexers only where they read better than a method; never an extension indexer inside an EF Core `IQueryable` lambda (expression trees reject it).

## Contextual Keywords

`union`, `closed` and a leading `with(` in a collection expression are keywords: an identifier or method with that name is escaped with `@` (`@with(...)`, `@closed`). CS9370, CS9380 and CS1519 after a TFM move mean an unescaped one.

## Verification

- [ ] No `<LangVersion>` in any project or props file
- [ ] Every `closed` base has `sealed` leaves, all as accessible as the base
- [ ] No `_`/`var` arm in a switch over `Result<T>`, `Error`, a closed base or a union
- [ ] Type-keyed lookups over a closed set are exhaustive switches
- [ ] No `lock (object)` field; no flag variables exiting nested loops
