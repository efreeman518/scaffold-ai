# Placeholder Token Glossary

When generating code from templates and skill files, substitute these placeholder tokens with the actual values from the user's domain inputs. This glossary is the canonical reference for all tokens.

## Token Definitions

| Token | Source | Notes |
|-------|--------|-------|
| `{Project}` | `ProjectName` | Primary project and namespace prefix. Renders empty as a name prefix when `projectNamePrefix: none` (see Derivation Rule 8). |
| `{ProjectName}` | `ProjectName` | Markdown/document templates that should display the full project name. Always the literal `ProjectName`, never collapsed. Prefer `{Project}` for code templates. |
| `{Org}` | `OrganizationName` | Optional org prefix. If present (and `projectNamePrefix: solution-name`), full namespace becomes `{Org}.{Project}`. Not applied when `projectNamePrefix: none`. |
| `{App}` | Derived from `{Project}` | Application type prefix. Used in `{App}DbContextTrxn` and `{App}DbContextQuery`. Renders empty when `projectNamePrefix: none` (-> `DbContextTrxn` / `DbContextQuery`). |
| `{APP}` | `{App}` upper-cased, word separators removed | Environment-variable **name** prefix only, e.g. `{APP}_WASM_BASE_URL`, `{APP}_ASPIRE_RESOURCE_LOGGING`. See Derivation Rule 9. |
| `{app}` | `{App}` lower-cased, word separators removed | Resource/identifier name only - Aspire resource names (`"{app}db"`, `"{app}api"`), the owned SQL schema name, and the JS test-bridge global prefix (`__{app}TestState`). See Derivation Rule 9. |
| `{Host}` | Derived from `{Project}` or `{Org}.{Project}` | Host project prefix. Used in `{Host}.Api`, `{Host}.Gateway`, `{Host}.Scheduler`. Renders empty as a name prefix when `projectNamePrefix: none`. |
| `{Entity}` | Entity `name` | Entity class, file, and method name. |
| `{entity}` | Entity `name` with lower first character | Local variables, parameters, route values. |
| `{Entities}` | Pluralized entity name | Display and feature grouping name. |
| `{EntityPlural}` | Pluralized entity name | Alias of `{Entities}` used in CQRS feature namespaces (`{Project}.Application.Cqrs.Features.{EntityPlural}`). Same derivation as `{Entities}`. |
| `{entities}` | Lower-cased pluralized entity name | URL path or collection variable. |
| `{entity-route}` | Kebab-cased entity name | URL-safe route segment. |
| `{ChildEntity}` | Child entity `name` | Child entity class name. |
| `{childEntity}` | Child entity `name` with lower first character | Child variables and parameters. |
| `{ChildEntities}` | Pluralized child entity name | Default child collection property. Same derivation as `{Entities}` (Rule 5) - never `{ChildEntity}` followed by a literal `s`. |
| `{child-entities}` | Kebab-cased pluralized child entity name | Child sub-resource route segment. |
| `{Children}` | Child collection name | Use when the collection name differs from `{ChildEntities}`. |
| `{Feature}` | Defaults to `{Entities}` | Uno feature folder/service grouping. |
| `{Gateway}` | Same as `{Host}` | Compose gateway project name as `{Gateway}.Gateway`. |
| `{SolutionName}` | Derived from `{Org}.{Project}` or `{Project}` | `.slnx` file name and solution prefix. **Always** derived this way - never collapsed by `projectNamePrefix`, so the solution file stays `{Project}.slnx` even when project names are bare. |
| `{entra-tenant-id}` | `authProvider` config | Azure Entra tenant GUID. |
| `{api-client-id}` | `authProvider` config | API app registration client ID. |
| `{Agent}` | Agent `name` | Agent class/service prefix. |
| `{agent-route}` | Kebab-cased agent name | Agent endpoint route segment. |
| `{Tool}` | Tool or function name | AI function tool class name. |
| `{SearchIndex}` | Search config index name | Azure AI Search index name. The only index-name token; when the resource plan supplies no name it derives as `{entity}-index`. |
| `{ValueObject}` | Phase 1 language artifact | Value object term accepted in `.scaffold/UBIQUITOUS-LANGUAGE.md`. |
| `{Role}` | Phase 1 language artifact | Actor or authorization role term accepted in `.scaffold/UBIQUITOUS-LANGUAGE.md`. |
| `{State}` | Phase 1 language artifact | Lifecycle state term accepted in `.scaffold/UBIQUITOUS-LANGUAGE.md`. |
| `{PolicyName}` | Phase 1 language artifact | Domain policy/rule term accepted in `.scaffold/UBIQUITOUS-LANGUAGE.md`. |
| `{ExternalSystem}` | Phase 1 language artifact | External system term accepted in `.scaffold/UBIQUITOUS-LANGUAGE.md`. |

