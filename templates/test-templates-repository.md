# Test Templates - Repository (Phase 5a)

| | |
|---|---|
| **Generates** | `tests/Test.Unit/Repositories/{Entity}RepositoryTrxnTests.cs` |
| **Requires** | [repository-template](repository-template.md), entity (implemented in 5a), `DbContextOptionsFactory` (EF.IntegrationTesting) |
| **Phase** | 5a (Foundation TDD) |
| **Protocol** | Write these tests AFTER entity is implemented (green). See [../ai/tdd-protocol.md](../ai/tdd-protocol.md). |

## Test Naming Convention

Owned by [../skills/testing.md](../skills/testing.md) section Test Naming Convention. `Given_When_Then` is the
default; `<Subject>_<Condition>_<Outcome>` applies when a named member or structural fact is under test.

---

This file covers repository write plumbing only: create, read by key, update through a domain method and delete.
Contexts run on the EF in-memory provider through `DbContextOptionsFactory.BuildInMemoryOptions<T>(dbName)`
(fast, no relational constraints). `AuditId` is a required member; set `TenantId` so the tenant query filter admits
the seeded rows.

Search, filter and paging tests do not belong here. The in-memory provider evaluates predicates, string comparison
and paging in .NET, so such a test can pass for a query the database translates differently or cannot translate.
They run against the lane's real database in every testing profile ([test-templates-integration.md](test-templates-integration.md)
section Repository Integration Tests); constraint and migration coverage is in the same template, at `balanced`+.

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
