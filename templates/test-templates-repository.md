# Test Templates - Repository (Phase 5a)

| | |
|---|---|
| **Generates** | `tests/Test.Unit/Repositories/{Entity}RepositoryTrxnTests.cs`, `tests/Test.Unit/Repositories/{Entity}RepositoryQueryTests.cs` |
| **Requires** | [repository-template](repository-template.md), entity (implemented in 5a), `DbContextOptionsFactory` (EF.IntegrationTesting) |
| **Phase** | 5a (Foundation TDD) |
| **Protocol** | Write these tests AFTER entity is implemented (green). See [../ai/tdd-protocol.md](../ai/tdd-protocol.md). |

## Test Naming Convention

Owned by [../skills/testing.md](../skills/testing.md) section Test Naming Convention. `Given_When_Then` is the
default; `<Subject>_<Condition>_<Outcome>` applies when a named member or structural fact is under test.

---

Contexts run on the EF in-memory provider through `DbContextOptionsFactory.BuildInMemoryOptions<T>(dbName)`
(fast, no relational constraints); constraint, migration, and translation coverage belongs to the component
tier ([test-templates-integration.md](test-templates-integration.md)). `AuditId` is a required member; set
`TenantId` so the tenant query filter admits the seeded rows.

## Repository Trxn Tests

### File: `tests/Test.Unit/Repositories/{Entity}RepositoryTrxnTests.cs`

```csharp
[TestClass]
[TestCategory("Unit")]
public class {Entity}RepositoryTrxnTests
{
    [TestMethod]
    public async Task Given_ValidEntity_When_CrudCycleCompleted_Then_AllOperationsSucceed()
    {
        // Arrange
        var tenantId = Guid.NewGuid();
        await using var db = new {App}DbContextTrxn(
            DbContextOptionsFactory.BuildInMemoryOptions<{App}DbContextTrxn>())
        { AuditId = "test", TenantId = tenantId };
        var repo = new {Entity}RepositoryTrxn(db);
        var entity = {Entity}.Create(tenantId, "TestEntity").Value!;

        // Act - Create
        repo.Create(ref entity);
        await repo.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins);

        // Act - Read
        var retrieved = await repo.Get{Entity}Async(entity.Id);

        // Assert - Read
        Assert.IsNotNull(retrieved);
        Assert.AreEqual("TestEntity", retrieved.Name);

        // Act - Update via domain method
        retrieved.Update(name: "Updated");
        await repo.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins);

        // Assert - Updated
        var updated = await repo.Get{Entity}Async(entity.Id);
        Assert.AreEqual("Updated", updated!.Name);

        // Act - Delete
        repo.Delete(updated);
        await repo.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins);

        // Assert - Deleted
        var deleted = await repo.Get{Entity}Async(entity.Id);
        Assert.IsNull(deleted);
    }
}
```

---

## Repository Query Tests

### File: `tests/Test.Unit/Repositories/{Entity}RepositoryQueryTests.cs`

```csharp
[TestClass]
[TestCategory("Unit")]
public class {Entity}RepositoryQueryTests
{
    private static readonly Guid TenantId = Guid.NewGuid();

    [TestMethod]
    public async Task Given_SeededEntities_When_SearchWithFilter_Then_ReturnsMatchingEntities()
    {
        // Arrange
        await using var db = await SeedAsync("Alpha", "Beta", "AlphaTwo");
        var repo = new {Entity}RepositoryQuery(db);

        // Act
        var page = await repo.Search{Entity}Async(
            new SearchRequest<{Entity}SearchFilter>
            {
                PageIndex = 1,
                PageSize = 10,
                Filter = new {Entity}SearchFilter { SearchTerm = "Alpha" }
            });

        // Assert
        Assert.AreEqual(2, page.Total);
        Assert.IsTrue(page.Data.All(i => i.Name.Contains("Alpha")));
    }

    [TestMethod]
    public async Task Given_PaginatedRequest_When_SearchExecuted_Then_ReturnsCorrectPage()
    {
        // Arrange
        await using var db = await SeedAsync(Enumerable.Range(0, 15).Select(i => $"Item{i}").ToArray());
        var repo = new {Entity}RepositoryQuery(db);

        // Act
        var page = await repo.Search{Entity}Async(
            new SearchRequest<{Entity}SearchFilter>
            {
                PageIndex = 2,
                PageSize = 10,
                Filter = new {Entity}SearchFilter()
            });

        // Assert
        Assert.AreEqual(15, page.Total);
        Assert.AreEqual(5, page.Data.Count);
    }

    // Seeds through a write context, then reads through a query context over the same in-memory database.
    private static async Task<{App}DbContextQuery> SeedAsync(params string[] names)
    {
        var dbName = Guid.NewGuid().ToString();
        await using (var trxn = new {App}DbContextTrxn(
            DbContextOptionsFactory.BuildInMemoryOptions<{App}DbContextTrxn>(dbName))
        { AuditId = "test", TenantId = TenantId })
        {
            foreach (var name in names)
                trxn.Set<{Entity}>().Add({Entity}.Create(TenantId, name).Value!);
            await trxn.SaveChangesAsync(OptimisticConcurrencyWinner.ClientWins);
        }
        return new {App}DbContextQuery(DbContextOptionsFactory.BuildInMemoryOptions<{App}DbContextQuery>(dbName))
        { AuditId = "test", TenantId = TenantId };
    }
}
```
