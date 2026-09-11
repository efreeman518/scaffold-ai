# Ontology Projection

`.scaffold/ontology/` is a generated, enterprise-facing view of `.scaffold/domain-specification.yaml`. It exists for glossary owners, analytics teams, and a Fabric IQ ontology that treats this application's domain as one module of a larger enterprise model. It is **not** a fourth binding artifact: GR-01 keeps the YAML as the source of truth, and this folder is regenerated from it.

## Purpose

- Give the business a readable concept map (Mermaid class diagram plus tables) that stays byte-consistent with the spec across sessions.
- Give a data and analytics platform a machine-readable layer (OWL/RDFS/SKOS in JSON-LD, Fabric IQ item-definition parts) without anyone hand-maintaining a second entity list.
- Carry the enterprise-facing enrichment the per-app DDD model lacks: namespace, ownership, is-a hierarchy, synonyms, alignment to upstream concepts.

## Opt-In

Presence of a top-level `ontology:` block in the spec turns the projection on; absence changes nothing. The interview owns the question ([../ai/shared-understanding-interview.md](../ai/shared-understanding-interview.md) section Enterprise Model Alignment Decision); the schema doc owns the fields ([../ai/domain-specification-schema.md](../ai/domain-specification-schema.md) section Enterprise Ontology Alignment (Optional)). Brownfield adoption asks the same question after its code passes and never infers the block from code.

## Outputs

All files are tracked, generated, and regenerated - never edited.

| Path | Content |
|---|---|
| `ontology.md` | Header comment with `sourceHash`; Overview, Diagram (Mermaid `classDiagram`), Concepts, Properties, Relationships, Enterprise Alignment, Glossary (Entities And Aggregates, Value Objects, States, Events, Policies And Rules), Generation Notes (hash, commands, warnings, omitted constructs). |
| `ontology.jsonld` | OWL/RDFS/SKOS graph. The `owl:Ontology` node carries `scaffold:sourceHash`. |
| `manifest.json` | `formatVersion`, `generator`, `sourceHash`, `ontologyIri`, and a sha256 per rendered file. |
| `fabric-iq/.platform`, `fabric-iq/definition.json` | Fabric IQ ontology item-definition root parts. |
| `fabric-iq/EntityTypes/{id}/definition.json` | One part per entity (join entities excluded). |
| `fabric-iq/RelationshipTypes/{id}/definition.json` | One part per relationship edge. |

`sourceHash` is the sha256 of the parsed spec re-serialized canonically, so comment and whitespace edits to the YAML are not drift. Output is UTF-8 without BOM, `\n` newlines, JSON with two-space indent and sorted keys.

## Generate

```powershell
python {instructionsRoot}/scripts/generate-ontology.py --root .
```

`{instructionsRoot}` is the installed instruction payload (`.instructions` in a scaffolded app), as in `START-AI.md`; the Python launcher follows [python-setup.md](python-setup.md) and the script needs `pyyaml`. Run it from the app root once the YAML is final at the Phase 1 gate, and again after every later edit to the spec (vertical slices, brownfield corrections). The script writes only changed bytes and prunes parts listed in the previous manifest that are no longer rendered, when their on-disk hash still matches the manifest; it never deletes files it did not list. Output is a pure function of the spec: the same YAML always yields the same bytes.

Warnings (`[warn] ...`) are printed and echoed into `ontology.md` section Generation Notes; `--strict` turns any warning into exit 1.

## Check

```powershell
python {instructionsRoot}/scripts/generate-ontology.py --root . --check
```

Renders in memory and compares with disk after `\r\n` normalization, so autocrlf clones do not false-flag. Exit codes:

| Exit | Meaning |
|---|---|
| 0 | Generated, up to date, or skipped (no `ontology:` block and no `.scaffold/ontology/`). |
| 1 | `--check` found drift (`spec changed` when `sourceHash` moved, otherwise the differing file); `--strict` with warnings; or `ontology:` was removed while `.scaffold/ontology/` still exists (remove the folder or restore the block). |
| 2 | Invalid spec or environment: missing `namespace`, unknown `extends`, `extends` cycle, a property and a relationship sharing a name on one entity, a flattened value-object field colliding with a declared property, a Fabric id collision, or `pyyaml` absent. |

The `--check` form is the currency check in `HANDOFF.md`, the Phase 1 -> 2 gate, and the final scaffold checklist.

## Projection Mapping

