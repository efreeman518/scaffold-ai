#!/usr/bin/env python3
"""
Project `.scaffold/domain-specification.yaml` into `.scaffold/ontology/`.

GR-01 makes the Phase 1 domain spec the binding source of truth. When the spec
declares a top-level `ontology:` block (opt-in), this script renders a
deterministic, enterprise-facing projection of it:

  ontology.md        human doc: Mermaid classDiagram, concept / property /
                     relationship tables, glossary, generation notes
  ontology.jsonld    OWL / RDFS / SKOS graph (JSON-LD)
  manifest.json      format version, sourceHash, per-file sha256
  fabric-iq/         Microsoft Fabric IQ ontology item-definition parts
                     (.platform, definition.json, EntityTypes/{id}/definition.json,
                     RelationshipTypes/{id}/definition.json)

The projection is generated, never edited. Owner doc: support/ontology-projection.md.

Usage (from a scaffolded app root):
    python .instructions/scripts/generate-ontology.py [--root .] [--check] [--strict]

Exit codes:
  0  generated, up to date, or skipped (no `ontology:` block and no output dir)
  1  --check found drift; --strict with warnings; `ontology:` absent while
     `.scaffold/ontology/` exists
  2  invalid spec or environment (missing namespace, unknown extends, cycle,
     id or member collision, flattened-name collision, pyyaml absent)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SPEC_PATH = Path(".scaffold") / "domain-specification.yaml"
OUTPUT_ROOT = Path(".scaffold") / "ontology"
FORMAT_VERSION = 1
GENERATOR = "scaffold-ai scripts/generate-ontology.py"
GENERATE_CMD = "python {instructionsRoot}/scripts/generate-ontology.py --root ."
# One annotation vocabulary shared by every app so a merged enterprise graph has one IRI per annotation.
META_NS = "urn:scaffold-ai:ontology-meta#"
FABRIC_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,127}$")
FABRIC_VALUE_TYPE = {
    "string": "String", "text": "String", "enum": "String", "flags_enum": "String",
    "identifier": "String", "number": "Double", "money": "Double",
    "date": "DateTime", "boolean": "Boolean",
}
XSD_RANGE = {
    "string": "xsd:string", "text": "xsd:string", "enum": "xsd:string", "flags_enum": "xsd:string",
    "identifier": "xsd:string", "number": "xsd:decimal", "money": "xsd:decimal",
    "date": "xsd:dateTime", "boolean": "xsd:boolean",
}
CARDINALITY = {
    "one-to-many": ("1", "*"), "one-to-one": ("1", "1"), "many-to-many": ("*", "*"),
    "self-referencing": ("0..1", "*"), "polymorphic-join": ("1", "*"),
}
PREFIXES = {
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dcterms": "http://purl.org/dc/terms/",
    "scaffold": META_NS,
}
KNOWN_TOP_KEYS = {
    "ProjectName", "ProjectDescription", "OrganizationName", "projectNamePrefix", "multiTenant",
    "tenantIsolation", "globalAdminRole", "authProvider", "authScenario", "entities", "valueObjects",
    "domainRules", "events", "workflows", "policyMatrices", "aiCapabilities", "ontology",
}
DISPLAY_NAME_CANDIDATES = ("Name", "Title", "DisplayName")
PAIRABLE_KINDS = ("one-to-many", "one-to-one", "self-referencing")


class SpecError(Exception):
    """Invalid spec or environment - exit 2."""


@dataclass
class Prop:
    owner: str
    name: str
    kind: str
    required: bool
    description: str
    sensitive: bool
    values: list[str]
    value_object: str | None
    iri: str
    scheme_iri: str | None = None


@dataclass
class Concept:
    name: str
    iri: str
    kind: str                       # entity | value-object
    description: str
    role: str                       # root | owned-child | join | inherited | value-object
    extends: str | None
    synonyms: list[str]
    owner: str | None
    system_of_record: bool
    alignment: dict
    tenant_scoped: bool
    props: list[Prop] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    state_machine: dict | None = None
    aggregate_parent: str | None = None
    used_by: list[dict] = field(default_factory=list)


@dataclass
class Relation:
    source: str
    target: str
    name: str
    rel_kind: str
    iri: str
    cardinality: tuple[str, str]
    cascade: bool | None
    predicate: str | None
    self_key: str | None
    poly_types: list[str]
    join_entity: str | None = None
    target_role: str | None = None      # paired navigation name on the target


@dataclass
class Navigation:
    source: str
    target: str
    name: str
    iri: str
    required: bool
    predicate: str | None
    paired: Relation | None = None


@dataclass
class EnumScheme:
    iri: str
    owner: str
    prop: str
    values: list[str]
    initial: str | None = None
    terminals: list[str] = field(default_factory=list)
    is_state_machine: bool = False


@dataclass
class Event:
    name: str
    iri: str
    raised_by: str
    trigger: str
    payload: list[str]


@dataclass
class External:
    iri: str
    namespace: str | None
    prefix: str | None
    local: str


@dataclass
class Model:
    project: str
    description: str
    namespace: str
    ontology_iri: str
    bounded_context: str
    owner: str | None
    aligns_with: list[dict]
    prefix: str
    source_hash: str
    concepts: dict[str, Concept] = field(default_factory=dict)
    relations: list[Relation] = field(default_factory=list)
    navigations: list[Navigation] = field(default_factory=list)
    schemes: list[EnumScheme] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    externals: dict[str, External] = field(default_factory=dict)
    domain_rules: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    omitted: dict[str, int] = field(default_factory=dict)
    fabric_entity_types: list[dict] = field(default_factory=list)
    fabric_relationship_types: list[dict] = field(default_factory=list)

    def entities(self) -> list[Concept]:
        return [c for c in self.concepts.values() if c.kind == "entity"]

    def value_objects(self) -> list[Concept]:
        return [c for c in self.concepts.values() if c.kind == "value-object"]


# --- Loading and identity ----------------------------------------------------

def load_spec(path: Path) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SpecError("pyyaml is required (pip install pyyaml); see support/python-setup.md") from exc
    if not path.is_file():
        raise SpecError(f"spec not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise SpecError(f"{path} must be a YAML mapping")
    return data


def spec_hash(spec: dict) -> str:
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fabric_id(iri: str) -> str:
    digest = hashlib.sha256(iri.encode("utf-8")).digest()[:8]
    return str((int.from_bytes(digest, "big") & 0x7FFF_FFFF_FFFF_FFFF) or 1)


class IdRegistry:
    """One id space across entity types, properties, and relationship types."""

    def __init__(self) -> None:
        self._by_id: dict[str, str] = {}

    def id_for(self, iri: str) -> str:
        fid = fabric_id(iri)
        other = self._by_id.get(fid)
        if other is not None and other != iri:
            raise SpecError(f"Fabric id collision: '{iri}' and '{other}' both hash to {fid}; rename one")
        self._by_id[fid] = iri
        return fid


def ns_prefix(namespace: str, fallback: str) -> str:
    segment = namespace.rstrip("/#").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    segment = re.sub(r"[^A-Za-z0-9_]", "_", segment).strip("_")
    if not segment or not segment[0].isalpha():
        segment = re.sub(r"[^A-Za-z0-9_]", "", fallback) or "ns"
    return segment.lower()


def _unique_prefix(candidate: str, used: set[str]) -> str:
    prefix, n = candidate, 2
    while prefix in used:
        prefix = f"{candidate}{n}"
        n += 1
    used.add(prefix)
    return prefix


def _rule_text(rule: dict) -> str:
    name = str(rule.get("name") or "").strip()
    condition = str(rule.get("condition") or "").strip()
    return f"{name}: {condition}" if condition else name


def _seg(name: str) -> str:
    """IRI path segment; PascalCase names pass through unchanged."""
    return quote(name, safe="")


# --- Model -------------------------------------------------------------------

def build_model(spec: dict) -> Model:
    block = spec.get("ontology")
    if not isinstance(block, dict) or not str(block.get("namespace") or "").strip():
        raise SpecError("ontology.namespace is required (IRI base ending in / or #)")
    warnings: list[str] = []
    ns = str(block["namespace"]).strip()
    if not ns.endswith(("/", "#")):
        warnings.append(f"ontology.namespace '{ns}' lacks a trailing / or #; '/' appended")
        ns += "/"
    project = str(spec.get("ProjectName") or "Domain")
    used_prefixes = set(PREFIXES)
    aligns_with: list[dict] = []
    for item in block.get("alignsWith") or []:
        if not isinstance(item, dict) or not item.get("namespace"):
            raise SpecError("ontology.alignsWith entries need name and namespace")
        upstream_ns = str(item["namespace"])
        aligns_with.append({
            "name": str(item.get("name") or upstream_ns),
            "namespace": upstream_ns,
            "prefix": _unique_prefix(ns_prefix(upstream_ns, str(item.get("name") or "upstream")), used_prefixes),
        })
    m = Model(
        project=project,
        description=str(spec.get("ProjectDescription") or ""),
        namespace=ns,
        ontology_iri=ns.rstrip("/#"),
        bounded_context=str(block.get("boundedContext") or project),
        owner=str(block["owner"]) if block.get("owner") else None,
        aligns_with=aligns_with,
        prefix=_unique_prefix(ns_prefix(ns, project), used_prefixes),
        source_hash=spec_hash(spec),
        warnings=warnings,
    )

    entities = [e for e in spec.get("entities") or [] if isinstance(e, dict) and e.get("name")]
    value_objects = [v for v in spec.get("valueObjects") or [] if isinstance(v, dict) and v.get("name")]
    entity_names = [str(e["name"]) for e in entities]
    vo_names = [str(v["name"]) for v in value_objects]
    all_names = entity_names + vo_names
    if len(set(all_names)) != len(all_names):
        raise SpecError("entity and value-object names must be unique across the spec")
    multi_tenant = bool(spec.get("multiTenant", True))

    for e in entities:
        name = str(e["name"])
        ext = e.get("extends")
        if ext is not None and str(ext) not in entity_names:
            raise SpecError(f"entity {name}: extends '{ext}' is not an entity in this file")
        m.concepts[name] = Concept(
            name=name, iri=ns + name, kind="entity", description=str(e.get("description") or ""), role="",
            extends=str(ext) if ext is not None else None,
            synonyms=[str(s) for s in e.get("synonyms") or []],
            owner=str(e["owner"]) if e.get("owner") else None,
            system_of_record=bool(e.get("systemOfRecord", True)),
            alignment=dict(e.get("alignment") or {}),
            tenant_scoped=multi_tenant and bool(e.get("isTenantEntity", True)),
            rules=[_rule_text(r) for r in e.get("rules") or [] if isinstance(r, dict)],
            state_machine=e.get("stateMachine") if isinstance(e.get("stateMachine"), dict) else None,
            aggregate_parent=str(e["aggregateParent"]) if e.get("aggregateParent") else None,
        )
    for name in entity_names:
        chain: list[str] = []
        cur: str | None = name
        while cur is not None:
            if cur in chain:
                raise SpecError(f"extends cycle: {' -> '.join(chain + [cur])}")
            chain.append(cur)
            cur = m.concepts[cur].extends

    for v in value_objects:
        c = Concept(
            name=str(v["name"]), iri=ns + str(v["name"]), kind="value-object",
            description=str(v.get("description") or ""), role="value-object", extends=None,
            synonyms=[str(s) for s in v.get("synonyms") or []], owner=None, system_of_record=True,
            alignment=dict(v.get("alignment") or {}), tenant_scoped=False,
            rules=[_rule_text(r) for r in v.get("rules") or [] if isinstance(r, dict)],
            used_by=[u for u in v.get("usedBy") or [] if isinstance(u, dict)],
        )
        for f in v.get("fields") or []:
            kind = str(f.get("kind") or "string")
            if kind not in FABRIC_VALUE_TYPE:
                raise SpecError(f"{c.name}.{f.get('name')}: unknown field kind '{kind}'")
            prop = Prop(owner=c.name, name=str(f["name"]), kind=kind, required=bool(f.get("required", False)),
                        description=str(f.get("description") or ""), sensitive=False,
                        values=[str(x) for x in f.get("values") or []], value_object=None,
                        iri=f"{c.iri}/{_seg(str(f['name']))}")
            if prop.values:
                m.schemes.append(EnumScheme(iri=f"{prop.iri}/values", owner=c.name, prop=prop.name, values=list(prop.values)))
                prop.scheme_iri = f"{prop.iri}/values"
            c.props.append(prop)
        m.concepts[c.name] = c

    owners: dict[str, list[str]] = {}
    for e in entities:
        c = m.concepts[str(e["name"])]
        members: set[str] = set()

        def claim(member: str, c: Concept = c, members: set[str] = members) -> None:
            if member in members:
                raise SpecError(f"entity {c.name}: '{member}' is declared more than once across properties, children and navigation")
            members.add(member)

        for p in e.get("properties") or []:
            pname = str(p["name"])
            claim(pname)
            kind = str(p.get("kind") or "string")
            if kind != "value_object" and kind not in FABRIC_VALUE_TYPE:
                raise SpecError(f"{c.name}.{pname}: unknown kind '{kind}'")
            prop = Prop(owner=c.name, name=pname, kind=kind, required=bool(p.get("required", False)),
                        description=str(p.get("description") or ""), sensitive=bool(p.get("sensitive", False)),
                        values=[str(x) for x in p.get("values") or []],
                        value_object=str(p["valueObject"]) if p.get("valueObject") else None, iri=f"{c.iri}/{_seg(pname)}")
            if kind == "value_object" and prop.value_object not in vo_names:
                raise SpecError(f"{c.name}.{pname}: valueObject '{prop.value_object}' is not defined under valueObjects")
            if kind in ("enum", "flags_enum") and prop.values:
                m.schemes.append(EnumScheme(iri=f"{prop.iri}/values", owner=c.name, prop=pname, values=list(prop.values)))
                prop.scheme_iri = f"{prop.iri}/values"
            c.props.append(prop)
        _merge_state_machine(m, c)

        for ch in e.get("children") or []:
            rname = str(ch["name"])
            claim(rname)
            target = str(ch["entity"])
            rel_kind = str(ch.get("relationship") or "")
            if rel_kind not in CARDINALITY:
                raise SpecError(f"{c.name}.{rname}: unknown relationship '{rel_kind}'")
            if target not in entity_names:
                raise SpecError(f"{c.name}.{rname}: entity '{target}' is not defined")
            base = dict(name=rname, rel_kind=rel_kind, cardinality=CARDINALITY[rel_kind],
                        cascade=ch.get("cascadeDelete"), predicate=ch.get("predicate"),
                        self_key=ch.get("selfReferenceKey"),
                        poly_types=[str(x) for x in ch.get("polymorphicEntityTypes") or []])
            if rel_kind == "polymorphic-join":
                declaring = base["poly_types"] or [c.name]
                if c.name not in declaring:
                    m.warnings.append(f"{c.name}.{rname}: polymorphic-join declared on {c.name} but polymorphicEntityTypes lists {', '.join(declaring)}")
                for d in declaring:
                    if d not in entity_names:
                        raise SpecError(f"{c.name}.{rname}: polymorphicEntityTypes '{d}' is not defined")
                    iri = f"{ns}{d}/{_seg(rname)}"
                    if any(r.iri == iri for r in m.relations):
                        continue  # same polymorphic child declared on several owners
                    m.relations.append(Relation(source=d, target=target, iri=iri, **base))
                continue
            if rel_kind == "self-referencing" and target != c.name:
                m.warnings.append(f"{c.name}.{rname}: self-referencing relationship targets '{target}'; projected onto {c.name}")
                target = c.name
            m.relations.append(Relation(source=c.name, target=target, iri=f"{c.iri}/{_seg(rname)}", **base))
            if rel_kind in ("one-to-many", "one-to-one"):
                owners.setdefault(target, []).append(c.name)

        for nv in e.get("navigation") or []:
            nname = str(nv["name"])
            claim(nname)
            target = str(nv["entity"])
            if target not in entity_names:
                raise SpecError(f"{c.name}.{nname}: navigation entity '{target}' is not defined")
            m.navigations.append(Navigation(source=c.name, target=target, name=nname, iri=f"{c.iri}/{_seg(nname)}",
                                            required=bool(nv.get("required", False)), predicate=nv.get("predicate")))

    for e in entities:
        c = m.concepts[str(e["name"])]
        parents = owners.get(c.name, [])
        if len(parents) > 1:
            m.warnings.append(f"{c.name}: owned child of more than one parent ({', '.join(parents)}); pin aggregateRole and aggregateParent")
        pinned = e.get("aggregateRole")
        if pinned:
            c.role = str(pinned)
            if c.role in ("owned-child", "join") and not c.aggregate_parent and parents:
                c.aggregate_parent = parents[0]
        elif parents:
            c.role, c.aggregate_parent = "owned-child", parents[0]
        elif c.extends:
            c.role = "inherited"
        else:
            c.role = "root"

    for r in m.relations:
        if r.rel_kind != "many-to-many":
            continue
        r.join_entity = _find_join(m, r, entity_names)
        if r.join_entity:
            join = m.concepts[r.join_entity]
            join.role = "join"
            join.aggregate_parent = join.aggregate_parent or r.source
    for c in m.entities():
        if c.role != "join":
            continue
        matched = [r for r in m.relations if r.join_entity == c.name]
        if not matched:
            m.warnings.append(f"join entity {c.name} matches no many-to-many relationship; it keeps an OWL class and gets no Fabric IQ EntityType")
            continue
        expected = {f"{matched[0].source}Id", f"{matched[0].target}Id", "Id", "TenantId"}
        extra = [p.name for p in c.props if p.name not in expected]
        if extra:
            m.warnings.append(f"join entity {c.name}: properties {', '.join(extra)} are not projected to Fabric IQ (the edge carries no properties)")

    for nv in m.navigations:
        candidates = [r for r in m.relations if r.rel_kind in PAIRABLE_KINDS and r.source == nv.target and r.target == nv.source]
        siblings = [n for n in m.navigations if n.source == nv.source and n.target == nv.target]
        if len(candidates) == 1 and len(siblings) == 1 and candidates[0].target_role is None:
            nv.paired = candidates[0]
            candidates[0].target_role = nv.name
        elif candidates:
            m.warnings.append(f"{nv.source}.{nv.name}: ambiguous inverse of {nv.target} children ({', '.join(r.name for r in candidates)}); left unpaired")

    for vo in m.value_objects():
        declared = {(str(u.get("entity")), str(u.get("property"))) for u in vo.used_by}
        actual = {(c.name, p.name) for c in m.entities() for p in c.props if p.kind == "value_object" and p.value_object == vo.name}
        for ent, prop in sorted(declared - actual):
            m.warnings.append(f"value object {vo.name}: usedBy {ent}.{prop} does not match a kind: value_object property")
        for ent, prop in sorted(actual - declared):
            m.warnings.append(f"value object {vo.name}: used by {ent}.{prop} but not listed in usedBy")

    for rule in spec.get("domainRules") or []:
        if not isinstance(rule, dict):
            continue
        m.domain_rules.append(rule)
        for target in rule.get("appliesTo") or []:
            c = m.concepts.get(str(target))
            if c is None or c.kind != "entity":
                m.warnings.append(f"domain rule {rule.get('name')}: appliesTo '{target}' is not a defined entity")

    for ev in spec.get("events") or []:
        if not isinstance(ev, dict) or not ev.get("name"):
            continue
        name = str(ev["name"])
        if name in m.concepts:
            raise SpecError(f"event {name} collides with a concept of the same name")
        raised = str(ev.get("raisedBy") or "")
        if raised not in entity_names:
            m.warnings.append(f"event {name}: raisedBy '{raised}' is not a defined entity")
        m.events.append(Event(name=name, iri=ns + name, raised_by=raised, trigger=str(ev.get("trigger") or ""),
                              payload=[str(x) for x in ev.get("payload") or []]))

    for c in m.concepts.values():
        for key in ("equivalentTo", "specializes"):
            iri = c.alignment.get(key)
            if not iri:
                continue
            iri = str(iri)
            match = next((a for a in m.aligns_with if iri.startswith(a["namespace"])), None)
            if match is None:
                m.warnings.append(f"{c.name}: alignment.{key} '{iri}' is outside every ontology.alignsWith namespace")
                local = iri.rstrip("/#").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                m.externals.setdefault(iri, External(iri=iri, namespace=None, prefix=None, local=local))
            else:
                m.externals.setdefault(iri, External(iri=iri, namespace=match["namespace"], prefix=match["prefix"],
                                                     local=iri[len(match["namespace"]):]))

    def omitted(label: str, count: int) -> None:
        if count:
            m.omitted[label] = count

    omitted("workflows", len(spec.get("workflows") or []))
    omitted("policyMatrices", len(spec.get("policyMatrices") or []))
    ai = spec.get("aiCapabilities") or {}
    if isinstance(ai, dict):
        omitted("aiCapabilities.search", len(ai.get("search") or []))
        omitted("aiCapabilities.agentWorkflows", len(ai.get("agentWorkflows") or []))
    omitted("customActions", sum(len(e.get("customActions") or []) for e in entities))
    for key in spec:
        if key not in KNOWN_TOP_KEYS:
            m.omitted[f"top-level '{key}'"] = 1

    _build_fabric(m)
    return m


def _merge_state_machine(m: Model, c: Concept) -> None:
    sm = c.state_machine
    if not sm or not sm.get("field"):
        return
    field_name = str(sm["field"])
    states = [str(s) for s in sm.get("states") or []]
    scheme = next((s for s in m.schemes if s.owner == c.name and s.prop == field_name), None)
    from_enum = scheme is not None
    if scheme is None:
        scheme = EnumScheme(iri=f"{c.iri}/{_seg(field_name)}/values", owner=c.name, prop=field_name, values=[])
        m.schemes.append(scheme)
        target = next((p for p in c.props if p.name == field_name), None)
        if target is None:
            m.warnings.append(f"{c.name}: stateMachine field '{field_name}' is not a declared property")
        else:
            target.scheme_iri = scheme.iri
    for s in states:
        if s not in scheme.values:
            if from_enum:
                m.warnings.append(f"{c.name}.{field_name}: state '{s}' is not among the enum values; added to the value scheme")
            scheme.values.append(s)
    scheme.is_state_machine = True
    scheme.initial = str(sm["initial"]) if sm.get("initial") is not None else None
    outgoing = {str(t.get("from")) for t in sm.get("transitions") or [] if isinstance(t, dict)}
    scheme.terminals = [s for s in states if s not in outgoing]


def _find_join(m: Model, r: Relation, entity_names: list[str]) -> str | None:
    by_name = (r.source + r.target, r.target + r.source)
    needed = {f"{r.source}Id", f"{r.target}Id"}
    for name in entity_names:
        c = m.concepts[name]
        ids = {p.name for p in c.props if p.kind == "identifier"}
        pinned = c.role == "join" and (c.aggregate_parent in (r.source, r.target) or name in by_name)
        if (pinned or name in by_name) and needed <= ids:
            return name
        if pinned and name in by_name:
            return name
    return None


def _stringify(attrs: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in attrs.items():
        if v is None:
            continue
        out[k] = ("true" if v else "false") if isinstance(v, bool) else str(v)
    return out


def _enrichment(description: str, attrs: dict, synonyms: list[str] | None = None) -> dict:
    out: dict[str, object] = {"customAttributes": _stringify(attrs)}
    if description:
        out["description"] = description
    if synonyms is not None:
        out["synonyms"] = list(synonyms)
    return out


def _build_fabric(m: Model) -> None:
    reg = IdRegistry()
    type_ids = {c.name: reg.id_for(c.iri) for c in m.entities() if c.role != "join"}
    prop_types: dict[str, set[str]] = {}
    schemes = {s.iri: s for s in m.schemes}

    def check_name(label: str, name: str, display: str | None = None) -> None:
        if not FABRIC_NAME_RE.match(name):
            m.warnings.append(f"Fabric IQ: {label} '{display or name}' does not match {FABRIC_NAME_RE.pattern}; emitted as-is")

    for c in m.entities():
        if c.name not in type_ids:
            continue  # join entities: their rows are the edge, not an EntityType
        check_name("entity type name", c.name)
        props: list[dict] = []
        entries: list[tuple[str, str, str, bool, bool]] = []  # name, id, valueType, required, synthesized
        names = {p.name for p in c.props}

        def add(name: str, iri: str, value_type: str, description: str, attrs: dict, synthesized: bool = False) -> str:
            pid = reg.id_for(iri)
            props.append({
                "id": pid, "name": name, "redefines": None, "baseTypeNamespaceType": None, "valueType": value_type,
                "semanticEnrichment": _enrichment(description, {"iri": iri, **attrs}),
            })
            entries.append((name, pid, value_type, bool(attrs.get("required")), synthesized))
            prop_types.setdefault(name, set()).add(value_type)
            check_name("property name", name, f"{c.name}.{name}")
            return pid

        id_prop_id: str | None = None
        if c.extends is None:
            if "Id" not in names:
                id_prop_id = add("Id", f"{c.iri}/Id", "String", f"Identity of {c.name} (synthesized).",
                                 {"sourceKind": "identifier", "required": True, "synthesized": True}, synthesized=True)
            if c.tenant_scoped and "TenantId" not in names:
                add("TenantId", f"{c.iri}/TenantId", "String", "Tenant scope (synthesized).",
                    {"sourceKind": "identifier", "required": True, "synthesized": True}, synthesized=True)
        for p in c.props:
            if p.kind == "value_object":
                vo = m.concepts[p.value_object]
                for f in vo.props:
                    flat = f"{p.name}{f.name}"
                    if flat in names:
                        raise SpecError(f"{c.name}: flattened value-object field '{flat}' collides with a declared property")
                    names.add(flat)
                    if f.kind == "money":
                        m.warnings.append(f"Fabric IQ: {c.name}.{flat} money -> Double (Decimal is unsupported in the Fabric graph)")
                    attrs = {"sourceKind": f.kind, "required": p.required and f.required, "valueObject": vo.name, "valueObjectField": f.name}
                    if f.values:
                        attrs["allowedValues"] = ",".join(f.values)
                    add(flat, f"{p.iri}/{_seg(f.name)}", FABRIC_VALUE_TYPE[f.kind],
                        f.description or f"{vo.name}.{f.name} flattened onto {c.name}.{p.name}.", attrs)
                continue
            if p.kind == "money":
                m.warnings.append(f"Fabric IQ: {c.name}.{p.name} money -> Double (Decimal is unsupported in the Fabric graph)")
            attrs = {"sourceKind": p.kind, "required": p.required}
            if p.sensitive:
                attrs["pii"] = True
            if p.scheme_iri and schemes[p.scheme_iri].values:
                attrs["allowedValues"] = ",".join(schemes[p.scheme_iri].values)
            pid = add(p.name, p.iri, FABRIC_VALUE_TYPE[p.kind], p.description, attrs)
            if p.name == "Id" and c.extends is None:
                id_prop_id = pid

        by_name = {name: pid for name, pid, _t, _r, _s in entries}
        display = next((by_name[n] for n in DISPLAY_NAME_CANDIDATES if n in by_name), None)
        if display is None:
            display = next((pid for _n, pid, t, req, syn in entries if t == "String" and req and not syn), id_prop_id)
        custom = {
            "iri": c.iri, "aggregateRole": c.role, "aggregateParent": c.aggregate_parent, "tenantScoped": c.tenant_scoped,
            "systemOfRecord": c.system_of_record, "owner": c.owner or m.owner, "boundedContext": m.bounded_context,
            "extends": c.extends, "equivalentTo": c.alignment.get("equivalentTo"), "specializes": c.alignment.get("specializes"),
        }
        m.fabric_entity_types.append({
            "id": type_ids[c.name], "namespace": "usertypes", "namespaceType": "Custom", "visibility": "Visible",
            "name": c.name, "baseEntityTypeId": type_ids.get(c.extends) if c.extends else None,
            "entityIdParts": [id_prop_id] if id_prop_id else [], "displayNamePropertyId": display,
            "semanticEnrichment": _enrichment(c.description, custom, c.synonyms),
            "properties": props, "timeseriesProperties": [],
        })

    def add_edge(name: str, iri: str, source: str, target: str, description: str, attrs: dict) -> None:
        if source not in type_ids or target not in type_ids:
            m.warnings.append(f"Fabric IQ: relationship {name} touches a join entity and is not emitted as an edge")
            return
        check_name("relationship type name", name)
        m.fabric_relationship_types.append({
            "id": reg.id_for(iri), "namespace": "usertypes", "namespaceType": "Custom", "name": name,
            "source": {"entityTypeId": type_ids[source]}, "target": {"entityTypeId": type_ids[target]},
            "semanticEnrichment": _enrichment(description, {"iri": iri, **attrs}),
        })

    for r in m.relations:
        attrs = {
            "relationship": r.rel_kind, "sourceCardinality": r.cardinality[0], "targetCardinality": r.cardinality[1],
            "cascadeDelete": r.cascade, "predicate": r.predicate, "targetRole": r.target_role, "joinEntity": r.join_entity,
            "selfReferenceKey": r.self_key, "polymorphicEntityTypes": ",".join(r.poly_types) if r.poly_types else None,
        }
        add_edge(f"{r.source}_{r.name}", r.iri, r.source, r.target, f"{r.source} {r.predicate or r.name} {r.target}", attrs)
    for nv in m.navigations:
        if nv.paired is not None:
            continue
        attrs = {"relationship": "navigation", "sourceCardinality": "*", "targetCardinality": "1" if nv.required else "0..1",
                 "required": nv.required, "predicate": nv.predicate}
        add_edge(f"{nv.source}_{nv.name}", nv.iri, nv.source, nv.target, f"{nv.source} {nv.predicate or nv.name} {nv.target}", attrs)

    for name, types in sorted(prop_types.items()):
        if len(types) > 1:
            m.warnings.append(f"Fabric IQ: property name '{name}' has conflicting value types across entity types ({', '.join(sorted(types))}); Fabric requires one valueType per name")


# --- Emitters ----------------------------------------------------------------

def _ext_id(ext: External) -> str:
    return "Ext_" + re.sub(r"[^A-Za-z0-9_]", "_", ext.local)


def _ext_label(ext: External) -> str:
    return f"{ext.prefix}:{ext.local}" if ext.prefix else ext.iri


def emit_mermaid(m: Model) -> str:
    lines = ["classDiagram"]
    for c in m.concepts.values():
        lines.append(f"  class {c.name} {{")
        lines.append(f"    <<{c.role}>>")
        for p in c.props:
            if p.kind != "value_object":
                lines.append(f"    +{p.kind} {p.name}")
        lines.append("  }")
    for ext in m.externals.values():
        lines.append(f'  class {_ext_id(ext)}["{_ext_label(ext)}"] {{')
        lines.append("    <<external>>")
        lines.append("  }")
    for c in m.entities():
        if c.extends:
            lines.append(f"  {c.extends} <|-- {c.name}")
    for c in m.entities():
        for p in c.props:
            if p.kind == "value_object":
                lines.append(f"  {c.name} --> {p.value_object} : {p.name}")
    for r in m.relations:
        label = r.predicate or r.name
        s, t = r.cardinality
        if r.rel_kind in ("one-to-many", "one-to-one", "self-referencing"):
            lines.append(f'  {r.source} "{s}" *-- "{t}" {r.target} : {label}')
        else:
            lines.append(f'  {r.source} "{s}" --> "{t}" {r.target} : {label}')
            if r.join_entity:
                lines.append(f"  {r.join_entity} ..> {r.source}")
                lines.append(f"  {r.join_entity} ..> {r.target}")
    for nv in m.navigations:
        if nv.paired is None:
            lines.append(f'  {nv.source} "*" --> "{"1" if nv.required else "0..1"}" {nv.target} : {nv.predicate or nv.name}')
    for c in m.concepts.values():
        for key in ("equivalentTo", "specializes"):
            iri = c.alignment.get(key)
            if iri and str(iri) in m.externals:
                lines.append(f"  {c.name} .. {_ext_id(m.externals[str(iri)])} : {key}")
    return "\n".join(lines) + "\n"


def _cell(value: object) -> str:
    text = str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()
    return text or "-"


def _table(headers: list[str], rows: list[list[object]]) -> list[str]:
    if not rows:
        return ["_none_"]
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out.extend("| " + " | ".join(_cell(x) for x in row) + " |" for row in rows)
    return out


def emit_markdown(m: Model, mermaid: str) -> str:
    yes_no = lambda b: "yes" if b else "no"  # noqa: E731
    L: list[str] = [
        f"<!-- Generated by scripts/generate-ontology.py from .scaffold/domain-specification.yaml. sourceHash: {m.source_hash}. Regenerate, never edit. -->",
        f"# Ontology - {m.bounded_context}", "",
    ]
    if m.description:
        L += [m.description, ""]
    L += ["## Overview", ""]
    L += _table(["Field", "Value"], [
        ["Namespace", f"`{m.namespace}`"], ["Ontology IRI", f"`{m.ontology_iri}`"], ["Bounded context", m.bounded_context],
        ["Owner", m.owner or "-"], ["Project", m.project],
        ["Concepts", f"{len(m.entities())} entities, {len(m.value_objects())} value objects"],
        ["Relationships", f"{len(m.relations)} ownership/association, {len(m.navigations)} navigation"],
        ["Aligns with", ", ".join(f"{a['name']} (`{a['namespace']}`)" for a in m.aligns_with) or "-"],
    ])
    L += ["", "## Diagram", "", "```mermaid", mermaid.rstrip("\n"), "```", ""]

    L += ["## Concepts", ""]
    L += _table(["Concept", "Kind", "Aggregate Role", "Extends", "Definition", "Synonyms", "System Of Record", "Owner"], [
        [f"`{c.name}`", c.kind, c.role, f"`{c.extends}`" if c.extends else "-", c.description, ", ".join(c.synonyms),
         yes_no(c.system_of_record) if c.kind == "entity" else "-", c.owner or (m.owner if c.kind == "entity" else None) or "-"]
        for c in m.concepts.values()
    ])
    L += ["", "## Properties", ""]
    prop_rows: list[list[object]] = []
    schemes = {s.iri: s for s in m.schemes}
    for c in m.concepts.values():
        for p in c.props:
            values = f"`{p.value_object}`" if p.kind == "value_object" else (
                ", ".join(schemes[p.scheme_iri].values) if p.scheme_iri and schemes[p.scheme_iri].values else "-")
            prop_rows.append([f"`{c.name}`", f"`{p.name}`", p.kind, yes_no(p.required), yes_no(p.sensitive), values, p.description])
    L += _table(["Concept", "Property", "Kind", "Required", "PII", "Values / Value Object", "Definition"], prop_rows)

    L += ["", "## Relationships", ""]
    rel_rows: list[list[object]] = []
    for r in m.relations:
        extra = []
        if r.join_entity:
            extra.append(f"join `{r.join_entity}`")
        if r.self_key:
            extra.append(f"key `{r.self_key}`")
        if r.poly_types:
            extra.append("polymorphic: " + ", ".join(r.poly_types))
        rel_rows.append([f"`{r.source}`", f"`{r.name}`", f"`{r.target}`", r.rel_kind, f"{r.cardinality[0]} : {r.cardinality[1]}",
                         r.predicate or "-", f"`{r.target_role}`" if r.target_role else "-",
                         "-" if r.cascade is None else yes_no(r.cascade), "; ".join(extra)])
    for nv in m.navigations:
        if nv.paired is None:
            rel_rows.append([f"`{nv.source}`", f"`{nv.name}`", f"`{nv.target}`", "navigation", f"* : {'1' if nv.required else '0..1'}",
                             nv.predicate or "-", "-", "-", "required" if nv.required else ""])
    L += _table(["From", "Relationship", "To", "Kind", "Cardinality", "Predicate", "Inverse Navigation", "Cascade Delete", "Notes"], rel_rows)

    L += ["", "## Enterprise Alignment", "", "Upstream models:", ""]
    L += _table(["Model", "Namespace", "Prefix"], [[a["name"], f"`{a['namespace']}`", f"`{a['prefix']}`"] for a in m.aligns_with])
    L += ["", "Concept alignments:", ""]
    align_rows: list[list[object]] = []
    for c in m.concepts.values():
        for key in ("equivalentTo", "specializes"):
            iri = c.alignment.get(key)
            if iri:
                ext = m.externals[str(iri)]
                upstream = next((a["name"] for a in m.aligns_with if a["namespace"] == ext.namespace), "(outside alignsWith)")
                align_rows.append([f"`{c.name}`", key, f"`{_ext_label(ext)}`", f"`{iri}`", upstream])
    L += _table(["Concept", "Relation", "External Concept", "IRI", "Upstream Model"], align_rows)

    L += ["", "## Glossary", "", "### Entities And Aggregates", ""]
    L += _table(["Term", "Role", "Parent", "Meaning"], [
        [f"`{c.name}`", c.role, f"`{c.aggregate_parent}`" if c.aggregate_parent else "-", c.description] for c in m.entities()])
    L += ["", "### Value Objects", ""]
    L += _table(["Term", "Fields", "Used By", "Meaning"], [
        [f"`{c.name}`", ", ".join(f"`{p.name}`" for p in c.props),
         ", ".join(f"`{u.get('entity')}.{u.get('property')}`" for u in c.used_by), c.description] for c in m.value_objects()])
    L += ["", "### States", ""]
    L += _table(["Concept", "Field", "Initial", "States", "Terminal"], [
        [f"`{s.owner}`", f"`{s.prop}`", s.initial or "-", ", ".join(s.values), ", ".join(s.terminals) or "-"]
        for s in m.schemes if s.is_state_machine])
    L += ["", "### Events", ""]
    L += _table(["Event", "Raised By", "Trigger", "Payload"], [
        [f"`{e.name}`", f"`{e.raised_by}`", f"`{e.trigger}`", ", ".join(e.payload)] for e in m.events])
    L += ["", "### Policies And Rules", ""]
    rule_rows: list[list[object]] = []
    for c in m.concepts.values():
        for rule in c.rules:
            name, _, condition = rule.partition(": ")
            rule_rows.append([f"`{name}`", f"`{c.name}`", condition or "-"])
    for rule in m.domain_rules:
        rule_rows.append([f"`{rule.get('name')}`", ", ".join(f"`{t}`" for t in rule.get("appliesTo") or []) or "domain",
                          str(rule.get("errorMessage") or "-")])
    L += _table(["Rule", "Scope", "Condition"], rule_rows)

    L += ["", "## Generation Notes", "",
          f"- Source: `.scaffold/domain-specification.yaml` (sourceHash `{m.source_hash}`)",
          f"- Generate: `{GENERATE_CMD}`",
          f"- Check currency: `{GENERATE_CMD} --check`",
          f"- Fabric IQ parts: {len(m.fabric_entity_types)} entity type(s), {len(m.fabric_relationship_types)} relationship type(s) under `fabric-iq/`",
          "- Warnings:"]
    L += [f"  - {w}" for w in m.warnings] or ["  - none"]
    L += ["- Omitted constructs (not projected):"]
    L += [f"  - {k}: {v}" for k, v in m.omitted.items()] or ["  - none"]
    return "\n".join(L) + "\n"


def _ref(iri: str) -> dict:
    return {"@id": iri}


def _node(**pairs: object) -> dict:
    return {k: v for k, v in pairs.items() if v not in (None, "", [], {})}


def emit_jsonld(m: Model) -> dict:
    context: dict[str, object] = dict(PREFIXES)
    context[m.prefix] = m.namespace
    for a in m.aligns_with:
        context[a["prefix"]] = a["namespace"]
    graph: list[dict] = [_node(**{
        "@id": m.ontology_iri, "@type": "owl:Ontology", "rdfs:label": m.bounded_context, "rdfs:comment": m.description,
        "scaffold:project": m.project, "scaffold:boundedContext": m.bounded_context, "scaffold:owner": m.owner,
        "scaffold:sourceHash": m.source_hash, "scaffold:generator": GENERATOR, "scaffold:formatVersion": FORMAT_VERSION,
        "dcterms:references": [_ref(a["namespace"]) for a in m.aligns_with],
    })]
    for c in m.concepts.values():
        parents = []
        if c.extends:
            parents.append(_ref(m.concepts[c.extends].iri))
        if c.alignment.get("specializes"):
            parents.append(_ref(str(c.alignment["specializes"])))
        notes = list(c.rules) + [_rule_text(r) for r in m.domain_rules if c.name in (r.get("appliesTo") or [])]
        graph.append(_node(**{
            "@id": c.iri, "@type": "owl:Class", "rdfs:label": c.name, "skos:definition": c.description,
            "skos:altLabel": list(c.synonyms), "rdfs:isDefinedBy": _ref(m.ontology_iri), "rdfs:subClassOf": parents,
            "owl:equivalentClass": _ref(str(c.alignment["equivalentTo"])) if c.alignment.get("equivalentTo") else None,
            "scaffold:conceptKind": c.kind, "scaffold:aggregateRole": c.role if c.kind == "entity" else None,
            "scaffold:aggregateParent": _ref(m.concepts[c.aggregate_parent].iri) if c.aggregate_parent in m.concepts else None,
            "scaffold:tenantScoped": c.tenant_scoped if c.kind == "entity" else None,
            "scaffold:systemOfRecord": c.system_of_record if c.kind == "entity" else None,
            "scaffold:owner": c.owner, "skos:note": notes,
            "scaffold:stateField": str(c.state_machine["field"]) if c.state_machine and c.state_machine.get("field") else None,
        }))
        for p in c.props:
            if p.kind == "value_object":
                graph.append(_node(**{
                    "@id": p.iri, "@type": ["owl:ObjectProperty", "owl:FunctionalProperty"], "rdfs:label": p.name,
                    "rdfs:domain": _ref(c.iri), "rdfs:range": _ref(m.concepts[p.value_object].iri), "skos:definition": p.description,
                    "scaffold:sourceKind": p.kind, "scaffold:required": p.required,
                }))
                continue
            graph.append(_node(**{
                "@id": p.iri, "@type": ["owl:DatatypeProperty", "owl:FunctionalProperty"], "rdfs:label": p.name,
                "rdfs:domain": _ref(c.iri), "rdfs:range": _ref(XSD_RANGE[p.kind]), "skos:definition": p.description,
                "scaffold:sourceKind": p.kind, "scaffold:required": p.required, "scaffold:pii": True if p.sensitive else None,
                "scaffold:valueScheme": _ref(p.scheme_iri) if p.scheme_iri else None,
            }))
    for s in m.schemes:
        graph.append(_node(**{
            "@id": s.iri, "@type": "skos:ConceptScheme", "rdfs:label": f"{s.owner} {s.prop} values",
            "scaffold:initialState": _ref(f"{s.iri}/{_seg(s.initial)}") if s.initial else None,
            "skos:hasTopConcept": [_ref(f"{s.iri}/{_seg(v)}") for v in s.values],
        }))
        for v in s.values:
            graph.append(_node(**{
                "@id": f"{s.iri}/{_seg(v)}", "@type": "skos:Concept", "skos:prefLabel": v, "skos:inScheme": _ref(s.iri),
                "scaffold:terminal": True if v in s.terminals else None,
            }))
    for r in m.relations:
        types = ["owl:ObjectProperty"] + (["owl:FunctionalProperty"] if r.rel_kind == "one-to-one" else [])
        inverse = next((nv for nv in m.navigations if nv.paired is r), None)
        graph.append(_node(**{
            "@id": r.iri, "@type": types, "rdfs:label": r.predicate or r.name, "rdfs:domain": _ref(m.concepts[r.source].iri),
            "rdfs:range": _ref(m.concepts[r.target].iri), "scaffold:relationshipName": r.name, "scaffold:relationshipKind": r.rel_kind,
            "scaffold:sourceCardinality": r.cardinality[0], "scaffold:targetCardinality": r.cardinality[1],
            "scaffold:cascadeDelete": r.cascade, "scaffold:predicate": r.predicate,
            "scaffold:joinEntity": _ref(m.concepts[r.join_entity].iri) if r.join_entity else None,
            "scaffold:selfReferenceKey": r.self_key,
            "scaffold:polymorphicEntityTypes": [_ref(m.concepts[d].iri) for d in r.poly_types],
            "owl:inverseOf": _ref(inverse.iri) if inverse else None,
        }))
    for nv in m.navigations:
        graph.append(_node(**{
            "@id": nv.iri, "@type": ["owl:ObjectProperty", "owl:FunctionalProperty"], "rdfs:label": nv.predicate or nv.name,
            "rdfs:domain": _ref(m.concepts[nv.source].iri), "rdfs:range": _ref(m.concepts[nv.target].iri),
            "scaffold:relationshipName": nv.name, "scaffold:relationshipKind": "navigation", "scaffold:required": nv.required,
            "scaffold:predicate": nv.predicate, "owl:inverseOf": _ref(nv.paired.iri) if nv.paired else None,
        }))
    for ext in m.externals.values():
        graph.append(_node(**{"@id": ext.iri, "@type": "owl:Class", "rdfs:label": ext.local,
                              "rdfs:isDefinedBy": _ref(ext.namespace.rstrip("/#")) if ext.namespace else None}))
    if m.events:
        graph.append({"@id": META_NS + "DomainEvent", "@type": "owl:Class", "rdfs:label": "Domain Event"})
        for e in m.events:
            graph.append(_node(**{
                "@id": e.iri, "@type": "owl:Class", "rdfs:subClassOf": [_ref(META_NS + "DomainEvent")], "rdfs:label": e.name,
                "scaffold:raisedBy": _ref(m.concepts[e.raised_by].iri) if e.raised_by in m.concepts else e.raised_by,
                "scaffold:trigger": e.trigger, "scaffold:payloadField": list(e.payload),
            }))
    return {"@context": context, "@graph": graph}


def emit_fabric(m: Model) -> dict[str, object]:
    parts: dict[str, object] = {
        "fabric-iq/.platform": {"metadata": {"type": "Ontology", "displayName": m.bounded_context}},
        "fabric-iq/definition.json": {},
    }
    for et in m.fabric_entity_types:
        parts[f"fabric-iq/EntityTypes/{et['id']}/definition.json"] = et
    for rt in m.fabric_relationship_types:
        parts[f"fabric-iq/RelationshipTypes/{rt['id']}/definition.json"] = rt
    return parts


# --- Rendering and I/O -------------------------------------------------------

def _dump(obj: object) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def render_all(spec: dict) -> tuple[Model, dict[str, bytes]]:
    m = build_model(spec)
    files: dict[str, bytes] = {}
    files["ontology.md"] = emit_markdown(m, emit_mermaid(m)).encode("utf-8")
    files["ontology.jsonld"] = _dump(emit_jsonld(m))
    for rel, obj in emit_fabric(m).items():
        files[rel] = _dump(obj)
    manifest = {
        "formatVersion": FORMAT_VERSION, "generator": GENERATOR, "sourceHash": m.source_hash,
        "ontologyIri": m.ontology_iri, "files": {rel: _sha256(data) for rel, data in sorted(files.items())},
    }
    files["manifest.json"] = _dump(manifest)
    return m, files


def _read_manifest(out_dir: Path) -> dict | None:
    path = out_dir / "manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def write_outputs(out_dir: Path, files: dict[str, bytes]) -> tuple[list[str], list[str], list[str]]:
    """Write changed bytes only; prune files the previous manifest listed that are no longer rendered
    and still match their manifest hash. Returns (written, pruned, kept_modified)."""
    previous = _read_manifest(out_dir) or {}
    written: list[str] = []
    pruned: list[str] = []
    kept: list[str] = []
    for rel, data in sorted(files.items()):
        path = out_dir / rel
        if path.is_file() and _normalize(path.read_bytes()) == data:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written.append(rel)
    for rel, digest in sorted((previous.get("files") or {}).items()):
        if rel in files:
            continue
        path = out_dir / rel
        if not path.is_file():
            continue
        if _sha256(_normalize(path.read_bytes())) == digest:
            path.unlink()
            pruned.append(rel)
            parent = path.parent
            while parent != out_dir and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        else:
            kept.append(rel)
    return written, pruned, kept


def check_outputs(out_dir: Path, files: dict[str, bytes], source_hash: str) -> list[str]:
    previous = _read_manifest(out_dir)
    if previous is None:
        return ["manifest.json missing - run without --check to generate"]
    if previous.get("sourceHash") != source_hash:
        return [f"spec changed since last generation (sourceHash {str(previous.get('sourceHash'))[:12]} -> {source_hash[:12]}) - regenerate"]
    problems: list[str] = []
    for rel, data in sorted(files.items()):
        path = out_dir / rel
        if not path.is_file():
            problems.append(f"{rel}: missing")
        elif _normalize(path.read_bytes()) != data:
            problems.append(f"{rel}: differs from the rendered projection (hand edit? regenerate)")
    for rel in sorted(previous.get("files") or {}):
        if rel not in files and (out_dir / rel).is_file():
            problems.append(f"{rel}: stale - no longer rendered")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Project .scaffold/domain-specification.yaml into .scaffold/ontology/.")
    parser.add_argument("--root", default=".", help="Scaffolded app root (contains .scaffold/).")
    parser.add_argument("--check", action="store_true", help="Exit 1 when .scaffold/ontology/ is not current; write nothing.")
    parser.add_argument("--strict", action="store_true", help="Exit 1 when the projection produced warnings.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    spec_path = root / SPEC_PATH
    out_dir = root / OUTPUT_ROOT
    try:
        spec = load_spec(spec_path)
        if "ontology" not in spec:
            if out_dir.exists():
                print(f"[fail] {spec_path} declares no ontology: block but {out_dir} exists - remove .scaffold/ontology/ or restore ontology:")
                return 1
            print("ontology: skipped - domain-specification.yaml declares no ontology: block (opt-in)")
            return 0
        model, files = render_all(spec)
    except SpecError as exc:
        print(f"[fail] {exc}")
        return 2

    for w in model.warnings:
        print(f"[warn] {w}")
    if args.check:
        problems = check_outputs(out_dir, files, model.source_hash)
        if problems:
            print(f"[drift] .scaffold/ontology/ is out of date ({len(problems)} finding(s)) - run: {GENERATE_CMD}")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(f"[ok] .scaffold/ontology/ is current (sourceHash {model.source_hash[:12]})")
    else:
        written, pruned, kept = write_outputs(out_dir, files)
        print(f"ontology: {len(files)} file(s) rendered, {len(written)} written, {len(pruned)} pruned -> {out_dir} (sourceHash {model.source_hash[:12]})")
        for rel in kept:
            print(f"[note] {rel}: listed in the previous manifest but modified on disk; not pruned")
    if args.strict and model.warnings:
        print(f"[fail] --strict: {len(model.warnings)} warning(s)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
