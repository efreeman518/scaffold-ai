# Background Services (TickerQ Scheduler)

## Prerequisites

- [solution-structure.md](solution-structure.md)
- [bootstrapper.md](bootstrapper.md)
- [aspire.md](aspire.md)
- [data-persistence.md](data-persistence.md)
- TickerQ docs & source: [https://github.com/Arcenox-co/TickerQ](https://github.com/Arcenox-co/TickerQ)

## Purpose

Use `{Host}.Scheduler` for cron/time-based orchestration with persisted scheduling state via TickerQ. Keep in-process queue consumers and listeners in `{Host}.BackgroundServices`.

## Non-Negotiables

1. Scheduler is a separate host project from API.
2. Job methods are thin `[TickerFunction]` adapters; business logic lives in handlers.
3. Deploy one scheduler replica unless EF.Cache has Redis configured, so the `IDistributedLock` around cron seeding is shared. **Why:** Without distributed coordination, replicas seed the same schedule concurrently and race persisted state. Therefore one replica is the safe baseline.
4. TickerQ persistence uses the app-owned `{App}TickerQDbContext` with the `[Scheduler]` schema and its own migration history table (`Scheduler.__EFMigrationsHistory_TickerQ`).
5. TickerQ schema is applied by the `{App}.DatabaseMigrator` host; scheduler startup validates the schema exists and fails fast - it never creates or patches it (see [../support/data-persistence-advanced.md](../support/data-persistence-advanced.md) section Third-Party Operational Store Schemas).

---

## Scheduler vs BackgroundServices

- `{Host}.Scheduler`: persisted cron/time scheduling, dashboard, orchestration.
- `{Host}.BackgroundServices`: channel consumers, long-running listeners, queue pumps.
- Use both when needed, but keep their responsibilities and deployment independent.

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
- For work that needs persistence, retry, or scheduling, use TickerQ instead.
- The queue is in-memory - items are lost if the host crashes before processing.
- Audit records, notifications with delivery commitments, and cross-service events are not disposable. Persist them through the transaction/outbox, scheduler, or broker path in [messaging.md](messaging.md).
- Always create a new DI scope inside the work item if you need scoped services (DbContext, etc.). **Why:** Queued work can outlive the enqueueing request scope; capturing it can access disposed services or reuse one DbContext unit of work across items. Therefore resolve scoped dependencies inside each work item.

## Minimal Scheduler Structure

```
Host/{Host}.Scheduler/
|-- Program.cs
|-- RegisterSchedulerServices.cs
|-- Jobs/{Feature}Jobs.cs
|-- Handlers/{JobName}Handler.cs
`-- appsettings*.json
```

The job runner, the handler contract, the scheduler telemetry, the operational-store validation, occurrence retention and the stall health check are EF.BackgroundServices.TickerQ ([../support/ef-packages-optional.md](../support/ef-packages-optional.md) section Scheduling (EF.BackgroundServices.TickerQ)); generate no job base class, handler interface, scheduler exception handler, schema validator, retention handler or scheduler health check. The Scheduler project references EF.BackgroundServices.TickerQ **directly**: the package carries TickerQ with `PrivateAssets="none"` so TickerQ's source generator reaches the consuming project, and a transitive reference does not run it.

Reference patterns: [../patterns/infrastructure-wiring.md](../patterns/infrastructure-wiring.md) (Aspire Resource Wiring).

---

## Registration Sequence (Required)

The startup flow must remain in this order:

1. Add service defaults.
2. Register bootstrapper infra/app services (including `AddTypedCache`, which registers the `IDistributedLock` the cron-seed lock uses).
3. Register scheduler-specific services (handlers, job classes, dispatcher, workers).
4. Configure TickerQ (`AddEFTickerQ`).
5. Build app.
6. Validate the TickerQ operational store (`TickerQSchemaValidator`; validate-only - the migrator applied the schema).
7. Call `app.UseTickerQ()`.
8. Map health/endpoints and run.

```csharp
builder.AddServiceDefaults();
services
    .RegisterInfrastructureServices(config)
    .RegisterApplicationServices(config)
    .AddSchedulerServices(config);            // AddScoped<{JobName}Handler>(), AddScoped<{Feature}Jobs>()

builder.Services.AddEFTickerQ<{App}TickerQDbContext>(
    config,
    db => db.Use{App}Provider(/* TickerQDbContext connection, history table, schema */),
    {App}TickerQDbContext.SchemaName,
    options => { /* options.AddDashboard(...) only when Scheduling:EnableDashboard, never without basic auth */ });
builder.Services.AddHealthChecks().AddSchedulerHealthCheck<{App}TickerQDbContext>(tags: ["ready"]);

var app = builder.Build();
await TickerQSchemaValidator.ValidateAsync<{App}TickerQDbContext>(app.Services);
app.UseTickerQ();                             // required: TickerQ initializes and seeds crons only after this
app.MapDefaultEndpoints();
await app.RunAsync();
```

**TickerQ jobs are top-level classes, and the host calls `UseTickerQ()`.** TickerQ's source generator registers `[TickerFunction]` methods only on top-level (non-nested) classes, and nothing initializes, seeds or fires until `UseTickerQ()` runs after `AddEFTickerQ`. A nested job class or a missing `UseTickerQ()` compiles cleanly and never runs; the stall health check is what surfaces it.

---

## Job/Handler Split (Required)

```csharp
// Top-level class; TickerQ resolves it in each execution's scope.
public sealed class ReminderJobs(ScheduledJobRunner runner)
{
    [TickerFunction("ProcessDueReminders", "10 */5 * * * *", TickerTaskPriority.High)]
    public Task ProcessDueRemindersAsync(TickerFunctionContext context, CancellationToken ct) =>
        runner.RunAsync<ProcessDueRemindersHandler>(context, ct);
}

public sealed class ProcessDueRemindersHandler(/* repositories, IOutboxStaging, ScheduledJobTelemetry */) : IScheduledJobHandler
{
    public Task HandleAsync(CancellationToken ct) => /* application logic */ Task.CompletedTask;
}
```

- Job methods only map trigger -> handler.
- Handler implements `IScheduledJobHandler` (`EF.BackgroundServices.Scheduling`), holds the domain/application logic and remains testable; register it scoped.
- `ScheduledJobRunner.RunAsync<THandler>` resolves the handler from TickerQ's execution scope (no second scope), starts one `{job} execute` activity, records `scheduler.job.*` metrics, logs a failure once and rethrows it so TickerQ applies its retries, and turns a caller cancellation into the `TaskCanceledException` TickerQ treats as a cancellation.
- A handler that scans every tenant uses a system repository with `IgnoreQueryFilters([DbContextBase.TenantQueryFilterName])` or an all-tenants context ([multi-tenant.md](multi-tenant.md) section Automatic Query Filters), and records row counts with `ScheduledJobTelemetry.RecordWork`.
- A step that reads, guards and stages in one transaction runs each attempt from a clean change tracker, returns the committed attempt's result, and stages an outbox or work id only for a row its own guarded write affected; the handler counts after the call returns ([data-persistence.md](data-persistence.md) section Set-Based Writes and Query Shape).

---

## TickerQ Configuration Contract

`AddSchedulerServices` and the TickerQ registration must cover:

- Scoped handlers and job adapters.
- Scheduler settings from the `Scheduling` section (`TickerQSchedulerSettings`: `MaxConcurrency`, `PollIntervalSeconds`, `IdleWorkerTimeoutMinutes`, `NodeIdentifier` default `{MachineName}:{ProcessId}`, `SeedLockKey` / `SeedLockTtl` / `SeedLockTimeout`). The scheduler time zone is UTC.
- EF Core persistence through the `configureDbContext` callback of `AddEFTickerQ<{App}TickerQDbContext>` with the `[Scheduler]` schema; the provider options set the migrations assembly + history table to match the migrator target. `AddEFTickerQ(config, configure)` without a context is the in-memory store: one replica, tests and development only.
- Optional dashboard through the `configure` callback (secure credentials only).
- Occurrence retention through the package `TickerQOccurrenceRetentionHandler<{App}TickerQDbContext>` on a cron (`Scheduling:Retention:OccurrenceRetention`, default 7 days).

If workflows are time-policy sensitive (billing windows, scheduled publish, SLA windows), bind a shared time-boundary policy and avoid hard-coded timezone math inside handlers.

Key settings:

| Section | Keys |
|---|---|
| `ConnectionStrings` | `{Project}DbContextTrxn`, `TickerQDbContext` |
| `Scheduling` | `UsePersistence`, `EnableDashboard`, `MaxConcurrency`, `PollIntervalSeconds` |
| `Scheduling:Retention` | `OccurrenceRetention` |
| `Scheduling:Health` | `StallThreshold` (required) |
| `Scheduling:Dashboard` | `Username`, `Password` |

## Database Setup

- `TickerQDbContext` keeps its own logical connection name; it may point at the app database (local) or a dedicated DB (Azure) - configuration only, never runtime code.
- TickerQ tables remain isolated by the `[Scheduler]` schema with their own migration history table.
- Schema is applied by the `{App}.DatabaseMigrator` host via the app-owned `{App}TickerQDbContext` migration target; migrations live under `Migrations/TickerQ` with an explicit migrations assembly. Scheduler startup validates the schema with `TickerQSchemaValidator.ValidateAsync`, which names every missing table and never creates or patches it; library auto-create and deployment-script generation stay off. Canonical rules: [../support/data-persistence-advanced.md](../support/data-persistence-advanced.md) section Third-Party Operational Store Schemas.

---

## Runtime Scheduling APIs

- One-off jobs: use `ITimeTickerManager<T>.EnqueueAsync("JobName", scheduledTime, payload)`.
- Cron jobs: declare the expression on the job method, `[TickerFunction("JobName", "<cron>")]`, or as a `%Section:Key%` placeholder TickerQ resolves from configuration. TickerQ seeds attribute cron idempotently at start, keyed by function, inside the package's distributed seed lock. Never seed code-defined jobs with `ICronTickerManager.AddAsync`: before the host starts no function is registered, so every call returns a failed result, and after start every restart and replica inserts a duplicate ticker.

TickerQ cron format is six fields: seconds, minutes, hours, day-of-month, month, day-of-week.

`AddSchedulerHealthCheck<{App}TickerQDbContext>` asserts the scheduler fires, not only that the process is up: it reports its failure status (Degraded by default) when the latest cron execution is older than `Scheduling:Health:StallThreshold` (twice the shortest cron interval is a good value), or when nothing has executed and the host has been up longer than the threshold.

For ingestion/event-time workflows, define and apply allowed-lateness/watermark behavior before triggering reconciliation jobs.

---

## Deployment Rules

- More than one scheduler replica needs the Redis-backed `IDistributedLock` from EF.Cache: the in-process lock gives no protection across replicas, and a node that cannot take the seed lock within `SeedLockTimeout` fails to start. Two replicas on one host need distinct `NodeIdentifier` values (the default already differs by process id).
- The seed lock relies on the Generic Host starting hosted services in order; never set `HostOptions.ServicesStartConcurrently = true` on the scheduler host.
- Keep scheduler as its own resource in Aspire/AppHost.
- If dashboard is enabled, secure credentials through environment variables or Key Vault.

### Worker SDK choice drives ACA ingress

A "worker" scaffolded as `Microsoft.NET.Sdk.Web` (uses `WebApplication`, maps `/health` + `/`) DOES serve HTTP, so on Container Apps it gets **internal** ingress (not "no ingress"). That is fine - health probes pass. Do not try to disable its ingress. Only a plain `Microsoft.NET.Sdk.Worker` generic-host project (no `WebApplication`, no mapped endpoints) gets **no ingress**. Pick the SDK to match the intent: use `Sdk.Worker` for pure background processing with no HTTP surface; use `Sdk.Web` when you want the host to expose health endpoints (and accept internal ingress).

---

## Lite Mode

In `lite` mode keep only:

- Program + registration + one job + one handler.
- Persistence and core scheduling settings.

Skip by default:

- Dashboard
- Expanded one-off/cron examples

---

## Verification

- [ ] Scheduler project builds cleanly
- [ ] `dotnet run --project src/Host/{Host}.Scheduler` starts successfully
- [ ] At least one `[TickerFunction]` is registered
- [ ] Job classes are top-level and delegate through `ScheduledJobRunner.RunAsync<THandler>()`; the host calls `UseTickerQ()`
- [ ] `{App}TickerQDbContext` is resolved; startup validation confirms the `[Scheduler]` schema exists (migrator ran)
- [ ] Aspire config uses `WithReplicas(1)` unless Redis backs the `IDistributedLock`
- [ ] If dashboard enabled, credentials are not default/plain test values
- [ ] If `{Host}.BackgroundServices` exists, it remains a separate project

See [placeholder-tokens.md](../ai/placeholder-tokens.md) for token definitions.
