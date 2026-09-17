# AI Integration

> **When to read:** Phase 5b/5e, when a slice actually needs semantic retrieval, grounded Q&A, or bounded tool-driven automation - provider selection, `IChatClient` wiring, agents and function tools, search, or the AI trust boundary.
> **Skip if:** `includeAiServices: false`; the slice contains no inference; FlowEngine wiring with no `agent` node (see `flowengine.md`); pure domain, data, or UI work.

## Provider Activation Contract

**Provider selection is declarative, never inferred.** `AiServices:Provider` is the sole activation source. Supported values come from the selected lane's declared provider set, with `None` as the default. Endpoint, deployment, and connection-string values only validate the explicitly selected provider; they never activate Azure or OpenAI-compatible AI by presence. AppHost resources, child-host configuration, runtime DI, live-test eligibility, and operational remediation must use the same closed, lane-aware resolver.

Selection tokens and status wire values are intentionally distinct but have one fixed mapping:

| Selection | `/api/v1/ai/status` provider | Configured |
|---|---|---|
| `AzureInference` | `azure` | yes |
| `OpenAICompatible` | `openai-compatible` | yes |
| `None` | `none`, or `stub` only for the explicit Development demo switch | no |

Unknown or cross-lane selection fails before graph construction. A selected live provider missing required settings or failing startup also fails; it never degrades to `none` or `stub`.

The provider set is closed - Azure, OpenAI-compatible, or none. There is no on-device model arm: a machine with no cloud provider runs `None` (optionally with the Development dev-stub described below), never a native local runtime.

## Prerequisites

- [solution-structure.md](solution-structure.md)
- [bootstrapper.md](bootstrapper.md)
- [configuration-secrets.md](configuration-secrets.md)
- [identity-management.md](identity-management.md) (agents need auth context)
- [package-dependencies.md](package-dependencies.md)

### Local Run Preflight

Substrate checks - container runtime, Aspire CLI, `launchSettings.json`, AppHost user secrets, free ports, clean restore - are owned by [aspire.md](aspire.md) -> *Preflight (Before First Launch)*. Run those first; never debug application code against an unverified substrate.

The AI-specific launch settings layered on top of that preflight:

- **Offline / no provider (default):** `AiServices:Provider=None`. The app boots, registers no-op AI services, and `GET /api/v1/ai/status` reports `provider: none`, `isConfigured: false`.
- **Real Azure Foundry run:** explicitly select `AiServices:Provider=AzureInference` and supply its required endpoint/deployment configuration in AppHost user secrets or configuration. `aspire publish` preserves that explicit selection; raw endpoint presence never selects the provider.
- **OpenAI-compatible run:** select `AiServices:Provider=OpenAICompatible` and supply `AiServices:Endpoint`, `AiServices:ChatModel`, and a secret-only `AiServices:ApiKey`.

## Non-Negotiables

1. All AI services behind interfaces - testable, swappable.
2. Embedding generation is infrastructure, not domain.
3. Agent function tools delegate to existing `I{Entity}Service` application services - no domain logic in tools, and every invocation is authorized against the **caller's** identity, never the agent's. See *AI Trust Boundary*.
4. Search indexes are projections, not source of truth.
5. Use `DefaultAzureCredential` for Foundry/Search auth (no API keys in code). In production, prefer `ManagedIdentityCredential`.
6. Configuration-driven model selection (appsettings, not hardcoded deployment names).
7. Use **Microsoft Agent Framework** (`Microsoft.Agents.AI`) - the successor to Semantic Kernel and AutoGen. Do not scaffold with Semantic Kernel or AutoGen packages.
8. Scope each `AgentSession` by tenant, user, and conversation; never share across any boundary. **Why:** A session carries conversation and tool state, so reuse can expose prior-user context or interleave concurrent turns. Therefore session storage and lookup keys include all three dimensions.
9. System prompts live in files, not inline string literals spread through services.
10. **Read the DTO/response source before writing property access against it (GR-18).** The AI surface hits this often - assuming a property such as `snapshot.PreferredLanguage` that the type does not expose. `read_file` the DTO before generating tool wrappers or snapshot records.
11. **Read the target class constructor before injecting new dependencies into generated agents or tool classes (GR-18).** Generated constructors drift from session notes; reading the actual signature first avoids the compile errors called out in the rule.
12. **Scaffold mode is the default.** AI Search is `deployment-only` (no local emulator). `AiServices:Provider=None` registers no-op stubs, including a no-op `IChatClient`, so the app boots without cloud credentials. Generate Azure or OpenAI-compatible runtime wiring only for an explicitly selected provider; record any deployment-only dependency in `HANDOFF.md`.
13. **Function-tool schemas must be provider-compatible.** Avoid nullable optional tool parameters such as `string? status = null` when targeting Azure AI Inference. `AIFunctionFactory` can emit JSON Schema union types like `["string","null"]`, and some inference endpoints reject them. Prefer non-null optional strings with empty defaults (`string status = ""`) or explicit DTOs with provider-safe schema.
14. **AI provider contract explicit.** Provider selection comes only from `AiServices:Provider`; raw connection strings, endpoints, and deployments validate that selection but never change it. AppHost, runtime DI, status, live tests, and docs share one resolver. No-op is allowed for non-live AI tests and offline boot only. Live AI tests never green on `none` or `stub`.
15. **Model names resolve at scaffold time, not from an example.** Never copy a model or deployment name out of this file or a template into generated code - see *Model Selection: Latest, Not Copied*.
16. **Everything the model reads that is not your own system prompt is untrusted input** - retrieved documents, tool output, prior turns, and user text alike. See *AI Trust Boundary*.

---

## Decision Order

Escalate in this order and stop at the first rung that satisfies the requirement. This ladder is stated once; the rest of this file assumes it.

1. **Need retrieval over business data?** Start with Azure AI Search in keyword or semantic mode. Add embeddings, vector, or hybrid search only when search-quality testing shows lexical/semantic ranking is inadequate, and only after both behaviors are individually understood.
2. **Need the model to call internal business operations?** Add one `ChatClientAgent` with a few function tools that delegate to existing application services. Keep the first tool set small.
3. **Need a durable, branching, resumable, or approval-gated AI process?** Add `Microsoft.Agents.Workflows`. Do not introduce a workflow for a single linear task.
4. **Need hosted memory, centralized/portal-managed tool catalogs, or versioned agent definitions managed outside your code?** Use a server-hosted Foundry agent (Aspire `AddProject` + `AddPromptAgent`, or a pre-existing agent via the client SDK) after the code-hosted path is proven insufficient. Server-hosted agents always require Azure.

