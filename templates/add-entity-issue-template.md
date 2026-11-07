# Add-Entity Issue Template

GitHub issue form for requesting one entity vertical slice. It collects the inputs the vertical-slice Pre-Flight ([../support/vertical-slice-checklist.md](../support/vertical-slice-checklist.md)) would otherwise ask for, so an issue-driven run (an ecosystem feature loop, for one) can plan the slice without a question round, and an attended `/vertical-slice` session can start from the issue.

Copy the block below to `.github/ISSUE_TEMPLATE/add-entity.yml` in the app. The `feature` label keeps the request out of bug triage; move it to wherever the app's feature work starts (a project board column, for one).

```yaml
name: Add entity
description: Request one entity vertical slice (domain -> data -> application -> API -> tests).
title: "Add entity: "
labels: ["feature"]
body:
  - type: input
    id: entity
    attributes:
      label: Entity name
      description: Singular PascalCase, as it should appear in code and in .scaffold/UBIQUITOUS-LANGUAGE.md.
      placeholder: Invoice
    validations:
      required: true
  - type: dropdown
    id: kind
    attributes:
      label: Aggregate root or internal child (GR-15)
      description: A root has its own identity and lifecycle and gets the full slice. An internal child exists only inside one root; its writes go through the root.
      options:
        - Aggregate root
        - Internal child (1:N owned)
        - Internal child (M:N junction)
    validations:
      required: true
  - type: input
    id: parent
    attributes:
      label: Owning root (internal child only)
      description: Required when the kind is an internal child - the aggregate root that owns it. The slice stops and asks when it is missing.
      placeholder: Customer
  - type: textarea
    id: properties
    attributes:
      label: Properties
      description: One per line - name, type, required or optional, and any length, range or uniqueness rule.
      placeholder: |
        Number: string, required, unique per tenant, max 32
        DueDate: DateOnly, required
        Total: decimal, required, >= 0
    validations:
      required: true
  - type: textarea
    id: relationships
    attributes:
      label: Relationships
      description: Other entities it references by id, and child collections it owns.
  - type: textarea
    id: rules
    attributes:
      label: Domain rules and actions
      description: Invariants and custom actions beyond create, read, update and delete, with the outcome each one must produce.
  - type: textarea
    id: acceptance
    attributes:
      label: Acceptance checks
      description: 3-5 observable outcomes the tests must prove (endpoint behavior, rule enforcement, event emission).
    validations:
      required: true
  - type: textarea
    id: terms
    attributes:
      label: New domain terms or decisions
      description: Terms, roles, events or design decisions this entity introduces; they land in the .scaffold artifacts before the code.
```
