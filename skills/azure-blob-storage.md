# Azure Blob Storage (EF.Storage)

> **Shared shape** (settings class, repository wrapper, DI registration, Aspire integration, local inspection tools) lives in [azure-data-storage.md](azure-data-storage.md). This file covers Blob-specific guidance only.

### Purpose

Use Blob Storage for unstructured payloads (documents, media, exports, backups). Keep relational/queryable data in SQL/Cosmos/Table as appropriate.

### Non-Negotiables

1. Access blobs through `IBlobRepository` abstraction.
2. Register storage with named `BlobServiceClient` via `IAzureClientFactory`.
3. Use scoped SAS permissions and short expiry windows.
4. Keep container access private unless explicitly required.
5. Dispose downloaded streams correctly.

### Repository Contract

```csharp
public interface IBlobRepository
{
    Task CreateContainerAsync(ContainerInfo containerInfo, CancellationToken cancellationToken = default);
    Task DeleteContainerAsync(ContainerInfo containerInfo, CancellationToken cancellationToken = default);

    Task<(IReadOnlyList<BlobItem>, string?)> QueryPageBlobsAsync(
        ContainerInfo containerInfo,
        string? continuationToken = null,
        BlobTraits blobTraits = BlobTraits.None,
        BlobStates blobStates = BlobStates.None,
        string? prefix = null,
        CancellationToken cancellationToken = default);

    Task<IAsyncEnumerable<BlobItem>> GetStreamBlobList(
        ContainerInfo containerInfo,
        BlobTraits blobTraits = BlobTraits.None,
        BlobStates blobStates = BlobStates.None,
        string? prefix = null,
        CancellationToken cancellationToken = default);

    Task<Uri?> GenerateBlobSasUriAsync(
        ContainerInfo containerInfo,
        string blobName,
        BlobSasPermissions permissions,
        DateTimeOffset expiresOn,
        SasIPRange? ipRange = null,
        CancellationToken cancellationToken = default);

    Task UploadBlobStreamAsync(
        ContainerInfo containerInfo,
        string blobName,
        Stream stream,
        string? contentType = null,
        bool encrypt = false,
        IDictionary<string, string>? metadata = null,
        CancellationToken cancellationToken = default);

    Task UploadBlobStreamAsync(
        Uri sasUri,
        Stream stream,
        string? contentType = null,
        bool encrypt = false,
        IDictionary<string, string>? metadata = null,
        CancellationToken cancellationToken = default);

    Task<Stream> StartDownloadBlobStreamAsync(
        ContainerInfo containerInfo,
        string blobName,
        bool decrypt = false,
        CancellationToken cancellationToken = default);

    Task<Stream> StartDownloadBlobStreamAsync(
        Uri sasUri,
        bool decrypt = false,
        CancellationToken cancellationToken = default);

    Task DeleteBlobAsync(ContainerInfo containerInfo, string blobName, CancellationToken cancellationToken = default);
    Task DeleteBlobAsync(Uri sasUri, CancellationToken cancellationToken = default);
}
```

Supporting types:

```csharp
public class ContainerInfo
{
    public string ContainerName { get; set; } = null!;
    public ContainerPublicAccessType ContainerPublicAccessType { get; set; }
    public bool CreateContainerIfNotExist { get; set; }   // defaults to false
}

public enum ContainerPublicAccessType
{
    None = 0,
    BlobContainer = 1,
    Blob = 2
}
```

### Project Repository Wrapper

```csharp
public interface I{Project}BlobRepository : IBlobRepository { }

public class {Project}BlobRepository : BlobRepositoryBase, I{Project}BlobRepository
{
    public {Project}BlobRepository(
        ILogger<{Project}BlobRepository> logger,
        IOptions<{Project}BlobRepositorySettings> settings,
        IAzureClientFactory<BlobServiceClient> clientFactory)
        : base(logger, settings, clientFactory) { }
}

public class {Project}BlobRepositorySettings : BlobRepositorySettingsBase { }
```

`BlobRepositorySettingsBase` requires `BlobServiceClientName`.

**No overrides needed.** `BlobRepositoryBase` implements `IBlobRepository` and the provider-neutral `IObjectStorageRepository` (`UploadAsync(containerName, objectName, content, contentType, metadata, ct)`, `DownloadAsync`, `DeleteAsync`, `ExistsAsync`, `GetPresignedUrlAsync`, `ListAsync`) with non-virtual members. Application code that may run against S3 as well depends on `IObjectStorageRepository` ([../support/ef-packages-optional.md](../support/ef-packages-optional.md) section Object Storage (EF.Storage.Contracts, EF.Storage.S3)).