Two narrower escalations sit inside rung 2 and are added only on concrete need:

- **Middleware** - logging, redaction, or safety interception, once the core run path works. The tool-authorization and untrusted-content rules in *AI Trust Boundary* are not in this optional set; they ship with the first tool.
- **Agent-as-tool composition** - only when one agent owns a distinct bounded capability that should stay isolated from the outer agent.

Keep the first pass of any escalation narrow: one middleware policy, one subordinate agent, one workflow path.

**Do not scaffold empty AI folders.** Generate only the Search, Agents, and Workflows folders that are enabled.

## Model Selection: Latest, Not Copied

Model and deployment names age the same way package versions do, and a copied one silently pins a generated app to a superseded model generation. The package rule in [package-dependencies.md](package-dependencies.md) -> *Latest, Not Pinned* applies unchanged to model selection:

- Resolve the current default chat and embedding models from the Foundry model catalog at scaffold time and write the resolved names into `Directory.Packages.props`-adjacent config (`AiServices:AgentModelDeployment`, `AiServices:EmbeddingModelDeployment`) and the AppHost `AddDeployment(...)` call.
- Snippets in this file and in `../templates/` use the `<latest-stable>` placeholder (for example `FoundryModel.OpenAI.<latest-stable>`). Substitute the resolved member at generation time; never emit the placeholder into code, and never emit a name copied from a snippet.
- Do not record the resolved name as a version-history note. State the current selection only.
- A model below the current default is permitted only under the same four-part temporary-exception record as a package pin: failing behavior, why the older model resolves it, removal condition, validating test.

## Technology Choices

- **Foundry Models / Azure OpenAI client:** default model host for completions, embeddings, and tool-calling.
- **Azure AI Search:** default retrieval tier.
- **Microsoft Agent Framework:** default code-side agent SDK (`ChatClientAgent` over the injected `IChatClient`).
- **Foundry projects + server-hosted agents:** optional hosted agent backend - Aspire `AddProject` + `AddPromptAgent`, or a pre-existing portal/IaC agent consumed via `AIProjectClient.AsAIAgent(...)`. Azure-only.
- **Agent Framework Workflows:** optional explicit orchestration layer.

Useful primitives:
- `ChatClientAgent` (`Microsoft.Agents.AI`) for the default single-agent path
- `AIFunctionFactory.Create()` (`Microsoft.Extensions.AI`) for application-service tools
- `AsAIAgent()` (`OpenAI.Chat` extension in `Microsoft.Agents.AI.OpenAI` package) to create a `ChatClientAgent` from a `ChatClient`
- `AgentSession` for per-conversation state
- `Microsoft.Agents.Workflows` for explicit orchestration only when needed

---

## Packages

- Baseline for any AI capability (Aspire Foundry path):
    - `Aspire.Hosting.Foundry` (AppHost) - when no stable release exists, resolve the latest compatible prerelease and document the temporary exception
    - `Aspire.Azure.AI.Inference` (host project) - same prerelease rule; provides the `IChatClient`
    - `Microsoft.Extensions.AI` - `IChatClient`, `AIFunctionFactory`
    - `Microsoft.Agents.AI` - `ChatClientAgent`
    - `Azure.Identity` - managed identity for real Azure
- Add only when enabled:
    - `Azure.Search.Documents` + `Aspire.Hosting.Azure.Search` for search
    - `Azure.AI.OpenAI` only if a component needs the Azure OpenAI client directly (embeddings, a FlowEngine Azure-OpenAI connector)
    - `OpenAI` + `Microsoft.Extensions.AI.OpenAI` for `OpenAICompatible`; bind the configured endpoint, secret API key, and model through the OpenAI client and expose it as `IChatClient`
    - `Azure.AI.Projects` + `Microsoft.Agents.AI.Foundry` when consuming a Foundry **project** or **server-hosted/pre-existing agent** from app code (the `AIProjectClient.AsAIAgent(...)` path). If only a prerelease exists, use the latest compatible prerelease under the temporary-exception rule.
    - `Microsoft.Agents.Workflows` for workflow orchestration

Resolve packages at generation time and record concrete versions in `Directory.Packages.props`. Prefer latest stable. When a required package has no stable release, record the issue, prerelease reason, removal condition, and validating test beside the resolved prerelease.

---

## Project Structure

Generate only the folders used by the enabled feature set.

```
src/Infrastructure/{Project}.Infrastructure.AI/
|-- {Project}.Infrastructure.AI.csproj
|-- Search/                                   # Only if useSearch: true
|   |-- I{Project}SearchService.cs
|   |-- {Project}SearchService.cs
|   |-- {Entity}SearchIndexDefinition.cs
|   `-- {Entity}VectorizationHandler.cs
|-- Agents/                                   # Only if useAgents: true
|   |-- I{Agent}Agent.cs
|   |-- {Agent}AgentService.cs
|   |-- Tools/
|   |   `-- {Tool}Tool.cs
|   |-- Middleware/
|   `-- Prompts/
|-- Workflows/                                 # Only if workflow.enabled: true
|-- {Project}AiSettings.cs
`-- ServiceCollectionExtensions.cs
```

---

## Agent Patterns

### Simple Agent (ChatClientAgent)

This is the default agent pattern. Wrap an Azure OpenAI / Foundry model with a small number of function tools that delegate to existing application services.

Generate the code-hosted interface, request/response contracts, `ChatClientAgent` service, bounded application-service tools, prompt, scoped registration, and optional endpoint from [agent-template.md](../templates/agent-template.md) -> *Agent Interface*, *Default Agent Service*, *Prompt File*, *DI Registration*, and *API Endpoint*. That template owns the generated code shape, session creation, `UseTools` control, and cancellation propagation. Keep provider selection outside the agent: inject the `IChatClient` chosen by *DI Registration* and *Aspire Integration* below.

Escalation rungs and their order live in *Decision Order*; do not re-derive them here.

### Stable Prompt Prefix (Provider Prompt Caching)

A multi-turn agent re-sends its instructions and its whole tool catalog on every turn. Providers cache that prefix and bill cached input tokens at a large discount, but only on an **exact prefix match** - so the saving is a property of how the request is assembled, not a feature to switch on. Assemble every request in this order and the prefix is cacheable for free:

1. System instructions (from the prompt file).
2. Tool catalog, in a fixed order.
3. Long stable grounding context, if any (schema descriptions, policy text, a pinned retrieved document).
4. Conversation turns, oldest first.
5. The current user message.

Rules that keep the prefix byte-identical:

