# FlowEngine Trigger Templates

Generated when `includeFlowEngine: true`. Pick one or more triggers based on `.scaffold/resource-implementation.yaml` flags. See [../skills/flowengine.md](../skills/flowengine.md) for the surrounding FE setup.

> **Token vs log placeholder:** `{WorkflowId}`, `{InstanceId}`, and `{TaskId}` inside the `LogInformation` message templates below are **log property names** bound to the trailing arguments, not scaffold tokens - leave them verbatim. Rule: [../ai/placeholder-tokens.md](../ai/placeholder-tokens.md) section Disambiguating Tokens From Logging And Interpolation.

## App-Level Facade - `IWorkflowTrigger`

`IFlowEngine` is the engine's full API (start, signal, resume, terminate). Wrap it in a thin app-level facade so trigger sites stay testable and small. Service Bus, inline, and scheduler adapters may launch the same workflow; keeping business logic in workflow nodes gives every source one versioned, tested behavior. Generate this in `{Project}.Application.Services`.

```csharp
namespace {Project}.Application.Services;

public interface IWorkflowTrigger
{
    Task<Guid> StartAsync(string workflowId, object input, CancellationToken ct = default);
}

public sealed class WorkflowTrigger(IFlowEngine engine) : IWorkflowTrigger
{
    public async Task<Guid> StartAsync(string workflowId, object input, CancellationToken ct = default)
    {
        var instance = await engine.StartAsync(workflowId, input, ct);
        return instance.InstanceId;
    }
}
```

Register in the bootstrapper:

```csharp
services.AddScoped<IWorkflowTrigger, WorkflowTrigger>();
```

---

## Trigger 1 - Service Bus Subscriber (`includeFunctionApp: true`)

Use when an out-of-process integration event should start a workflow. Lives in `{Project}.Functions`.

```csharp
namespace {Project}.Functions;

public sealed class StartWorkflowOnTaskCreated(
    IWorkflowTrigger workflows,
    ILogger<StartWorkflowOnTaskCreated> log)
{
    [Function(nameof(StartWorkflowOnTaskCreated))]
    public async Task Run(
        [ServiceBusTrigger("%TaskFlow:TaskCreatedTopic%", "%TaskFlow:Subscription%",
            Connection = "ServiceBus")]
        TaskCreatedIntegrationEvent evt,
        FunctionContext ctx)
    {
        var ct = ctx.CancellationToken;
        var input = new
        {
            evt.TenantId,
            evt.TaskItemId,
            evt.CreatedUtc
        };

        var instanceId = await workflows.StartAsync(
            workflowId: "approval-loop",
            input: input,
            ct: ct);

        log.LogInformation(
            "Started workflow {WorkflowId} instance {InstanceId} for task {TaskId}",
            "approval-loop", instanceId, evt.TaskItemId);
    }
}
```