## Casing Conventions

> **Naming conflicts:** Avoid entity names that collide with C# framework types. Canonical list and safe alternatives: [domain-specification-schema.md - Entities section](domain-specification-schema.md#entities).

| Convention | Rule | Example |
|------------|------|---------|
| **PascalCase** | First letter of each word capitalized, no separators | `TodoItem`, `TeamMember` |
| **camelCase** | First letter lowercase, subsequent words capitalized | `todoItem`, `teamMember` |
| **kebab-case** | All lowercase, words separated by hyphens | `todo-item` |
| **flatcase** | All lowercase, word separators removed | `todoitem` - the `{app}` form |
| **FLATCASE** | All uppercase, word separators removed | `TODOITEM` - the `{APP}` form |
| **UPPER_SNAKE** | All uppercase, words separated by underscores | Environment-variable **names**. The name is built as `{APP}_SOME_SETTING`: the underscores belong to the variable name, and `{APP}` itself stays FLATCASE. See Derivation Rule 9 |

## Derivation Rules

1. **`{App}` = `{Project}`** - always identical. Use `{App}` when the context is the application namespace (e.g., `{App}DbContextTrxn`). Use `{Project}` when the context is the project/solution name.
2. **`{Host}`** - if `OrganizationName` is provided: `{Org}.{Project}`. Otherwise: `{Project}`.
3. **`{Gateway}`** - same as `{Host}`. Compose the gateway project name as `{Gateway}.Gateway`.
4. **`{Feature}`** - defaults to `{Entities}` (plural entity name) unless explicitly provided. Groups UI services and models into feature folders (e.g., `Services/TodoItems/`).
5. **Pluralization** - use standard English pluralization rules. `TodoItem` -> `TodoItems`, `Category` -> `Categories`, `Reminder` -> `Reminders`, `Address` -> `Addresses`, `Branch` -> `Branches`. This rule owns **every** plural token - `{Entities}`, `{EntityPlural}`, `{entities}`, `{ChildEntities}`, `{child-entities}`, `{Feature}`. Appending a literal `s` to `{Entity}` or `{ChildEntity}` is always wrong: it produces `Categorys`, `Addresss`, `Branchs`. Pick the plural once per entity and use the same spelling in the collection property, the `DbSet`, the route, and the feature folder.
6. **Route segments** - for URL paths, use the lowercase/kebab-case form. Multi-word entities: `TodoItem` -> `todo-item`, `TeamMember` -> `team-member`.
7. **Aspire project references** - In `AppHost/AppHost.cs`, `builder.AddProject<Projects.X>()` uses the C# identifier form of the `.csproj` path, where dots and hyphens become underscores. For example: project `TaskFlow.Api` -> `Projects.TaskFlow_Api`. This is automatic - just be aware when reading or writing AppHost code.
8. **`projectNamePrefix`** (Phase 1 `domain-specification.yaml`, default `solution-name`) - decides whether `{Project}`, `{Host}`, `{Gateway}`, and `{App}` carry the prefix when used as a **name prefix** (project name, folder, root namespace, or type-name prefix).
   - `solution-name` (default): every rule above applies unchanged. Layout matches the reference app - `{Project}.Domain.Model`, `{Host}.Api`, `{Gateway}.Gateway`, `{App}DbContextTrxn`.
   - `none`: as a name prefix, `{Project}.`, `{Host}.`, and `{Gateway}.` render as empty and `{App}` renders as empty. Projects, folders, and root namespaces become bare: `Domain.Model`, `Application.Services`, `Infrastructure.Data`, `Api`, `Bootstrapper`, `DbContextTrxn`, `DbContextQuery`. `OrganizationName` / `{Org}` is **not** applied. **Unaffected by `none`:** `{SolutionName}` (the `.slnx` is still `{Project}.slnx`, or `{Org}.{Project}.slnx` if an org was given), `{ProjectName}` in document templates, and `{APP}` / `{app}` (Rule 9). Caveat: bare top-level namespaces are generic and can collide when an assembly is consumed alongside other solutions - acceptable per the Phase 1 decision, but record it.
