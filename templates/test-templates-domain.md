# Test Templates - Domain (Phase 5a)

| | |
|---|---|
| **Generates** | `tests/Test.Unit/Domain/{Entity}Tests.cs`, `tests/Test.Unit/Domain/{Entity}StatusTransitionTests.cs` (state machine only) |
| **Requires** | Entity shell from Phase 4 |
| **Phase** | 5a (Foundation TDD) |
| **Protocol** | Write these tests BEFORE implementing entity logic. See [../ai/tdd-protocol.md](../ai/tdd-protocol.md). |

## Test Naming Convention

Owned by [../skills/testing.md](../skills/testing.md) section Test Naming Convention (`Given_When_Then` by default).
Result API: [../support/ef-packages-reference.md](../support/ef-packages-reference.md) section Domain Layer.
Success: `GetValueOrThrow()`; failure: `Assert.IsInstanceOfType<ValidationError>(result.Value)`.

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
        var result = {Entity}.Create(Guid.NewGuid(), "Valid Name");

        Assert.IsTrue(result.IsSuccess, result.ToString());
        Assert.AreEqual("Valid Name", result.GetValueOrThrow().Name);
    }

    [TestMethod]
    [DataRow(null)]
    [DataRow("")]
    public void Given_EmptyName_When_EntityCreated_Then_ReturnsDomainFailure(string? name)
    {
        var result = {Entity}.Create(Guid.NewGuid(), name!);

        var error = Assert.IsInstanceOfType<ValidationError>(result.Value);
        Assert.Contains("name", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [TestMethod]
    public void Given_ExistingEntity_When_Updated_Then_ReturnsUpdatedValues()
    {
        var entity = {Entity}.Create(Guid.NewGuid(), "Original").GetValueOrThrow();

        var result = entity.Update(name: "Updated");

        Assert.IsTrue(result.IsSuccess);
        Assert.AreEqual("Updated", result.GetValueOrThrow().Name);
    }

    [TestMethod]
    public void Given_NullUpdate_When_Updated_Then_OriginalValuesPreserved()
    {
        var entity = {Entity}.Create(Guid.NewGuid(), "Original").GetValueOrThrow();

        var result = entity.Update(name: null);

        Assert.IsTrue(result.IsSuccess);
        Assert.AreEqual("Original", result.GetValueOrThrow().Name);
    }

    [TestMethod]
    public void Given_ParentEntity_When_ChildAdded_Then_CollectionContainsChild()
    {
        var entity = {Entity}.Create(Guid.NewGuid(), "Parent").GetValueOrThrow();
        var child = {ChildEntity}.Create(Guid.NewGuid(), "Child").GetValueOrThrow();

        var result = entity.Add{ChildEntity}(child);

        Assert.IsTrue(result.IsSuccess);
        Assert.AreEqual(1, entity.{ChildEntities}.Count);
    }

    [TestMethod]
    public void Given_DuplicateChild_When_ChildAdded_Then_IdempotentReturnsExisting()
    {
        var entity = {Entity}.Create(Guid.NewGuid(), "Parent").GetValueOrThrow();
        var child = {ChildEntity}.Create(Guid.NewGuid(), "Child").GetValueOrThrow();
        entity.Add{ChildEntity}(child);

        var result = entity.Add{ChildEntity}(child);

        Assert.IsTrue(result.IsSuccess);
        Assert.AreEqual(1, entity.{ChildEntities}.Count);
    }
}
```

> **Child entity tests:** only for an entity with child collections in `.scaffold/resource-implementation.yaml`.

---

## Transition Tests

### File: `tests/Test.Unit/Domain/{Entity}StatusTransitionTests.cs`

Only for an entity with a `stateMachine`. Drive the aggregate's `Transition`; one data row per allowed and per rejected pair from the spec.

```csharp
[TestClass]
[TestCategory("Unit")]
public class {Entity}StatusTransitionTests
{
    private static readonly DateTimeOffset Now = new(2030, 1, 15, 12, 0, 0, TimeSpan.Zero);   // fixed clock, never UtcNow

    [TestMethod]
    [DataRow({Entity}Status.Open, {Entity}Status.InProgress)]
    public void Given_AllowedTransition_When_Transitioned_Then_StatusChanges({Entity}Status current, {Entity}Status target)
    {
        var entity = CreateAt(current);

        var result = entity.Transition(target, Now);

        Assert.IsTrue(result.IsSuccess);
        Assert.AreEqual(target, entity.Status);
    }

    [TestMethod]
    [DataRow({Entity}Status.Open, {Entity}Status.Completed)]
    public void Given_RejectedTransition_When_Transitioned_Then_FailsAndKeepsStatus({Entity}Status current, {Entity}Status target)
    {
        var entity = CreateAt(current);

        var result = entity.Transition(target, Now);

        Assert.IsInstanceOfType<RuleError>(result.Value);
        Assert.AreEqual(current, entity.Status);
    }

    // Reaches the starting status only through allowed transitions.
    private static {Entity} CreateAt({Entity}Status status)
    {
        var entity = {Entity}.Create(Guid.NewGuid(), "Transition sample").GetValueOrThrow();
        {Entity}Status[] path = status switch
        {
            {Entity}Status.Open => [],
            {Entity}Status.InProgress => [{Entity}Status.InProgress],
            _ => throw new ArgumentOutOfRangeException(nameof(status), status, null)
        };
        foreach (var next in path)
            Assert.IsTrue(entity.Transition(next, Now).IsSuccess);
        return entity;
    }
}
```

---

## Builder Activation (Phase 5a)

After entity `Create()` is implemented, activate the builder in `tests/Test.Support/Builders/{Entity}Builder.cs`:

```csharp
// Replace the Phase 4 shell:
public {Entity} Build() => null!;

// With the activated version:
public {Entity} Build() => {Entity}.Create(_tenantId, _name).GetValueOrThrow();
```

This must happen in Phase 5a **after** entity logic is implemented, not before.
