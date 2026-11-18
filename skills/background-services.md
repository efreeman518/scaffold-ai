# Background Services (Scheduler)

## Prerequisites

- [solution-structure.md](solution-structure.md)
- [bootstrapper.md](bootstrapper.md)
- [aspire.md](aspire.md)
- [data-persistence.md](data-persistence.md)
- EF.Data.Scheduling API: [../support/ef-packages-optional.md](../support/ef-packages-optional.md#scheduling-efdatascheduling)

## Purpose

Use `{Host}.Scheduler` for cron and one-off jobs with persisted scheduling state through EF.Data.Scheduling. Keep in-process queue consumers and listeners in `{Host}.BackgroundServices`.

## Non-Negotiables

1. Scheduler is a separate host project from API.
2. Each job is an `IScheduledJobHandler` registered on `AddEFScheduler`; the handler holds the work.
3. Every replica runs the cron planner and the job worker; the database coordinates them, so there is no lock service, leader election or single-replica rule. Delivery is at least once, so handlers are idempotent.
4. Scheduling persistence uses the app-owned `{App}SchedulerDbContext` with the `scheduler` schema and its own migration history table (`__EFMigrationsHistory_Scheduler`).
5. The `{App}.DatabaseMigrator` host applies that schema; scheduler startup validates it and fails fast - it never creates or patches it (see [../support/data-persistence-advanced.md](../support/data-persistence-advanced.md) section Third-Party Operational Store Schemas).

---

## Scheduler vs BackgroundServices

- `{Host}.Scheduler`: persisted cron and one-off jobs.
- `{Host}.BackgroundServices`: channel consumers, long-running listeners, queue pumps.
- Use both when needed, but keep their responsibilities and deployment independent.
- **A `BackgroundService` failure stops the host.** When `ExecuteAsync` throws, the host stops and `RunAsync` throws. A worker that must survive a failure catches and handles it inside `ExecuteAsync` (log, back off, continue its loop).

---

## Channel-Based Background Task Queue

Use `EF.BackgroundServices` for fire-and-forget background work within the API host. The package provides a `Channel<T>`-backed producer/consumer queue.

### Registration (Bootstrapper)

```csharp
private static IServiceCollection AddSupportServices(this IServiceCollection services)
{
    services.AddChannelBackgroundTaskQueueWithShutdownHandling();
    services.AddSingleton<IInternalMessageBus, InternalMessageBus>();
    return services;
}
```

`AddChannelBackgroundTaskQueueWithShutdownHandling()` registers `IBackgroundTaskQueue` (singleton) + `ChannelBackgroundTaskQueue` hosted service. The "WithShutdownHandling" variant drains the queue on host shutdown.

### Usage (in services/endpoints)

```csharp
public class SomeService(IBackgroundTaskQueue taskQueue)
{
    public void EnqueueWork(Guid itemId)
    {
        taskQueue.QueueBackgroundWorkItem(async ct =>
        {
            // Fire-and-forget work - runs outside request scope
            // Create a new DI scope if you need scoped services
        });
    }
}
```

### Rules

- Use only for disposable work that does not need persistence or retry, such as best-effort cache warm-up or telemetry enrichment.
- For work that needs persistence, retry, or scheduling, use the scheduler (`IJobScheduler.Schedule`) instead.
- The queue is in-memory - items are lost if the host crashes before processing.
- Audit records, notifications with delivery commitments, and cross-service events are not disposable. Persist them through the transaction/outbox, scheduler, or broker path in [messaging.md](messaging.md).
- Always create a new DI scope inside the work item if you need scoped services (DbContext, etc.). **Why:** Queued work can outlive the enqueueing request scope; capturing it can access disposed services or reuse one DbContext unit of work across items. Therefore resolve scoped dependencies inside each work item.

## Minimal Scheduler Structure

```
Host/{Host}.Scheduler/
|-- Program.cs
|-- RegisterSchedulerServices.cs
|-- Handlers/{JobName}Handler.cs
`-- appsettings*.json
```

The cron planner, the leased job worker, the handler contract, scheduler telemetry, schema validation, run-history retention and the stall health check are EF.Data.Scheduling and EF.BackgroundServices ([../support/ef-packages-optional.md](../support/ef-packages-optional.md#scheduling-efdatascheduling)); generate no job adapter or base class, handler interface, scheduler exception handler, schema validator, retention handler or scheduler health check.

Reference patterns: [../patterns/infrastructure-wiring.md](../patterns/infrastructure-wiring.md) (Aspire Resource Wiring).

---

## Registration Sequence (Required)

1. Add service defaults.
2. Register bootstrapper infra/app services.
3. Register scheduler-specific services (dispatcher, workers, consumers).
4. Register `{App}SchedulerDbContext`, `AddEFScheduler` with every job, and the scheduler health check.
5. Build app.
6. Validate the schema (`SchedulerSchemaValidator`; validate-only - the migrator applied it).
7. Map health/endpoints and run; the planner and worker start with the host.

```csharp
builder.AddServiceDefaults();
services
    .RegisterInfrastructureServices(config)
    .RegisterApplicationServices(config)
    .AddSchedulerServices(config);

services.AddDbContext<{App}SchedulerDbContext>(db => db.Use{App}Provider(/* {App}SchedulerDbContext connection, history table, schema */));
services.AddEFScheduler<{App}SchedulerDbContext>()
    .AddJob<{JobName}Handler>({JobName}Handler.JobName, o => o.Cron = "0 0 2 * * *")
    .AddJob<SchedulerRetentionHandler<{App}SchedulerDbContext>>("scheduler_retention", o => o.Cron = "0 30 4 * * *");
services.AddHealthChecks().AddSchedulerHealthCheck<{App}SchedulerDbContext>(tags: ["ready"]);

var app = builder.Build();
await SchedulerSchemaValidator.ValidateAsync<{App}SchedulerDbContext>(app.Services);
app.MapDefaultEndpoints();
await app.RunAsync();
```

**Register every job on the one `AddEFScheduler` call.** A job missing there is never planned or executed, and a queued run whose job name is unregistered parks at once. Each process uses exactly one of `AddEFScheduler` (executing host) or `AddEFSchedulerClient<TContext>()` (a process that only schedules or administers), once.

---

## Job Handlers (Required)

```csharp
public sealed class ProcessDueRemindersHandler(/* repositories, IOutboxStaging, ScheduledJobTelemetry */) : IScheduledJobHandler
{
    public const string JobName = "process_due_reminders";   // also the job tag on its telemetry
    public Task HandleAsync(CancellationToken ct) => /* application logic */ Task.CompletedTask;
}
```

- Handler implements `IScheduledJobHandler` (`EF.BackgroundServices.Scheduling`), or `IScheduledJobHandler<TPayload>` for a payload job (no cron). `AddJob` registers it scoped; each attempt resolves it from a fresh scope. A thrown exception fails the attempt.
- Job names are lowercase snake_case (`overdue_task_check`, `scheduler_retention`), so `Scheduling__Jobs__{name}__Cron` stays settable as an environment variable.
- The worker runs each attempt as one `{job} execute` activity with `scheduler.job.*` metrics, cancels the handler's token at `Timeout`, retries a failure with backoff and parks the run after `MaxAttempts`.
- A handler that scans every tenant uses a system repository with `IgnoreQueryFilters([DbContextBase.TenantQueryFilterName])` or an all-tenants context ([multi-tenant.md](multi-tenant.md) section Automatic Query Filters), and records row counts with `ScheduledJobTelemetry.RecordWork`.
- A step that reads, guards and stages in one transaction runs each attempt from a clean change tracker, returns the committed attempt's result, and stages an outbox or work id only for a row its own guarded write affected; the handler counts after the call returns ([data-persistence.md](data-persistence.md) section Set-Based Writes and Query Shape).

---

## Configuration Contract

| Section | Keys |
|---|---|
| `ConnectionStrings` | `{Project}DbContextTrxn`, `{App}SchedulerDbContext` |
| `Scheduling` | `Slots`, `CronPollInterval`, `MaxAttempts`, `LeaseDuration` |
| `Scheduling:Jobs:{name}` | `Cron`, `TimeZoneId`, `Timeout`, `MaxConcurrency` (override the code values) |
| `Scheduling:Retention` | `RunRetention`, `ParkedRetention` |
| `Scheduling:Health` | `StallThreshold` (required) |

Defaults and validation (`LeaseDuration` must exceed every `Timeout` plus twice `SettlementTimeout`) are in the package table linked above. If workflows are time-policy sensitive (billing windows, scheduled publish, SLA windows), bind a shared time-boundary policy and avoid hard-coded timezone math inside handlers.

## Database Setup

- `{App}SchedulerDbContext` keeps its own logical connection name; it may point at the app database (local) or a dedicated DB (Azure) - configuration only, never runtime code.
- Context shape, one initial migration per provider under `Migrations/Scheduler`, and migrator ownership: [../support/data-persistence-advanced.md](../support/data-persistence-advanced.md) section Third-Party Operational Store Schemas. `SchedulerSchemaValidator.ValidateAsync` names every missing table and never changes schema.

---

## Runtime Scheduling APIs

- Cron jobs: `AddJob<THandler>(name, o => o.Cron = "<cron>")`. Six fields, seconds first: seconds, minutes, hours, day-of-month, month, day-of-week; read in UTC unless `TimeZoneId` is set. An empty cron runs only when scheduled or triggered. A new job starts at its next occurrence; occurrences missed while no replica ran collapse into one run of the latest.
- One-off runs: `IJobScheduler.Schedule(name, payload, runAtUtc)` stages a row on the scoped scheduler context; it commits when that context saves.
- Administration: `ISchedulerAdmin` (scoped) lists jobs, runs and the queue, triggers a run and retries a parked one. The package ships no dashboard or HTTP endpoints; an admin API built on it applies its own authorization.

`AddSchedulerHealthCheck<{App}SchedulerDbContext>` asserts the scheduler runs, not only that the process is up: it reports its failure status (Degraded by default) when the newest finished attempt is older than `Scheduling:Health:StallThreshold` (twice the shortest cron interval is a good value), or when nothing has run and the replica has been up longer than the threshold. Register it only on executing hosts.

For ingestion/event-time workflows, define and apply allowed-lateness/watermark behavior before triggering reconciliation jobs.

---

## Deployment Rules

- Replicas scale without coordination services: the planner enqueues each occurrence once through a version-guarded state row, and the EF.Data.Outbox lease gives each run to one replica.
- `MaxConcurrency` bounds one job per replica, so a job that must never overlap across replicas takes its own lock.
- There is no lease renewal: a handler that ignores its cancellation token can outlive `LeaseDuration` and run again on another replica.
- Keep scheduler as its own resource in Aspire/AppHost. Deploy the migrator, then the executing scheduler, before client processes.

### Worker SDK choice drives ACA ingress

A "worker" scaffolded as `Microsoft.NET.Sdk.Web` (uses `WebApplication`, maps `/health` + `/`) DOES serve HTTP, so on Container Apps it gets **internal** ingress (not "no ingress"). That is fine - health probes pass. Do not try to disable its ingress. Only a plain `Microsoft.NET.Sdk.Worker` generic-host project (no `WebApplication`, no mapped endpoints) gets **no ingress**. Pick the SDK to match the intent: use `Sdk.Worker` for pure background processing with no HTTP surface; use `Sdk.Web` when you want the host to expose health endpoints (and accept internal ingress).

---

## Lite Mode

In `lite` mode keep only:

- Program + registration + one job + one handler, plus scheduler retention and the health check.
- Persistence and core scheduling settings.

Skip by default:

- Client registrations and an admin API
- Expanded one-off/cron examples

---

## Verification

- [ ] Scheduler project builds cleanly
- [ ] `dotnet run --project src/Host/{Host}.Scheduler` starts successfully
- [ ] Every job, including `SchedulerRetentionHandler<{App}SchedulerDbContext>`, is registered on the one `AddEFScheduler` call with a lowercase snake_case name
- [ ] Startup validation confirms the `scheduler` schema exists (migrator ran)
- [ ] `Scheduling:Health:StallThreshold` is set and the scheduler health check is registered
- [ ] If `{Host}.BackgroundServices` exists, it remains a separate project

See [placeholder-tokens.md](../ai/placeholder-tokens.md) for token definitions.
