# Test Templates - Domain (Phase 5a)

| | |
|---|---|
| **Generates** | `tests/Test.Unit/Domain/{Entity}Tests.cs`, `tests/Test.Unit/Domain/{Entity}StatusTransitionTests.cs` (state machine only) |
| **Requires** | Entity shell from Phase 4 |
| **Phase** | 5a (Foundation TDD) |
| **Protocol** | Write these tests BEFORE implementing entity logic. See [../ai/tdd-protocol.md](../ai/tdd-protocol.md). |

## Test Naming Convention

Owned by [../skills/testing.md](../skills/testing.md) section Test Naming Convention. `Given_When_Then` is the
default; `<Subject>_<Condition>_<Outcome>` applies when a named member or structural fact is under test.

---

## Domain Entity Tests

### File: `tests/Test.Unit/Domain/{Entity}Tests.cs`

```csharp
[TestClass]
[TestCategory("Unit")]
public class {Entity}Tests
{
    [TestMethod]
    public void Given_ValidInput_When_EntityCreated_Then_ReturnsSuccess()
    {
        // Arrange & Act
        var result = {Entity}.Create(Guid.NewGuid(), "Valid Name");

        // Assert
        Assert.IsTrue(result.IsSuccess);
        Assert.IsNotNull(result.Value);
        Assert.AreEqual("Valid Name", result.Value.Name);
    }

    [TestMethod]
    [DataRow(null)]
    [DataRow("")]
    public void Given_EmptyName_When_EntityCreated_Then_ReturnsDomainFailure(string? name)
    {
        // Arrange & Act
        var result = {Entity}.Create(Guid.NewGuid(), name!);

        // Assert
        Assert.IsTrue(result.IsFailure);
        Assert.Contains("name", result.ErrorMessage!, StringComparison.OrdinalIgnoreCase);
    }

    [TestMethod]
    public void Given_ExistingEntity_When_Updated_Then_ReturnsUpdatedValues()
    {
        // Arrange
        var entity = {Entity}.Create(Guid.NewGuid(), "Original").Value!;

        // Act
        var result = entity.Update(name: "Updated");

        // Assert
        Assert.IsTrue(result.IsSuccess);
        Assert.AreEqual("Updated", result.Value!.Name);
    }

    [TestMethod]
    public void Given_NullUpdate_When_Updated_Then_OriginalValuesPreserved()
    {
        // Arrange
        var entity = {Entity}.Create(Guid.NewGuid(), "Original").Value!;

        // Act
        var result = entity.Update(name: null);

        // Assert
        Assert.IsTrue(result.IsSuccess);
        Assert.AreEqual("Original", result.Value!.Name);
    }

    [TestMethod]
    public void Given_ParentEntity_When_ChildAdded_Then_CollectionContainsChild()
    {
        // Arrange
        var entity = {Entity}.Create(Guid.NewGuid(), "Parent").Value!;
        var child = {ChildEntity}.Create(Guid.NewGuid(), "Child").Value!;

        // Act
        var result = entity.Add{ChildEntity}(child);

        // Assert
        Assert.IsTrue(result.IsSuccess);
        Assert.AreEqual(1, entity.{ChildEntities}.Count);
    }

    [TestMethod]
    public void Given_DuplicateChild_When_ChildAdded_Then_IdempotentReturnsExisting()
    {
        // Arrange
        var entity = {Entity}.Create(Guid.NewGuid(), "Parent").Value!;
        var child = {ChildEntity}.Create(Guid.NewGuid(), "Child").Value!;
        entity.Add{ChildEntity}(child);

        // Act - add same child again
        var result = entity.Add{ChildEntity}(child);

        // Assert - idempotent
        Assert.IsTrue(result.IsSuccess);
        Assert.AreEqual(1, entity.{ChildEntities}.Count);
    }
}
```

> **Child entity tests:** Include the `Add{ChildEntity}` and duplicate-child tests only when the entity has child collections defined in `.scaffold/resource-implementation.yaml`. Omit for leaf entities.

---

## Domain Rule Test## Transition Tests

### File: `tests/Test.Unit/Domain/{Entity}StatusTransitionTests.cs`

Only for an entity with a `stateMachine`. Drive the aggregate's `Transition`; one data row per allowed and per rejected pair from the spec.

```csharp
[TestClass]
[TestCategory("Unit")]
public class {Entity}StatusTransitionTests
{
    [TestMethod]
    [DataRow({Entity}Status.Open, {Entity}Status.InProgress)]
    public void Given_AllowedTransition_When_Transitioned_Then_StatusChanges({Entity}Status current, {Entity}Status target)
    {
        var entity = CreateAt(current);

        var result = entity.Transition(target);

        Assert.IsTrue(result.IsSuccess);
        Assert.AreEqual(target, entity.Status);
    }

    [TestMethod]
    [DataRow({Entity}Status.Open, {Entity}Status.Completed)]
    public void Given_RejectedTransition_When_Transitioned_Then_FailsAndKeepsStatus({Entity}Status current, {Entity}Status target)
    {
        var entity = CreateAt(current);

        var result = entity.Transition(target);

        Assert.IsTrue(result.IsFailure);
        Assert.AreEqual(current, entity.Status);
    }

    // Reaches the starting status only through allowed transitions.
    private static {Entity} CreateAt({Entity}Status status)
    {
        var entity = {Entity}.Create(Guid.NewGuid(), "Transition sample").Value!;
        {Entity}Status[] path = status switch
        {
            {Entity}Status.Open => [],
            {Entity}Status.InProgress => [{Entity}Status.InProgress],
            _ => throw new ArgumentOutOfRangeException(nameof(status), status, null)
        };
        foreach (var next in path)
            Assert.IsTrue(entity.Transition(next).IsSuccess);
        return entity;
    }
}
```

---

on (Phase 5a)

After entity `Create()` is implemented, activate the builder in `tests/Test.Support/Builders/{Entity}Builder.cs`:

```csharp
// Replace the Phase 4 shell:
public {Entity} Build() => null!;

// With the activated version:
public {Entity} Build()
{
    var result = {Entity}.Create(_tenantId, _name);
    return result.Value!;
}
```

This must happen in Phase 5a **after** entity logic is implemented, not before.