9. **`{APP}` and `{app}` are derived casings of `{App}`, not separate inputs.** Same value, three renderings, each with one job:
   - `{App}` - PascalCase, for C# type and namespace prefixes (`{App}DbContextTrxn`).
   - `{APP}` - upper-cased with word separators removed, for **environment-variable names only** (`{APP}_WASM_BASE_URL`, `{APP}_ASPIRE_RESOURCE_LOGGING`, `{APP}_MOBILE_TESTS_ENABLED`). The prefix is one unbroken run of capitals; the underscores that follow belong to the variable name.
   - `{app}` - lower-cased with word separators removed, for **runtime identifier names only**: Aspire resource names (`"{app}db"`, `"{app}api"`, `"{app}gateway"`), the app-owned SQL schema, and the browser test-bridge global/query prefix (`__{app}TestState`, `{app}TestMode`). Not kebab-case - `TaskFlow` gives `taskflow`, not `task-flow`.

   `{APP}` and `{app}` name a runtime resource rather than prefixing a generated type, so `projectNamePrefix: none` does **not** collapse them - an empty environment-variable prefix or an empty schema name is not a valid value. Both keep deriving from `{Project}`.

---

## Angle-Bracket Tokens

A few placeholders use `<...>` instead of `{...}` because they appear inside file paths, package ids, and container image tags rather than inside C# source, where `{...}` would collide with logging and interpolation (see *Disambiguating Tokens From Logging And Interpolation*). Angle brackets read like C# generics, so they are deliberately limited to this short list - do not invent new ones.

| Token | Source | Notes |
|---|---|---|
| `<packagePrefix>` | `packagePrefix` in `.scaffold/resource-implementation.yaml` | Shared base-contract package/project prefix. Names feed packages (`<packagePrefix>.Data.Contracts`) and local packable projects (`src/Packages/<packagePrefix>.<Layer>`). `EF` is the canonical example, not a default. |
| `<target-dotnet-major>` | Target .NET major from `global.json` / `TargetFramework` | Container base-image major. Substituted in **every** Dockerfile stage that names a .NET image - SDK and runtime alike - so the image major always tracks the TFM. The Azure Functions host major in a `dotnet-isolated` tag is a separate number and stays literal. |

`<packagePrefix>` is the only spelling. The older shorthand `<Prefix>` means the same token and is no longer used anywhere in the payload - do not reintroduce it.

---

## Disambiguating Tokens From Logging And Interpolation

`{Word}` is also the syntax of two C# constructs that must survive **verbatim** into generated code:

- **`ILogger` structured-message templates** - `logger.LogInformation("{Handler} processing {Event}", a, b)`. The placeholders name log properties and bind positionally to the trailing arguments.
- **String interpolation** - `$"Cannot transition from {Status} to {target}."`. The placeholders name C# identifiers in scope.

Substituting either one silently corrupts the generated code: the log loses its property names, or the interpolation stops compiling.