- **Build the `ChatClientAgent` once** in the agent service (instructions + tools), not per request. Rebuilding it per turn is the common way the prefix drifts.
- **Load the system prompt once** at startup and reuse the same string instance. Re-reading and re-formatting per request invites whitespace drift.
- **Keep per-request values out of the prefix.** A timestamp, correlation id, tenant banner, or user name interpolated into the system prompt invalidates the cache on every single turn. Put them in the last message instead.
- **Keep tool registration order deterministic** - a set or dictionary enumeration that reorders between processes silently halves the hit rate.
- **Do not interleave** retrieved content between the instructions and the tool catalog.

Prefix caching on Azure OpenAI and OpenAI models is automatic above a provider minimum prefix length; there is no API to call. Where the provider reports it, read the cached-input counters from `ChatResponse.Usage` and log them once per run so a regression in prefix stability is visible instead of merely expensive.

This is distinct from `ChatClientBuilder.UseDistributedCache(...)` (`Microsoft.Extensions.AI`), which caches whole responses keyed on the whole request. That helps deterministic repeat calls (seeded demo content, a fixed classification prompt); it does nothing for a multi-turn conversation, where no two requests are identical.

---

## Search Patterns

Rollout order (keyword or semantic -> vector -> hybrid, each gated on search-quality evidence) is rung 1 of *Decision Order*.

### Azure AI Search Shape

Generate the search interface/mode, projection and result models, `SearchClient` implementation, settings, and index setup from [ai-search-template.md](../templates/ai-search-template.md) -> *Search Service Interface*, *Search Document Model*, *Search Result Model*, *Default Search Service*, *Relevant Settings*, and *Index Setup*. That template owns the generated query-option shapes. Keep registration and optional configuration semantics in *DI Registration* and *Configuration (appsettings)* below. Do not generate vector fields, vector queries, or vector index configuration until search-quality evidence justifies embeddings.

### Vectorization Pipeline

#### On-Write (Domain Event Handler)

- Use an event handler only when search freshness matters enough to justify write-path work.
- Index only projection fields plus the vector field. Always keep the primary entity ID in the document.
- Call a dedicated embedding service abstraction from the handler or job. Do not generate embeddings in domain code.

#### Batch (Function App / Scheduler)

Use when vectorizing large existing datasets or when eventual consistency is acceptable. Prefer batch backfill first when introducing embeddings to an existing system.

---

## DI Registration

AI services use explicit registration - `None` -> no-op stubs, while every selected live provider validates and registers before the app boots.

The gate applies to every optional provider (AI, Graph, external identity): registration checks the **complete** credential set, not a single key, and constructs the credential object at registration time so misconfiguration fails at startup. Gating on one key (e.g. ClientId alone) wires the real client when the rest is missing, defeating the no-op fallback with a first-resolve exception deep in a request path.

The load-bearing lines of `AddAiServices` are below; the rest (options binding, the Search branch) follows the ordinary gated-registration and no-op patterns and is summarized after the block.

```csharp
// AddAiServices(this IServiceCollection services, IConfiguration config, IHostEnvironment environment)
// The selected model client is registered at the HOST before this extension runs.
var selectedProvider = AiProviderResolver.Resolve(config);
var hasChatClient = services.Any(d => d.ServiceType == typeof(IChatClient));
if (selectedProvider != AiProvider.None && !hasChatClient)
    throw new InvalidOperationException($"Selected AI provider '{selectedProvider}' did not register IChatClient.");

// Opt-in dev-stub: deterministic IChatClient for manual local runs/demos. Development-only, off by
// default, and only when Provider=None (see Configuration -> DevStubContent).
var devStub = selectedProvider == AiProvider.None
    && !hasChatClient && settings.DevStubContent && environment.IsDevelopment();

// Agent services follow a usable client; without one, the no-op keeps an offline boot working.
if (hasChatClient || devStub) services.AddScoped<ISupportTriageAgent, SupportTriageAgentService>();
else                          services.AddScoped<ISupportTriageAgent, NoOpSupportTriageAgent>();

if (devStub) services.AddSingleton<IChatClient, StubContentChatClient>();
else if (selectedProvider == AiProvider.None && !hasChatClient) services.AddSingleton<IChatClient, NoOpChatClient>();

// Live bootstrap branches already registered azure / openai-compatible. Only explicit None reaches here.
if (devStub) services.TryAddSingleton(new AiProviderInfo("stub"));
if (selectedProvider == AiProvider.None) services.TryAddSingleton(new AiProviderInfo("none"));
```

`AiSettings` binds with `AddOptions<AiSettings>().Bind(...).ValidateDataAnnotations().ValidateOnStart()`. Azure AI Search registers a `SearchClient` with `DefaultAzureCredential` when `UseSearch` and `SearchEndpoint` are both set, and a `NoOpSearchService` when `UseSearch` is set without an endpoint - Search is `deployment-only`, so there is no local alternative.

No-op stubs return empty results or a `Result.Failure("AI service not configured")` and log a warning; never-throw rule and safe-default table: [../templates/no-op-stub-template.md](../templates/no-op-stub-template.md). Scaffold `AiProviderInfo` and the `GET /api/v1/ai/status` endpoint **by default** whenever `includeAiServices: true` - it is the live-lane gate (see *Testing*) and an ops signal, and is easy to skip because the agents work without it.

**Runtime synthesized content is deliberately not a default.** The honest default with no provider wired is the no-op contract - empty results, `AiProviderInfo("none")`, `isConfigured: false` - so an offline boot never fabricates content that looks like model output. Fast test tiers do not need this default to be populated: they inject a deterministic fake `IChatClient` (see *Testing* -> *Provider Test Tiers*), so they already assert full response contracts with no model. The one gap that justifies more is the **manual** local run / demo (a real `dotnet run` / Aspire boot, where no fake is injected): with no provider it shows empty AI surfaces. The opt-in `AiServices:DevStubContent` flag (above) closes only that gap - Development-only, off by default, registering a small deterministic `StubContentChatClient` (the same deterministic-stand-in shape the test tiers use, promoted to an opt-in app registration, not a second generator). It surfaces as a distinct provider `stub` via `GET /api/v1/ai/status`, so a UI can banner it as synthesized and it is never mistaken for a model. Deterministic tests assert `stub` as `isConfigured: false`; optional live tests apply the eligibility matrix below and never treat synthesized content as a model. Leave it off unless a populated local/demo experience is actually wanted.