Notes:
- The function project must already have `IWorkflowTrigger` registered (see [../skills/function-app.md](../skills/function-app.md) for the function host's DI bootstrapping).
- Use the **typed integration event**, not the in-process `IMessage` model. In-process messages are not delivered through Service Bus and will not arrive at the function.

---

## Trigger 2 - Inline (in-process command)

Use when an API endpoint or service should kick off a workflow synchronously as part of its own work. No new infrastructure.

```csharp
public sealed class TaskItemService(
    IRepository<TaskItem> repo,
    IWorkflowTrigger workflows) : ITaskItemService
{
    public async Task<DomainResult<TaskItem>> ApproveAsync(Guid id, CancellationToken ct)
    {
        var item = await repo.GetByIdAsync(id, ct);
        if (item is null) return DomainResult.NotFound<TaskItem>(id);

        item.MarkApproved();
        await repo.SaveAsync(item, ct);

        // Fire-and-track: the workflow id and the entity id are bound for later correlation.
        await workflows.StartAsync(
            workflowId: "notify-on-completion",
            input: new { item.Id, item.TenantId },
            ct: ct);

        return DomainResult.Success(item);
    }
}
```

Use this when:
- The trigger is an in-process command.
- You want the call site to fail loudly if FE is unavailable (vs. swallowing in a queue).

Avoid this when:
- The workflow may take many seconds and you want to return to the caller immediately. Prefer Trigger 1 (out-of-process) for that.

---

## Trigger 3 - TickerQ Recurring Job (`includeScheduler: true`)

Use when a workflow runs on a cron. Lives in `{Project}.Scheduler`.

```csharp
namespace {Project}.Scheduler.Jobs;

// Top-level class: TickerQ's source generator ignores nested job classes.
public sealed class NightlyReconciliationJob(ScheduledJobRunner runner)   // EF.BackgroundServices.TickerQ
{
    [TickerFunction(functionName: nameof(NightlyReconciliationJob), cronExpression: "0 0 2 * * *")]
    public Task Run(TickerFunctionContext context, CancellationToken ct) =>
        runner.RunAsync<NightlyReconciliationHandler>(context, ct);
}

public sealed class NightlyReconciliationHandler(IWorkflowTrigger workflows, TimeProvider clock) : IScheduledJobHandler
{
    public Task HandleAsync(CancellationToken ct) =>
        workflows.StartAsync(
            workflowId: "nightly-reconciliation",
            input: new { RunDate = DateOnly.FromDateTime(clock.GetUtcNow().UtcDateTime) },
            ct: ct);
}
```

Notes:
- Cron uses TickerQ's six-field expression with seconds first (UTC); the attribute is the only place a job's cron lives - see [../skills/background-services.md](../skills/background-services.md) section Runtime Scheduling APIs.
- Register the handler scoped (`services.AddScoped<NightlyReconciliationHandler>()`); the runner resolves it in TickerQ's execution scope with one span, `scheduler.job.*` metrics and TickerQ's cancellation contract. More than one scheduler replica needs the Redis-backed `IDistributedLock` for cron seeding - see [../skills/background-services.md](../skills/background-services.md).
- Do **not** put the workflow's business logic in the job. The job is a thin trigger; the work belongs in the workflow's nodes.

### Per-tenant scheduled start

Use when the workflow acts on each tenant's data. Proof: TaskFlow `ComplianceCheckHandler`, `ComplianceCheckSchedulerSmokeTests`.

```csharp
public sealed class {Workflow}Handler(
    I{Entity}SystemRepository systemRepository, IFlowEngine engine, ILogger<{Workflow}Handler> logger, TimeProvider clock)
    : IScheduledJobHandler
{
    public async Task HandleAsync(CancellationToken ct)
    {
        var failures = new List<Exception>();
        await foreach (var tenantId in systemRepository.Stream{Qualifying}TenantsAsync(pageSize: 200, ct))   // filters off, keyset over TenantId
        {
            if (tenantId != SelfCallTenantId) { logger.LogInformation("Skipped tenant {TenantId}", tenantId); continue; }
            var day = clock.GetUtcNow().UtcDateTime;
            var key = $"{WorkflowId}:{tenantId}:{day:yyyy-MM-dd}";   // also the correlation id; at most the column width
            try { await engine.StartBackgroundAsync(new StartRequest { WorkflowId = WorkflowId, TenantId = tenantId.ToString(), CorrelationId = key, IdempotencyKey = key }, ct); }
            catch (Exception ex) when (ex is not OperationCanceledException || !ct.IsCancellationRequested) { failures.Add(ex); }
        }
        if (failures.Count > 0) throw new AggregateException($"{WorkflowId} failed to start for {failures.Count} tenants.", failures);
    }
}
```

- Stream the qualifying tenants through the system repository (query filters off, keyset paging over `TenantId`) and start each with `StartRequest.TenantId` set and a date-scoped `IdempotencyKey` `{workflow}:{tenant}:{yyyy-MM-dd}` that fits the correlation-id column width.
- Prove same-day dedupe with an integration test that runs the job twice after newer instances exist. If the state store does not return the existing instance for a repeated key, look up the day's instance by workflow id and correlation id before starting, at that one site, with a comment naming the removal condition (the state store returns the existing instance for a repeated key regardless of newer instances).
- Start only tenants the workflow's API self-call identity can act for. A fan-out beyond that identity's tenant produces a false-clean result (its searches return the caller's tenant data or nothing). Log and count each skipped tenant.
- Collect per-tenant start failures and throw them together after the stream ends; the job's own cancellation stops the run immediately.
- Every host that executes workflow nodes needs the API self-call base URL (`FlowEngine:ApiBaseUrl`) wired: the Scheduler for scheduled starts, the API for human-task resumes and dashboard starts, Functions if it starts workflows. Wire it in each topology (Aspire, compose, Bicep) and pin it with contract tests.

---

## Selecting a Trigger

| Source of trigger | Template |
|---|---|
| Out-of-process integration event (Service Bus topic/queue) | Trigger 1 (Functions subscriber) |
| In-process API/service call | Trigger 2 (inline) |
| Cron / time-based | Trigger 3 (TickerQ job) |
| Multiple sources | Generate each independently; all funnel through `IWorkflowTrigger`. |

Record which triggers are enabled per workflow in `.scaffold/DESIGN-DECISIONS.md`.