**Procedure - run it per string, not per file:**

1. **Substitute** every `{Word}` that names something the *generator* knows: a glossary token above, or a domain/resource-spec value (entity, child, event, property, project, expected count). These resolve to text written into the file at generation time.
2. **Leave** every remaining `{Word}` untouched. These resolve to values only the *running process* knows.
3. **Check, before writing the file:**
   - In a logging or telemetry message template, the number of `{...}` left after step 1 must equal the number of trailing arguments.
   - In a `$"..."` / `$@"..."` string, every `{...}` left after step 1 must name an identifier in scope at that point.
   - If either check fails, a placeholder was classified wrong. Fix it rather than emitting the file.

**Tie-breaker:** ask whether the value is known at generation time or only at run time. `{Entity}` resolves to a type name the generator writes -> token. `{Id}` resolves to a value the process supplies -> literal.

Both kinds can appear in one string; classify each placeholder on its own:

```csharp
// {EventName} is a token; {Handler}, {Event}, {Id} are log properties bound to the three trailing args.
logger.LogInformation("{Handler} processing {Event}: {Id}",
    nameof({EventName}Handler), nameof({EventName}), message.Id);


// Mixed inside one interpolated string: {ExpectedTableCount} and {app} are tokens,
// {tableCount} is an in-scope local.
$"Expected >= {ExpectedTableCount} tables in {app} schema, found {tableCount}"
```

Do not introduce a new scaffold token whose name is a common log-property name (`{Id}`, `{Name}`, `{Message}`, `{Status}`, `{Count}`, `{Path}`, `{Type}`, `{Action}`, `{User}`). If a template genuinely needs one, rename the token instead of relying on the reader to disambiguate.

---

## File Naming Conventions

Canonical file name patterns for generated artifacts. Use these consistently across all generated code.

| Artifact | Pattern |
|---|---|
| Entity | `{Entity}.cs` |
| EF config | `{Entity}Configuration.cs` |
| Write repo | `{Entity}RepositoryTrxn.cs` |
| Read repo | `{Entity}RepositoryQuery.cs` |
| Repo interface | `I{Entity}RepositoryTrxn.cs` / `I{Entity}RepositoryQuery.cs` |
| Updater | `{Entity}Updater.cs` |
| DTO | `{Entity}Dto.cs` |
| Search filter | `{Entity}SearchFilter.cs` |
| Mapper | `{Entity}Mapper.cs` |
| Service | `{Entity}Service.cs` |
| Service interface | `I{Entity}Service.cs` |
| Endpoint | `{Entity}Endpoints.cs` |
| Message handler | `{Event}Handler.cs` |
| Health check | `{Target}HealthCheck.cs` |
| Settings POCO | `{Entity}ServiceSettings.cs` |
| Structure validator | `{Entity}StructureValidator.cs` |
| Domain rules | `Rules/{RuleName}Rule.cs` |
| Dockerfile | `Dockerfile` |

---

## Canonical Event And Publisher Naming

Use these defaults when scaffolding event-driven flows:

1. Cross-process event payloads are integration contracts.
2. Place transport payload records in `Application.Contracts.Events`.
3. Use `IIntegrationEventPublisher` as the publish abstraction for external buses.
4. Name publisher implementations by transport, for example `ServiceBusIntegrationEventPublisher` and `NoOpIntegrationEventPublisher`.
5. Reserve `Domain.*` events for aggregate-local invariants and in-process domain dispatch.
6. Do not name external publisher abstractions as `IDomainEventPublisher`.

Default naming patterns:

| Artifact | Pattern |
|---|---|
| Integration event contract | `{Entity}{Action}Event` (in `Application.Contracts.Events`) |
| Integration publisher interface | `IIntegrationEventPublisher` |
| Service Bus publisher | `ServiceBusIntegrationEventPublisher` |
| No-op publisher | `NoOpIntegrationEventPublisher` |