**Multi-host wiring.** When more than one host consumes AI (e.g. API and Functions), factor the closed provider selection into one shared path both hosts call - do not duplicate provider branches in each `Program.cs`. Register the AI consumer services (`AddAiServices` - agents, demos, and the explicit `None` contract) through the shared Bootstrapper as a feature-scoped `Register{Ai}Services` extension with per-host opt-in, per [bootstrapper.md](bootstrapper.md) (Conditional Per-Host Dependency Pattern); keep the host-builder client bootstrap (Azure or OpenAI-compatible) in one shared routine the opting-in hosts share. The inline `Program.cs` examples above are the single-host shorthand.

---

## Configuration (appsettings)

```json
{
  "AiServices": {
    "Provider": "None",
    "UseSearch": true,
    "UseAgents": false,
    "UseVectorSearch": false,
    "DevStubContent": false,
    "Endpoint": "",
    "ChatModel": "",
    "EmbeddingModel": "",
    "FoundryEndpoint": "https://ai-foundry-{resource}.services.ai.azure.com/",
    "AgentModelDeployment": "<resolved-chat-deployment>",
    "EmbeddingModelDeployment": "<resolved-embedding-deployment>",
    "SearchEndpoint": "https://{search-resource}.search.windows.net",
    "SearchIndexName": "products-index",

    "FoundryResourceName": "",
    "FoundryResourceGroup": "",
    "FoundryProjectEndpoint": "",
    "FoundryAgentName": ""
  }
}
```

Endpoint keys configure their axis after `AiServices:Provider` selects it. `Endpoint`, `ChatModel`, `EmbeddingModel`, and secret-only `ApiKey` configure `OpenAICompatible`. `FoundryEndpoint` configures the Azure inference path but does not select it. `FoundryResourceName` + `FoundryResourceGroup` target an **existing** Azure Foundry account (the `RunAsExisting`/`PublishAsExisting` parameters). `FoundryProjectEndpoint` + `FoundryAgentName` drive the **server-hosted/pre-existing agent** client path (`AIProjectClient.AsAIAgent(...)`). All are inactive until their provider/capability is explicitly selected. Supply `AiServices:ApiKey` only through user secrets or an environment/secret store, never tracked appsettings.

`AgentModelDeployment` and `EmbeddingModelDeployment` name Azure Foundry deployments and must match the deployment names the AppHost `AddDeployment(...)` calls create. Resolve both from the current model catalog at scaffold time per *Model Selection: Latest, Not Copied*; the placeholders above are not valid deployment names.

`DevStubContent` is the manual-local/demo **opt-in** (default `false`). When `true`, in a Development environment, and only when `AiServices:Provider=None`, the API registers a deterministic `StubContentChatClient` instead of the no-op client and records `AiProviderInfo("stub")` - so a real `dotnet run`/Aspire boot renders populated AI surfaces without a model. It has no effect outside Development, no effect for a selected live provider, and never greens a live smoke (`stub` is treated like `none`; see *DI Registration* and *Testing* -> *Provider Test Tiers*). Leave it `false` to keep the honest empty/`isConfigured: false` state.

> **Stub rule:** Generate all AI settings with `// TODO: [CONFIGURE]` comments. Use empty strings for endpoints - never hardcode real URLs, model names, or deployment names.

---

## Aspire Integration (Azure AI Foundry)

Only wire AI resources through Aspire if the solution already uses an AppHost. Do not introduce Aspire solely for AI.

Use the Foundry hosting integration (`Aspire.Hosting.Foundry`) - it provisions Azure AI Foundry on publish and connects to it in run mode. If this package or the Inference client has no stable release, resolve the latest compatible prerelease and apply the four-part temporary-exception record in `Directory.Packages.props`. The deployment resource name (`"chat"` below) is the connection name consumers bind to.

### Two axes: lifecycle x consumption

"Aspire Foundry" is two independent choices. Keeping them apart removes the confusion:

- **Axis 1 - where the Foundry resource comes from** (the `AddFoundry` lifecycle).
- **Axis 2 - what you consume** (raw model inference vs. a project + server-hosted agents).

**Axis 1 - lifecycle** (`FoundryResource : AzureProvisioningResource`, so the general `Aspire.Hosting.Azure` existing-resource APIs apply):

| Mode | AppHost call | Result | Azure? |
|---|---|---|---|
| Provision new | `AddFoundry("foundry").AddDeployment("chat", FoundryModel.OpenAI.<latest-stable>)` | Bicep creates the account + deploys the model on publish (and in run mode when `Azure:SubscriptionId/ResourceGroupPrefix/Location` provisioning secrets are set). | Yes (your sub) |
| Connect to existing | `AddFoundry("foundry").RunAsExisting(nameParam, rgParam)` (also `PublishAsExisting`, `AsExisting`) then `.AddDeployment("chat", ...)` | Points at an account you already provisioned; provisions nothing. The deployment name must match a model already deployed there. | Yes (existing) |
| `OpenAICompatible` selected | (no `AddFoundry`) | No `chat` resource is wired; the consuming host builds `IChatClient` from its own endpoint/key/model settings. | No |
| `None` selected | (no `AddFoundry`) | No `chat` resource is wired; app registers no-op AI services. | No |

**Axis 2 - consumption:** raw inference (`IChatClient` over a `FoundryDeploymentResource`, below) is the default and works with both Azure lifecycle modes. Projects + server-hosted agents are an escalation - see *Foundry Projects and Server-Hosted Agents*.

Generate one `AiProvider` enum and one `AiProviderResolver` in the shared hosting layer. The resolver reads `HostingLaneResolver.Resolve(configuration).AiServices`, parses the closed `AzureInference` / `OpenAICompatible` / `None` set, and enforces the active lane's allowlist. AppHost and every consuming host call that resolver; do not reimplement string or connection checks.

```csharp
// AppHost. Explicit provider selection is the only activation source.
IResourceBuilder<FoundryDeploymentResource>? chat = null;
var provider = AiProviderResolver.Resolve(builder.Configuration); // closed and lane-aware; unknown fails here

if (provider == AiProvider.AzureInference)
{
    // Validate the required endpoint/deployment for this arm before adding resources.
    // Substitute the model member resolved at scaffold time - never a copied name.
    chat = builder.AddFoundry("foundry").AddDeployment("chat", FoundryModel.OpenAI.<latest-stable>);

    // Connect to an EXISTING Azure Foundry account instead of provisioning a new one:
    // the deployment "chat" must already exist in that account. RunAsExisting binds in run
    // mode; PublishAsExisting binds the published graph. Parameters resolve from config/secrets.
    // var name = builder.AddParameter("foundry-name");
    // var rg = builder.AddParameter("foundry-rg");
    // chat = builder.AddFoundry("foundry").RunAsExisting(name, rg)
    //     .AddDeployment("chat", FoundryModel.OpenAI.<latest-stable>);
}
// OpenAICompatible is configured in the consuming host from its own settings. None wires no provider.

var api = builder.AddProject<Projects.MyApp_Api>("api")
    .WithEnvironment("AiServices__Provider", provider.ToString());

// Azure only: wire the deployment (ConnectionStrings:chat + CHAT_* env).
if (chat is not null)
    api = api.WithReference(chat);
```