**Provision once, never per repository call.** Register a startup/deployment task that creates each configured container before the host reports ready, then set `CreateContainerIfNotExist: false` for normal repository operations. The startup task may call `CreateIfNotExistsAsync`, is idempotent, and uses a distributed coordination primitive only when concurrent creation is unsafe. Upload/download/delete paths assume provisioning completed and surface a missing-container failure instead of adding a control-plane call to every request. Apply the same rule to S3 buckets, tables, search indexes, and broker topology. See [../support/scalability-and-hosting.md](../support/scalability-and-hosting.md) section Data-Path Rules.

**`BlobContainerClient.GetBlobsAsync` signature gotcha.** The current Azure SDK requires **positional** arguments: `GetBlobsAsync(BlobTraits.None, BlobStates.None, prefix, cancellationToken)`. The named-argument form `GetBlobsAsync(prefix: "...", cancellationToken: ct)` that older Microsoft samples show **does not compile** - the method exposes no parameters by those names. Use positional, or assign through the well-named overload of `BlobContainerClient`.

### Configuration

`appsettings.json`

```json
{
  "ConnectionStrings": {
    "BlobStorage1": ""
  },
  "{Project}BlobRepositorySettings": {
    "BlobServiceClientName": "{Project}BlobClient"
  }
}
```

`appsettings.Development.json`

```json
{
  "ConnectionStrings": {
    "BlobStorage1": "UseDevelopmentStorage=true"
  }
}
```

### DI Registration

```csharp
private static void AddBlobStorageServices(IServiceCollection services, IConfiguration config)
{
    services.AddAzureClients(builder =>
    {
        builder.AddBlobServiceClient(config.GetConnectionString("BlobStorage1")!)
            .WithName("{Project}BlobClient");
    });

    services.Configure<{Project}BlobRepositorySettings>(
        config.GetSection("{Project}BlobRepositorySettings"));

    services.AddScoped<I{Project}BlobRepository, {Project}BlobRepository>();
}
```

### Usage Patterns

- **Server upload/download/delete:** repository with `ContainerInfo`.
- **Client direct upload/download:** generate temporary SAS URI with minimal permissions.
- **Large listings:** continuation-token paging or stream enumeration.
- **Cross-instance lock:** blob lease/distributed lock execution where needed.

Blob naming patterns:

- `{tenantId}/{entityType}/{entityId}/{filename}`
- `{guid}/{filename}`
- `{yyyy}/{MM}/{dd}/{filename}`

### Attachment Rules

Apply when blob content backs an entity row (attachments, evidence). Proof: TaskFlow `AttachmentRepositoryTrxn`, `AttachmentBlobDeleteWork`, `AttachmentService`.

- The object key is server-made, includes a fresh UUIDv7 and is immutable; a rename changes only the display name.
- After an upload, the server-owned fields (content type, size, storage URI, owner) are immutable: a request that changes them is a 400. A metadata-only row (no blob) keeps full replace.
- Never delete a blob inline, and never catch-and-log a blob delete failure. A delete stages a leased work row (`LeasedWorkItem`) in the same save that removes the entity row ([data-persistence.md](data-persistence.md) section Set-Based Writes and Query Shape); a worker deletes the blob and treats an already-missing blob as success. The work row id is a UUIDv5 of tenant id, entity id and storage key, so a re-sent commit maps to the same row while a caller id reused after a delete gets a distinct row. One builder creates these ids for every path that stages them.
- An upload reserves its own deferred delete before it writes the blob: save a work row for the new key that is not claimable before now plus a grace longer than the request timeout (startup validation enforces it); write the blob; then insert the entity row and remove the reservation in one transaction under the execution strategy. The removal is guarded on the row being unleased and not dead-lettered, so it fails when the worker holds the lease: roll back and fail the upload, and the reservation removes the orphan. Use a UUIDv7 reservation id so it never collides with a UUIDv5 delete id.
- An upload with a caller id replays a stored duplicate before it writes anything, and again after it loses an insert race ([data-persistence.md](data-persistence.md) section Idempotent Create). A caller id that belongs to a metadata-only row is a 409. An upload POST carries no precondition and never answers 412.

## Verification

- [ ] Repository derives from `BlobRepositoryBase`
- [ ] Settings derive from `BlobRepositorySettingsBase`
- [ ] Named `BlobServiceClient` registration exists
- [ ] Container names/access levels are explicit
- [ ] SAS generation uses least privilege + short expiry
- [ ] Download stream lifecycle is correctly disposed
- [ ] Local dev uses `UseDevelopmentStorage=true` (Azurite)
- [ ] Storage connection naming aligns with Aspire/IaC
