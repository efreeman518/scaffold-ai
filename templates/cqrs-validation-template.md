# CQRS Validation Template

Custom validators only (no FluentValidation) in `Application.Cqrs/Features/{Entity}/{Entity}CommandValidators.cs`; the result bridge lives in `Features/Shared/CqrsHandlerSupport.cs`.

```csharp
internal sealed class Create{Entity}CommandValidator(IRequestContext<string, Guid?> requestContext)
    : IRequestValidator<Create{Entity}Command>
{
    public Task<RequestValidationResult> ValidateAsync(Create{Entity}Command request, CancellationToken ct = default)
    {
        var dto = request.Request.Item;
        dto.TenantId = requestContext.TenantId ?? Guid.Empty; // stamp before validation, as the handler does
        return Task.FromResult(CqrsHandlerSupport.ToValidationResult({Entity}StructureValidator.ValidateCreate(dto)));
    }
}

// CqrsHandlerSupport: exhaustive, no discard arm
public static RequestValidationResult ToValidationResult<T>(Result<T> result) where T : notnull => result switch
{
    T => RequestValidationResult.Valid(),
    ValidationError v => RequestValidationResult.Failure(v.Issues),
    Error e => RequestValidationResult.Failure(e.Message),
};
```

Validators hold cheap shape checks; invariants stay in domain methods. `Registration/CqrsApplicationRegistration.cs` adds `services.AddScoped<IRequestValidator<Create{Entity}Command>, Create{Entity}CommandValidator>();` per validator, then one `AddDecoratedRequestHandlers` call ([../support/ef-packages-optional.md](../support/ef-packages-optional.md) section CQRS).