Register the selected client at the **host** (`IHostApplicationBuilder`, not the `IServiceCollection` AI extension). Resolve the provider first, validate that arm's complete settings, and never use a connection string as the activation gate. The `connectionName` must equal the Azure deployment resource name; `OpenAICompatible` uses its endpoint/key/model settings:

```csharp
var provider = AiProviderResolver.Resolve(builder.Configuration);
switch (provider)
{
    case AiProvider.AzureInference:
        _ = builder.Configuration.GetConnectionString("chat")
            ?? throw new InvalidOperationException("AzureInference requires the Aspire-injected chat connection.");
        builder.AddAzureChatCompletionsClient("chat").AddChatClient();
        builder.Services.AddSingleton(new AiProviderInfo("azure"));
        break;
    case AiProvider.OpenAICompatible:
        builder.AddOpenAICompatibleChatClient(); // validates Endpoint, secret ApiKey, and ChatModel
        builder.Services.AddSingleton(new AiProviderInfo("openai-compatible"));
        break;
    case AiProvider.None:
        break; // AddAiServices supplies the explicit no-op/stub contract.
    default:
        throw new InvalidOperationException($"Unsupported AI provider '{provider}'.");
}
```

`AddOpenAICompatibleChatClient` binds `AiServices:Endpoint`, secret-only `AiServices:ApiKey`, and `AiServices:ChatModel` to the installed OpenAI-compatible client, validates all three on startup, and registers `IChatClient`. It may also bind `EmbeddingModel` when embeddings are enabled. Endpoint presence alone never calls this branch.

`AddAiServices` then uses `IChatClient` presence only after the closed selection switch completes. A selected live provider without a registered client is a startup error; only explicit `None` may receive the no-op or dev-stub fallbacks. The registration shape is in *DI Registration* above - do not re-derive it here, and in particular do not drop the dev-stub tier from it.

Build agents as a `ChatClientAgent` over the injected `IChatClient` (Microsoft Agent Framework), not over an `AzureOpenAIClient`. Keep an `AzureOpenAIClient` registration only if a component needs it directly (e.g. a FlowEngine Azure-OpenAI connector or embedding generation) - it is independent of the `IChatClient` chat/agent path.

```csharp
_agent = new ChatClientAgent(chatClient, instructions: systemPrompt, name: "Assistant", tools: [ /* AIFunctionFactory.Create(...) */ ]);
```

For embeddings or AI Search, add `builder.AddAzureSearch("search")` and reference it the same way; Search has no local emulator, so it stays `deployment-only` with a no-op stub.

Copy-paste configuration examples:

```powershell
# Explicit no-op for offline / fast iteration:
$env:AiServices__Provider = "None"; dotnet run --project src/Host/Aspire/AppHost

# Real Azure Foundry run
dotnet user-secrets set "AiServices:Provider" "AzureInference" --project src/Host/Aspire/AppHost
dotnet user-secrets set "AiServices:FoundryEndpoint" "https://<your-foundry-resource>.services.ai.azure.com/" --project src/Host/Aspire/AppHost
dotnet run --project src/Host/Aspire/AppHost
```

If the target Azure environment requires keyless managed-identity inference instead of the generated connection secret, update the host-side `AddAzureChatCompletionsClient("chat")` registration to use the required credential overload. Do that before classifying failures as model or prompt failures.

**A provider or config gate is not fully changed until the removed token is gone from comments and docs too.** After retiring a provider arm or an `AiServices` flag, grep the removed token across inline comments and XML doc comments, not just executable logic. `HANDOFF.md` records the high-level change; the recurring miss is a stale doc comment that still names a removed flag and now actively contradicts the code.

---

## Foundry Projects and Server-Hosted Agents

The default agent path is **code-hosted**: a `ChatClientAgent` running in your process over the injected `IChatClient` (above). It works with every Axis-1 lifecycle mode and boots offline as a no-op. Escalate to a **server-hosted** Foundry agent only for hosted memory, centralized/portal-managed tool catalogs, or versioned agent definitions managed outside your code. Server-hosted agents are **Azure-only**.

A Foundry **project** is the container that deployments, agents, connections, and tools live under.

### Aspire-modeled project + prompt agent

`Aspire.Hosting.Foundry` models the project and a declarative **prompt agent**. Tools are project-level resources, reusable across agents. The project reference injects `PROJ_URI` (the project endpoint, `https://<acct>.services.ai.azure.com/api/projects/<project>`), `PROJ_CONNECTIONSTRING`, and `PROJ_APPLICATIONINSIGHTSCONNECTIONSTRING`.

> **Prompt agents always deploy to Azure Foundry, even under `aspire run`** - local services talk to the cloud-provisioned agent. There is no offline mode. Keep this behind an explicit opt-in so a default run still boots without Azure.

```csharp
// AppHost - opt-in, Azure-only.
var foundry = builder.AddFoundry("foundry");
var project = foundry.AddProject("proj");
var chat = project.AddModelDeployment("chat", FoundryModel.OpenAI.<latest-stable>);

// Tools are project resources (reusable across agents).
var codeInterp = project.AddCodeInterpreterTool("code-interp");
var webSearch = project.AddWebSearchTool("web-search");
// var aiSearch = project.AddAISearchTool("search-tool").WithReference(search);

var agent = project.AddPromptAgent(chat, "assistant-agent",
        instructions: "You are an assistant for {Project}.")
    .WithTool(codeInterp)
    .WithTool(webSearch);

api.WithReference(agent);   // or .WithReference(project) to consume the project endpoint directly
```

### Pre-existing agents via the client SDK

When agents are created in the Foundry portal or by IaC, do not model them in Aspire. Connect to the existing project endpoint (Axis-1 existing mode, or `builder.AddConnectionString(...)`) and drive the agent with the Microsoft Agent Framework Foundry client. Add `Azure.AI.Projects` + `Microsoft.Agents.AI.Foundry` (prerelease) + `Azure.Identity`.

```csharp
using Azure.AI.Projects;
using Azure.Identity;
using Microsoft.Agents.AI;

var project = new AIProjectClient(new Uri(projectEndpoint), new DefaultAzureCredential());

// Code-first responses agent (no server-side agent resource is created):
AIAgent responsesAgent = project.AsAIAgent(
    model: agentModelDeployment, name: "Assistant", instructions: systemPrompt);

// Or bind to a pre-existing versioned agent created in the portal/IaC, by name:
var record = await project.AgentAdministrationClient.GetAgentAsync(agentName);
AIAgent foundryAgent = project.AsAIAgent(record);
```