| Spec | JSON-LD | Fabric IQ | Mermaid |
|---|---|---|---|
| entity | `owl:Class` with `rdfs:label`, `skos:definition`, `scaffold:aggregateRole` (derived per the schema doc, or pinned), `scaffold:tenantScoped`, `scaffold:systemOfRecord` | EntityType; synthesized `Id` (`entityIdParts`) and `TenantId` when tenant-scoped unless declared; `displayNamePropertyId` = first of `Name`/`Title`/`DisplayName`, else first required string, else `Id` | `class E { <<root>> }` - stereotypes `root`, `owned-child`, `join`, `inherited`, `value-object`, `external` |
| `extends` | `rdfs:subClassOf` | `baseEntityTypeId`; the subtype emits only its own properties | `Base <\|-- E` |
| property | `owl:DatatypeProperty` + `owl:FunctionalProperty`, `rdfs:range` xsd (`string`/`text`/`enum`/`flags_enum`/`identifier` -> `xsd:string`; `number`/`money` -> `xsd:decimal`; `date` -> `xsd:dateTime`; `boolean` -> `xsd:boolean`), `scaffold:sourceKind`, `scaffold:required`, `scaffold:pii` from `sensitive` | `valueType` `String`/`Double`/`DateTime`/`Boolean` (`money` -> `Double` with a warning: the Fabric graph has no Decimal); `customAttributes` carry `iri`, `sourceKind`, `required`, `pii`, `allowedValues` | `+kind Name` member |
| enum values, state-machine states | `skos:ConceptScheme` `{ns}E/P/values` with one `skos:Concept` per value; `scaffold:initialState`, `scaffold:terminal` | `allowedValues` on the property | tables only |
| value object | `owl:Class` (`scaffold:conceptKind value-object`); fields as datatype properties; the using property is a functional `owl:ObjectProperty` | no EntityType; fields flattened onto each using entity as `{Property}{Field}` with `valueObject`/`valueObjectField` attributes | `class VO { <<value-object>> }`, `E --> VO : prop` |
| one-to-many, one-to-one | `owl:ObjectProperty` `{ns}S/relName`, domain S, range T (functional for one-to-one); cardinality, cascade, predicate, kind as `scaffold:*` | RelationshipType `S_relName`, source S, target T; cardinality, cascade, predicate, `targetRole` in `customAttributes` | `S "1" *-- "*" T : label` |
| many-to-many | as above with `*`/`*`; the join entity (pinned `aggregateRole: join`, or named `S+T`/`T+S` with both `{X}Id` identifiers) is `scaffold:joinEntity` and keeps its class | one edge with `joinEntity`; the join entity gets no EntityType (its rows are the edge a Contextualization binds); extra join properties warn | `S "*" --> "*" T`, `J ..> S`, `J ..> T` |
| self-referencing | domain = range = S, `scaffold:selfReferenceKey` | edge with source = target | `S "0..1" *-- "*" S` |
| polymorphic-join | one object property per declaring entity in `polymorphicEntityTypes` | one edge per declaring entity (`TaskItem_Attachments`, `Comment_Attachments`) | `D "1" --> "*" T` |
| navigation | functional `owl:ObjectProperty`; `owl:inverseOf` the child relationship when unambiguously paired (one navigation on T back to S, one child relationship S -> T) | paired: folded into the child edge as `targetRole`; unpaired: its own edge `D_navName` | paired omitted; unpaired `D "*" --> "1" T` |
| `predicate` | `rdfs:label`, `scaffold:predicate` | `customAttributes.predicate` and the edge description | edge label |
| `synonyms`, `owner`, `systemOfRecord` | `skos:altLabel`, `scaffold:owner`, `scaffold:systemOfRecord` | `semanticEnrichment.synonyms`, `customAttributes` | omitted |
| `alignment.equivalentTo` / `specializes` | `owl:equivalentClass` / `rdfs:subClassOf` to the external IRI plus a stub `owl:Class` with `rdfs:isDefinedBy` | `customAttributes.equivalentTo` / `specializes` | `E .. Ext_X : specializes` to `class Ext_X["prefix:X"] { <<external>> }` |
| `alignsWith[]` | context prefix per entry; `dcterms:references` on the ontology node | omitted | Enterprise Alignment table |
| entity `rules`, `domainRules` | `skos:note` on the class | omitted | Policies And Rules table |
| events | `owl:Class` under `scaffold:DomainEvent` with `scaffold:raisedBy`, `scaffold:trigger`, `scaffold:payloadField` | omitted | Events table |
| workflows, policy matrices, AI capabilities, custom actions, keys outside the schema | omitted, counted in Generation Notes | omitted | omitted |

Annotation vocabulary (`aggregateRole`, `systemOfRecord`, `pii`, ...) lives in one fixed namespace `urn:scaffold-ai:ontology-meta#` (prefix `scaffold:`) shared by every app, so a merged enterprise graph has one IRI per annotation.

Identity is deterministic. Concept IRI `{namespace}{Name}`; member IRI `{namespace}{Owner}/{Member}` (properties and relationships share one member space per entity); value scheme `{namespace}{Owner}/{Prop}/values`. Fabric ids are the first 8 bytes of sha256 over the IRI, masked to a positive 64-bit integer, in one registry across entity types, properties, and relationship types. Reordering, descriptions, predicates, synonyms, and alignments never move an id; renaming a concept or changing the namespace does, by design. Every Fabric object carries its `iri` in `customAttributes` so an enterprise merge can re-run the same check.

## Fabric IQ Ingestion

`fabric-iq/` is the parts folder of a Fabric IQ ontology item definition. The platform team imports it with the Fabric REST Create Item (or Update Item Definition) call, base64-encoding each part as `InlineBase64`, or through Git integration when the tenant supports the item type. An alternative path is the Ontology Playground: load the JSON-LD as RDF and export the Fabric format from there. Data bindings and contextualizations (which lakehouse table feeds which entity type or edge) are the platform team's step and need workspace and lakehouse ids this repo never holds; the generator emits none. Inheritance semantics for `baseEntityTypeId` are taken from the REST reference; the first real import confirms whether the subtype must restate `Id`, and the fix is local to the Fabric emitter.

## Rules

- Regenerate, never edit. Any hand change is caught by `--check` in HANDOFF currency, the Phase 1 gate, and the final checklist.
- No classification taxonomy in Phase 1: `sensitive` exports as `pii`, nothing more. Graded classification stays a Phase 2 compliance concern.
- Minimum viable scaffold and api-only scaffolds answer `no` to the opt-in question and never declare `ontology:`.
- Rejected synonyms recorded in `.scaffold/UBIQUITOUS-LANGUAGE.md` are never exported; `synonyms[]` holds accepted alternates only.
- When a later phase edits the spec (vertical slice, brownfield correction), regenerate in the same session so the projection never lags the YAML.