Both results are standard `AIAgent` instances (sessions, tools, middleware, streaming) - the same surface the code-hosted `ChatClientAgent` exposes, so the application-facing `I{Agent}Agent` contract is unchanged. Use `DefaultAzureCredential` (prefer `ManagedIdentityCredential` in production); the project endpoint comes from `AiServices:FoundryProjectEndpoint` (or the Aspire-injected `PROJ_URI`).

---

## Inference Use-Case Taxonomy

When a slice needs inference, pick the pattern by concept and avoid building several that overlap:

- **Basic completion** - prompt to text via `IChatClient.GetResponseAsync`.
- **Streaming completion** - token UX via `IChatClient.GetStreamingResponseAsync` over Server-Sent Events.
- **Conversational tool-calling agent** - multi-turn `ChatClientAgent` with function tools that delegate to application services.
- **Structured-output decisioning** - constrain the response to a JSON schema and bind a typed result that drives a deterministic branch (classification/triage). See *Structured Output*.
- **Inline enrichment in a write** - one inference step inside an application command (e.g. draft fields before persisting).
- **Asynchronous event-driven inference** - reason in a background/event handler off a domain event, with the side effect on a different surface.
- **Read-only multi-tool reasoning** - an agent composes read-only tools to recommend, with no persistence.
- **Orchestrated workflow** - a durable workflow engine runs an agent node as one step of a branching, resumable process.

The first three are foundational; the rest embed inference inside application use cases. Start narrow and add a pattern only when the concept is genuinely new.

---

## Structured Output

**Schema-constrained decoding is the default whenever a model result feeds a typed branch.** Do not prompt for JSON and parse free text. `Microsoft.Extensions.AI` - the SDK this file mandates - carries the schema through `ChatOptions.ResponseFormat`, and providers that support constrained decoding then cannot emit prose, a fenced code block, or a trailing apology around the object.

Two equivalent entry points; prefer the first:

```csharp
// 1. Typed extension - derives the schema from TriageResult, sends it, and binds the response.
//    ChatResponse<T>.TryGetResult avoids the throwing .Result property.
var response = await chatClient.GetResponseAsync<TriageResult>(prompt, cancellationToken: ct);
if (!response.TryGetResult(out var triage))
    return Result<TriageDto>.Failure("Model did not return a usable triage result.");

// 2. Explicit response format - same constraint, when you own the ChatOptions (agent runs, tool
//    calls, a shared bounded options instance). Pass the app's JsonSerializerOptions so the schema's
//    property and enum names match the API's wire contract.
var options = new ChatOptions
{
    ResponseFormat = ChatResponseFormat.ForJsonSchema<TriageResult>(jsonSerializerOptions),
    // plus the deadline/iteration bounds from Agent Tests
};
```

Rules:

- **Model the result as a record with required, non-nullable members.** The schema is generated from the type, so an optional member is an invitation to omit it. Enums map to string values - keep the wire names aligned with the API's `JsonStringEnumConverter` shape ([api.md](api.md) -> *JSON Contract Across Hosts and Tests*).
- **The typed result is still input, not a decision.** Validate ranges, enum membership, and referenced ids against real data before acting. A schema constrains shape, never truth.
- **A binding failure is a `Result.Failure`, not an exception and not a retry loop.** Surface it through the same `Result<T>` path as any other service failure.
- **Not every provider honors the constraint.** An OpenAI-compatible endpoint may ignore `ResponseFormat` entirely; `Microsoft.Extensions.AI` says as much. Where the selected provider does not constrain, the call is in the unconstrained case below.

**The unconstrained case** - free-text summaries, streaming chat, a provider that ignores `ResponseFormat`, or a deliberately open-ended draft. Only here does the response need a parse guard: extract the first top-level JSON object, tolerate surrounding text, and fail closed on non-parseable output. Write that guard once as a shared helper, cover it with the parse tests in *Testing*, and do not copy it into every schema-constrained call site - there it is dead code that hides a real provider regression.

---

## AI Trust Boundary

A model chooses tool calls over content it did not author: user messages, retrieved search hits, prior-turn text, and the output of earlier tools. Those tools reach write-capable application services. **That is a trust boundary with the same standing as the gateway's forwarded-claims boundary** ([gateway.md](gateway.md) -> *Forwarded Claims Trust Boundary*), and it is wired with the first tool, not added later as middleware.

**Why:** Any text the model reads can carry instructions. Therefore nothing read at inference time may widen what the caller is allowed to do; this boundary establishes that.

1. **Only the system prompt is trusted.** Everything else in the context window - user input, retrieved documents, tool results, prior turns, file or email content - is untrusted data. Never concatenate retrieved content into the system prompt; pass it as a user-role message, delimited and labeled as retrieved data the model must not follow as instructions.
2. **Authorize every tool invocation against the caller's identity, not the agent's.** The tool wrapper resolves the same `IRequestContext` / tenant and role claims the equivalent HTTP endpoint would, and calls the same `I{Entity}Service` method with the same authorization. An agent that runs under a managed identity must never become an authorization bypass for a user who could not call the endpoint directly.
3. **Retrieval is tenant-scoped at the query, not in the prompt.** Search filters carry the caller's tenant; "only answer about tenant X" in the prompt is not a boundary. Cross-tenant leakage through a search index is the most likely failure here because search indexes are projections rebuilt outside the request path.
4. **Write-capable tools are opt-in and confirmed.** The default tool set is read-only. A tool that persists, sends, pays, or deletes is added only when the slice requires it, is gated by an explicit request flag (the `apply=false` / draft pattern in *Testing*), and returns a proposed change for confirmation rather than committing on the model's say-so. One-way actions (external send, payment, deletion) always require a human confirmation step.
5. **Tool parameters are validated as untrusted input.** The model supplies them; treat them exactly like a request body. Never accept a tool parameter that is a raw query, a file path, a URL to fetch, or a command. Bind to ids and enums the service re-resolves.
6. **Bound the blast radius per run.** Cap tool-call iterations per request, cap the number of write-adjacent calls at one per turn, and cancel on the per-request deadline in *Agent Tests*. An unbounded tool loop over a poisoned document is the practical exploit.
7. **Log the decision, not the content.** Record tool name, caller identity, tenant, and the resolved arguments' ids for every invocation, so a bad run is auditable. Keep prompt and document bodies out of logs - the redaction middleware in *Decision Order* is the place for that when content must be traced.

Required verification (mirrors the gateway boundary's shape):

- `RetrievedContentInstruction_DoesNotChangeToolAuthorization`: a retrieved document containing an instruction to call a privileged tool does not produce an authorized call.
- `AgentTool_UsesCallerIdentity_NotAgentIdentity`: a caller without the role for `I{Entity}Service.Delete` gets the same failure through the agent as through the endpoint.
- `AgentRetrieval_IsTenantScoped`: an agent run for tenant A never surfaces a tenant B document, with the tenant supplied only by the request context.
- `WriteCapableTool_RequiresExplicitOptIn`: with the apply/confirm flag absent or false, no persistence occurs and the response carries a proposal.
- `ToolLoop_IsBounded`: a response that keeps requesting tool calls terminates at the configured cap, red, rather than running to the method timeout.

---

## Testing

Cover the smallest useful surface first:

1. Search service returns expected fields and ordering for the selected search mode.
2. Agent tools call the intended application services and do not bypass business rules or the caller's authorization (*AI Trust Boundary* lists the required cases).
3. Prompt loading works from file-based system prompts.
4. Disabled AI features do not register or resolve their services.

### Deterministic agents for tests

When the app's primary workflow invokes an AI agent, the primary-journey E2E
([../templates/test-templates-e2e.md](../templates/test-templates-e2e.md) section Primary domain-journey E2E)
must run that agent deterministically and offline - no model call. Gate the live model behind a config
switch so a booted host can swap a scripted agent for the real one. A config switch (not just an injected
fake) is what makes this work where the test cannot reach the host's DI - the Aspire mesh and any
separately-launched host - and it is the simplest path for the journey test.

- Add `{App}:AiServices:UseScriptedAgent` (default false). When true, `AddAiServices` registers a scripted
  `IChatClient`/agent returning canned, deterministic responses (and a fixed tool-call sequence) instead of
  the live or no-op client.
- Set it in the E2E/journey host config (the `SqlApiFactory` config, or the Aspire AppHost testing branch,
  which also selects `AiServices:Provider=None`) so the journey is repeatable and needs no provider.
- It is a test mechanism, distinct from `AiServices:DevStubContent` (a manual demo aid). Like the stub and
  no-op, the scripted agent reports `isConfigured: false` on `GET /api/v1/ai/status`. Do not enable it in a
  `LiveAI` lane; deterministic booted-host tests assert that state directly. In-process unit/service/endpoint
  tests still inject a fake `IChatClient` directly (see Provider Test Tiers below) - the switch is for the
  booted-host deterministic tiers.

### Provider Test Tiers (Azure / OpenAI-compatible / no-op)

Keep the tiers distinct - the model provider must not leak into the fast tiers.

- **Application / service / endpoint tests use a fake `IChatClient`** (a small deterministic stand-in, or a Moq double) - never a real model. Cover with fakes: the response contract, schema-constrained binding (a well-formed object binds; a response missing a required member is a `Result.Failure`, not an exception), the no-write path (a triage/draft that must not persist), the write behavior (a valid response that does persist), and the trust-boundary cases listed in *AI Trust Boundary*. These live in `Test.Unit` / `Test.Endpoints`.
- **Parse-guard tests belong to the unconstrained path only.** Model JSON wrapped in extra text, or non-parseable output, exercises the shared parse helper from *Structured Output* - not every structured call site. Where the call sets `ChatOptions.ResponseFormat`, do not simulate prose-wrapped JSON as expected behavior: that is a provider regression, and covering it as normal hides the regression.
- **Provider selection stays deterministic.** Cover each explicit provider token, `None`, unknown-token failure, and selected-provider missing-config failure with fakes or direct registration tests. Also prove that raw endpoint/deployment/connection settings do not activate a provider while selection is `None`. Live-lane `Assert.Inconclusive` results never substitute for this coverage.
- **Cover explicit `None` behavior.** Assert that `AiServices:Provider=None` makes `AddAiServices` register the no-op `IChatClient` (and no-op search/agent) with `AiProviderInfo("none")`, that `GET /api/v1/ai/status` reports `provider: none`, and that each AI endpoint returns its `isConfigured: false` contract without persisting. A no-op path that is never asserted is untested.
- **Live model tests are smoke only.** The live smoke is HTTP-only and runs in the mesh tier (`Test.Aspire`); no test tier loads a native model runtime. It asserts response contracts (status, `isConfigured: true`, non-empty/typed fields), not exact model text.
- **One active-provider lane, not one lane per provider.** Smoke only the explicitly selected provider. Do not copy every app contract once for Azure and again for OpenAI-compatible. The active-provider smoke set is: chat, the tool-calling agent, one safe AI write-adjacent path (e.g. triage with `apply=false`, or a draft that may create), and one FlowEngine agent-workflow run. Reserve an `AzureFoundry` category for genuinely Azure-specific behavior (resource selection / provisioning), never for a second copy of a provider-neutral contract. Add a provider-specific copy only when the behavior actually differs by provider.
- **Do not change deterministic tests from stale IDE evidence.** Before changing fake-client, provider-selection, binding, or persistence assertions, require a fresh CLI reproduction: run the affected project from the current source/build, then repeat the exact failing filter. If the failure does not reproduce, refresh Test Explorer/build artifacts; do not loosen the deterministic contract.

### Optional Live-Provider Classification (canonical owner)

This is the explicit exception to the generic required Docker/AppHost failure rule in [testing.md](testing.md). Keep calls bounded; classification fixes the outcome, not the timeout.

| Checkpoint | Outcome |
|---|---|
| `{APP}_RUN_AZURE_FOUNDRY_TESTS=false` | `Assert.Inconclusive` immediately. This is a fast explicit opt-out, not a prerequisite when the optional provider is absent. |
| A live provider was explicitly selected but the shared resolver finds its required configuration absent | `Assert.Inconclusive` **before Aspire graph creation** only when this is an optional live lane. Do not boot the graph and infer absence later from status. Required deployment validation fails red. |
| Provider reports `isConfigured: true`, but bounded generation exceeds its per-request budget | `Assert.Inconclusive` - that is machine capacity, not a contract failure. Keep the bound and report the capacity overrun. Do not increase the timeout as the fix. |
| Provider was eligible, then AppHost/API/provider startup fails | Fail red with startup/resource diagnostics. |
| Expected provider differs from `/api/v1/ai/status`, or status/routing/HTTP/JSON/schema/contract assertions fail | Fail red. |

Live tests perform provider eligibility before Aspire creation: explicit false opt-out first, explicit provider selection plus required-configuration validation second, graph startup third. Do not start a graph merely to observe `none`/`stub` when no live provider was selected. After eligibility, fallback to `none`/`stub` is a configured-provider mismatch and fails.

The live lane must never report green without a real provider. The dev-stub provider remains a manual local/demo aid: if covered, assert deterministically that `stub` maps to `isConfigured: false`; never smoke synthesized content as model output.

Provider dispatch is a closed switch, not an availability fallback chain:

1. `AzureInference` -> validate Azure settings, then use Azure.
2. `OpenAICompatible` -> validate its endpoint/model settings, then use that provider.
3. `None` -> dev-stub only when explicitly enabled in Development, otherwise no-op.
4. Unknown token -> fail startup with the allowed values.

### Deciding the Live Lane

**The deterministic default is `AiServices:Provider=None`** on every API-booting tier: the in-memory `WebApplicationFactory` base (`CustomApiFactory` / `SqlApiFactory` config) and the Aspire AppHost testing branch. `Test.Aspire` is the one tier that may instead select a live provider before graph creation, and only for the optional live smoke - see [aspire.md](aspire.md) -> *Azure AI Foundry* for the AppHost side. Unit and endpoint tests use fake or no-op clients.

**Gate the live lane on `GET /api/v1/ai/status`, not on a connection string.** The endpoint reports the fixed mapping `azure` / `openai-compatible` / `none` (or explicit Development `stub`) from the provider resolved before registration, recorded once at startup. It must not call the model. Do not infer the provider by sniffing a connection string: the OpenAI-compatible path wires no Aspire `chat` connection. Scaffold it by default whenever AI is enabled.

**A self-contained provider-proof test owns its graph.** A test that claims to prove a specific provider/config path (Azure-only, OpenAI-compatible, no-op) constructs its own isolated graph instead of flipping env vars on a shared graph. AppHost env vars are read at graph-construction time and baked in once the graph starts, so a shared, lazily-started graph cannot re-flip them per test (see [test-templates-aspire.md](../templates/test-templates-aspire.md) section Aspire fixture non-negotiables). External opt-in env vars are fine for selecting which lane runs in CI; they are not a substitute for an isolated graph in a self-contained test.

```csharp
// At bootstrap, whichever path wires IChatClient also records the provider name (no model call);
// AddAiServices supplies the dev-stub and "none" fallbacks. See DI Registration + Aspire.
//   Azure host path:   services.AddSingleton(new AiProviderInfo("azure"));
//   OpenAI-compatible: services.AddSingleton(new AiProviderInfo("openai-compatible"));
//   dev-stub (opt-in):  services.TryAddSingleton(new AiProviderInfo("stub"));
//   no provider wired: services.TryAddSingleton(new AiProviderInfo("none"));

// GET /api/v1/ai/status - honest, side-effect-free provider signal for tests and ops.
// isConfigured is provider-derived (a real model only): "stub" and "none" report false, so synthesized
// dev content is never mistaken for a model and a live smoke never reports green on stub or none.
// `group` is the versioned AI route group (/api/v1/ai), so this maps to /api/v1/ai/status - the
// canonical path the CI/live lanes probe. A deployment MAY additionally expose an anonymous,
// unversioned /ai/status alias for infra probes; the versioned path stays canonical.
group.MapGet("/status", (
    [FromServices] AiProviderInfo provider) =>
    Results.Ok(new { provider = provider.Name, isConfigured = provider.Name is "azure" or "openai-compatible" }))
    .WithName("AiStatus");
```

### Agent Tests

Code-hosted agent tests must control tool use through request/options, not prompt wording. Add request flag such as `UseTools` (default `true`). No-tool smoke sets `UseTools=false` and maps to `ChatOptions.ToolMode = ChatToolMode.None`. Tool-calling tests set `UseTools=true`, use `ChatToolMode.Auto`, and bound the model call itself with a per-request `CancellationTokenSource.CancelAfter(...)` - the MSTest `[Timeout]` is a backstop only. Never rely on prompts like "do not call tools" as control flow.

**Bound every AI call by deadline, not by a small token cap.** Each structured or demo call - agent runs, seeded/demo content, live smokes - is bounded by:

- **A per-request `CancellationTokenSource.CancelAfter(...)` deadline.** This is the bound that actually holds. It is provider-independent, it covers a model that stalls as well as one that over-generates, and it is the same mechanism the tool-calling tests above already use.
- **A tool-call iteration cap**, so a tool loop terminates independently of wall-clock (*AI Trust Boundary*, rule 6).
- **A `MaxOutputTokens` floor, not a ceiling tuned for brevity.** Reasoning-capable models spend tokens on internal reasoning before emitting anything visible, and that budget counts against `MaxOutputTokens`. A cap sized for the expected answer (a few hundred tokens) is consumed before the first visible token, and the call returns an empty completion - which then looks like "the model returned nothing parseable" rather than "the cap was too low". Size it comfortably above the largest expected response plus the model's reasoning budget, and treat an empty completion as a suspected cap, not a parse failure.
- **Determinism comes from schema-constrained output and a fixed prompt prefix**, not from `Temperature`. Set `Temperature = 0` where it is accepted, but do not rely on it: reasoning-capable models ignore or reject the parameter, and a provider rejecting it is a configuration error to surface, not a result to retry around. Constrain the shape with `ChatOptions.ResponseFormat` (*Structured Output*) and assert on typed members, never on exact wording.

Keep the same bounds in the generated agent run path ([agent-template.md](../templates/agent-template.md)) and in tests, so a test cannot pass under limits the app does not apply.

```csharp
// ChatClientAgent requires IChatClient - use a mock or test double
// For function tool tests, test tools directly (they're plain C# methods)
var tools = new TaskItemTools(NullLogger<TaskItemTools>.Instance, mockService.Object, mockSearch.Object);
var result = await tools.SearchTasks("overdue");
Assert.IsTrue(result.Contains("expected text"));
```

### Search Tests

Mock `SearchClient` or use an integration test against a real test index. Verify index schema and field names match the projected entity shape.

### Function Tool Tests

Test function tools independently - they are plain C# methods that wrap domain services. Use standard unit test patterns with mocked `I{Entity}Service`.

---

## References

- [Microsoft Foundry](https://learn.microsoft.com/en-us/azure/ai-foundry/what-is-foundry)
- [Agent Framework Overview](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [Agent Framework - Workflows](https://learn.microsoft.com/en-us/agent-framework/workflows/)
- [Azure AI Search - .NET SDK](https://learn.microsoft.com/en-us/azure/search/search-howto-dotnet-sdk)
