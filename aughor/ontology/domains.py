"""ON-8 — one ontology, many sources: the organisation's ontology (ROADMAP §3.15, the second movement).

Before this wave an ontology was the graph of ONE connection's schema: its cache key, its overrides directory and every
door took ``(connection_id, schema_name)``, and neither a backing nor a binding could name another connection. The
builder still makes that graph, and it stays what it is: the source catalogue of one source, its tables profiled and its
joins measured. The business ontology is the organisation's, keyed ``org/domain`` — §6 item 18(a): a named domain, one
per organisation by default, so a single-domain organisation never spells the second segment — and its types are
declared on whichever connections hold their rows.

* **The scope** — `Domain`, `resolve_domain`. A domain's declarations live in the overrides tree under
  ``org=<org>/<domain>``, beside the per-connection scopes (a connection id never holds ``=``): no second ontology
  store, and every kind the tree already carries works here unchanged.
* **The served graph** — `domain_graph`. No cache and no build: an empty graph with every declaration overlaid from what
  its bind and its count recorded, as database-free as the per-connection overlay, and each link stamped with its
  traversal by the source law (`aughor.ontology.sources`).
* **The doors' bodies** — declaring a type, binding a source, declaring a link, and measuring them all again. Each
  reads its source on that source's own connection, and a binding or link whose two sides live on two connections is
  counted on both, under the verdict it would meet on one (`bindings.measure_binding`, `declared.measure_declared_link`).
  A column borrows what the builder measured of it (its role and unit) from its own source's catalogue when it is
  declared, and the declaration keeps the copy.
* **Edited by people only** — the user's rule, 2026-09-14. A declaration here is a person's: one that says it is a
  model's is refused before anything is read, the tree is written by `overrides.save_organisation_override` alone
  (which refuses anything but a person's declaration too), and a copied column profile carries no words a model or the
  explorer wrote. The explorer drafts inside one connection's ontology and never reads this one.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from aughor.ontology.models import OntologyGraph
from aughor.ontology.overrides import ORGANISATION_SEGMENT
from aughor.ontology.sources import binding_source, entity_source, stamp_traversals

logger = logging.getLogger(__name__)

#: The domain every organisation has until it names a second, so a single-domain organisation never spells one.
DEFAULT_DOMAIN = "default"
#: A domain's name: the second segment of ``org/domain``, and a directory of the overrides tree.
DOMAIN_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")

#: ``open_source(connection_id)`` → an open connection to that registered source. Whoever opens one closes it.
Opener = Callable[[str], Any]


class DomainRefused(ValueError):
    """A declaration an organisation's ontology will not take as asked, with the HTTP status its door answers."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class Domain:
    """``org/domain``: an organisation's ontology, or one named part of it — a retail ontology beside a finance one."""
    org: str
    name: str

    @property
    def key(self) -> str:
        return f"{self.org}/{self.name}"

    @property
    def tree(self) -> tuple[str, str]:
        """The two segments its declarations are kept under in the overrides tree."""
        return f"{ORGANISATION_SEGMENT}{self.org}", self.name


def resolve_domain(name: Optional[str] = None, org: Optional[str] = None) -> Domain:
    """The domain a request names, in its organisation — the default domain when it names none."""
    from aughor.org.context import current_org_id
    wanted = (name or "").strip() or DEFAULT_DOMAIN
    if not DOMAIN_PATTERN.match(wanted):
        raise DomainRefused(400, "a domain is named in lowercase: a letter, then up to 39 letters, digits, '-' or '_'")
    return Domain(org=(org or "").strip() or current_org_id(), name=wanted)


def domain_names(org: Optional[str] = None) -> list[str]:
    """The domains an organisation has declared anything in."""
    from aughor.ontology.overrides import override_scopes
    from aughor.org.context import current_org_id
    return override_scopes(f"{ORGANISATION_SEGMENT}{org or current_org_id()}")


def domain_graph(domain: Domain) -> OntologyGraph:
    """The organisation's ontology as served: every declaration in the domain overlaid onto an empty graph, and each
    link stamped with its traversal. Built on every read from the declaration files, with no database and no cache."""
    from aughor.ontology.overrides import apply_overrides
    conn, name = domain.tree
    graph = OntologyGraph(connection_id=conn, schema_name=name, schema_fingerprint="", scope=domain.key)
    _, report = apply_overrides(graph, conn, name)
    if report.skipped:
        logger.info("[ontology:%s] declarations not applied: %s", domain.key, report.skipped)
    stamp_traversals(graph)
    return graph


def connections_of(graph: OntologyGraph) -> list[str]:
    """Every connection an organisation's ontology reads: each type's, and each binding's that names its own."""
    found = {entity_source(graph, e) for e in graph.entities.values()}
    found |= {b.connection_id for e in graph.entities.values() for b in e.bindings or [] if b.connection_id}
    return sorted(found)


def check_source(domain: Domain, connection_id: str) -> None:
    """A connection a declaration names must be registered, and must not be another organisation's (a shared builtin
    belongs to none, and any organisation may read it)."""
    from aughor.db.registry import get_connection_org, get_dsn
    try:
        get_dsn(connection_id)
    except KeyError as exc:
        raise DomainRefused(404, f"no connection '{connection_id}'") from exc
    owner = get_connection_org(connection_id)
    if owner and owner != domain.org:
        raise DomainRefused(403, f"connection '{connection_id}' belongs to another organisation")


def catalogue_of(connection_id: str, schema_name: str = "") -> Optional[OntologyGraph]:
    """One source's catalogue: the graph its builder made of the schema a declaration reads, which the declaration's
    columns borrow their roles from. A cache read that never builds; None when that schema has no graph."""
    from aughor.db.registry import get_meta
    from aughor.ontology.store import load_latest_ontology
    schema = (schema_name or "").strip() or str(get_meta(connection_id).get("schema_name") or "")
    return load_latest_ontology(connection_id, schema) if schema else None


def _schema_of(table: Optional[str]) -> str:
    """The schema a qualified table names (`luxexperience` of `luxexperience.orders`), or ""."""
    parts = (table or "").split(".")
    return parts[-2] if len(parts) >= 2 else ""


def _persons_only(spec: dict) -> None:
    """The user's rule (2026-09-14): an organisation's ontology is edited by people only. A declaration that says it is a
    model's — an ``origin`` other than human, or a model's provenance — is refused before anything is read: a model
    drafts, and a person confirms, inside one connection's ontology."""
    origin = str(spec.get("origin") or "human")
    if origin != "human" or str(spec.get("provenance") or "").strip():
        raise DomainRefused(400, (
            "an organisation's ontology is edited by people only — a model's proposal is drafted and confirmed in one "
            f"connection's ontology, never here (this declaration's origin is '{origin}')"))


def declare_entity(domain: Domain, spec: dict, open_source: Opener):
    """Declare a type in the domain. The source holding one row per object is read for its columns ON ITS OWN
    connection and its key counted there before anything is written; its columns borrow what the builder measured of
    them from that connection's catalogue, and the declaration keeps the copy. Returns the saved override."""
    from aughor.ontology.bindings import column_profiles, describe_with, profile_record
    from aughor.ontology.declared import (
        backs_existing_type, entity_fields, entity_spec_problem, measure_declared_backing,
    )
    from aughor.ontology.overrides import OntologyOverride, save_organisation_override
    _persons_only(spec)
    problem = entity_spec_problem(spec)
    if problem:
        raise DomainRefused(400, problem)
    connection = str((spec.get("backing") or {}).get("connection_id") or "").strip()
    if not connection:
        raise DomainRefused(400, "a type in an organisation's ontology names the connection its rows live on — "
                                 "`backing.connection_id`")
    check_source(domain, connection)
    graph = domain_graph(domain)
    entity_id = str(spec["id"])
    if entity_id in graph.entities:
        raise DomainRefused(409, f"an object type '{entity_id}' already exists in {domain.key}")
    fields = entity_fields(spec)
    table = fields["backing"].get("table")
    if table:
        other = backs_existing_type(graph, table, connection)
        if other is not None:
            raise DomainRefused(400, f"{connection}.{table} already backs {other.id} — a second type over the same rows "
                                     f"is a duplicate; rename {other.id} instead")
    db = open_source(connection)
    try:
        entry = measure_declared_backing(db, fields, describe_with(db))
    finally:
        db.close()
    if not entry.get("bound"):
        raise DomainRefused(400, f"{entity_id} did not bind: {entry.get('note')}")
    entry["profiles"] = profile_record(column_profiles(catalogue_of(connection, _schema_of(table)), table or None,
                                                      entry.get("columns") or {}, fields["backing"].get("sql")))
    ov = OntologyOverride(target_kind="entity", target_id=entity_id, fields=fields, source=fields["origin"],
                          binding={"backing": entry})
    save_organisation_override(*domain.tree, ov)
    return ov


def bind_source(domain: Domain, entity_id: str, name: str, spec: dict, open_source: Opener):
    """Bind a further source to a type in the domain. A source on the type's own connection binds as it would in that
    connection's ontology; a source on another (``connection_id``) is read for its columns THERE and counted against
    the objects across both. Across two connections a binding is read by key, one row per object, so only a static one
    binds. ``schema_name`` qualifies a bare table. Returns the saved override."""
    from aughor.ontology.bindings import bind_binding, binding_block, declared_bindings, describe_with, measure_binding
    from aughor.ontology.overrides import OntologyOverride, find_override, save_organisation_override
    _persons_only(spec)
    graph = domain_graph(domain)
    entity = graph.entities.get(entity_id)
    if entity is None:
        raise DomainRefused(404, f"no object type '{entity_id}' in {domain.key}")
    spec = dict(spec)
    if spec.pop("absorb", None):
        raise DomainRefused(400, "a part is absorbed in the ontology of the connection that holds both tables, not "
                                 "across an organisation's")
    schema = str(spec.pop("schema_name", "") or "").strip()
    if schema and spec.get("table") and "." not in str(spec["table"]):
        spec["table"] = f"{schema}.{spec['table']}"
    home = entity_source(graph, entity)
    where = str(spec.get("connection_id") or "").strip() or home
    if where == home:
        spec.pop("connection_id", None)
    else:
        check_source(domain, where)
    objects = open_source(home)
    rows = objects if where == home else open_source(where)
    try:
        entry = bind_binding(entity, name, spec, graph, describe_with(rows),
                             profiles_from=catalogue_of(where, _schema_of(spec.get("table"))))
        if not entry["bound"]:
            raise DomainRefused(400, f"binding '{name}' on {entity_id} did not bind: {entry['note']}")
        existing = find_override(*domain.tree, "entity", entity_id)
        fields = dict(existing.fields) if existing else {}
        fields["bindings"] = {**(fields.get("bindings") or {}), name: entry["spec"]}
        kept = dict(existing.binding) if existing else {}
        entries = {**((kept.get("bindings") or {}).get("entries") or {}), name: entry}
        # Count it now, over exactly what the overlay will build, so the verdict arrives while the person is here.
        built, _ = declared_bindings(entity.model_copy(update={"bindings": []}), fields["bindings"],
                                     {"entries": entries}, graph)
        mine = next((b for b in built if b.name == name), None)
        if mine is not None:
            counted = measure_binding(rows, entity, mine, object_db=None if where == home else objects)
            entries[name] = {**entry, "measured": {"spec": entry["spec"], **counted.counts()}}
        ov = OntologyOverride(target_kind="entity", target_id=entity_id, fields=fields,
                              source=(existing.source if existing else "human"),
                              binding={**kept, "bindings": binding_block(entries)})
        save_organisation_override(*domain.tree, ov)
    finally:
        objects.close()
        if rows is not objects:
            rows.close()
    return ov


def declare_link(domain: Domain, spec: dict, open_source: Opener):
    """Declare a link between two types in the domain. Each side is counted on the connection its type lives on, and
    the share of from-keys the to-side holds is measured before anything is written — across two connections the keys
    meet in memory, under the law one connection's probe follows. Returns the saved override."""
    from aughor.ontology.declared import (
        link_fields, link_id, link_problem_on_graph, link_spec_problem, measure_declared_link,
    )
    from aughor.ontology.overrides import OntologyOverride, save_organisation_override
    _persons_only(spec)
    problem = link_spec_problem(spec)
    if problem:
        raise DomainRefused(400, problem)
    graph = domain_graph(domain)
    fields = link_fields(spec)
    if link_id(fields) in graph.relationships:
        raise DomainRefused(409, f"a link '{link_id(fields)}' already exists in {domain.key}")
    problem = link_problem_on_graph(graph, fields)
    if problem:
        raise DomainRefused(400, problem)
    a, b = graph.entities[fields["from_entity"]], graph.entities[fields["to_entity"]]
    left_source, right_source = entity_source(graph, a), entity_source(graph, b)
    left = open_source(left_source)
    right = left if left_source == right_source else open_source(right_source)
    try:
        entry = measure_declared_link(left, graph, fields, to_db=None if right is left else right)
    finally:
        left.close()
        if right is not left:
            right.close()
    if not entry.get("bound"):
        raise DomainRefused(400, f"link '{fields['name']}' did not bind: {entry.get('note')}")
    ov = OntologyOverride(target_kind="link", target_id=link_id(fields), fields=fields, source=fields["origin"],
                          binding={"link": entry})
    save_organisation_override(*domain.tree, ov)
    return ov


def declare_process(domain: Domain, spec: dict, open_source: Opener):
    """ON-9 on an organisation's ontology: a process one of its types goes through, each stage resolved by the object
    door's path law over the domain and the whole declaration counted through it before anything is written — a stage
    anchored on a type or binding on another connection is counted across the two, split at the keyed reads, as a query
    there is. Returns the saved override."""
    from aughor.ontology.overrides import OntologyOverride, save_organisation_override
    from aughor.ontology.processes import (
        NotMeasurable, measure_process, process_entry, process_fields, process_spec_problem, resolve_process,
    )
    _persons_only(spec)
    problem = process_spec_problem(spec)
    if problem:
        raise DomainRefused(400, problem)
    graph = domain_graph(domain)
    process_id = str(spec["id"])
    if process_id in graph.processes:
        raise DomainRefused(409, f"a process '{process_id}' already exists in {domain.key}")
    problem, fields = resolve_process(graph, process_id, process_fields(spec))
    if problem:
        raise DomainRefused(400, problem)
    for connection_id in connections_of(graph):
        check_source(domain, connection_id)
    try:
        measured = measure_process(None, graph, process_id, fields, open_source=open_source)
    except NotMeasurable as exc:
        raise DomainRefused(400, f"{process_id} could not be counted: {exc}") from exc
    ov = OntologyOverride(target_kind="process", target_id=process_id, fields=fields, source=fields["origin"],
                          binding={"process": process_entry(fields, measured)})
    save_organisation_override(*domain.tree, ov)
    return ov


def declare_rule(domain: Domain, spec: dict, open_source: Opener):
    """ON-9 on an organisation's ontology: a named rule over one of its types — a value set, or conditions in the object
    door's shape, which may read a type on another connection through a to-one link — counted through the door before
    anything is written. Returns the saved override."""
    from aughor.ontology.business_rules import measure_rule, resolve_rule, rule_entry, rule_fields, rule_spec_problem
    from aughor.ontology.overrides import OntologyOverride, save_organisation_override
    from aughor.ontology.processes import NotMeasurable
    _persons_only(spec)
    problem = rule_spec_problem(spec)
    if problem:
        raise DomainRefused(400, problem)
    graph = domain_graph(domain)
    rule_id = str(spec["id"])
    if rule_id in graph.rules:
        raise DomainRefused(409, f"a rule '{rule_id}' already exists in {domain.key}")
    problem, fields = resolve_rule(graph, rule_id, rule_fields(spec))
    if problem:
        raise DomainRefused(400, problem)
    for connection_id in connections_of(graph):
        check_source(domain, connection_id)
    try:
        measured = measure_rule(None, graph, rule_id, fields, open_source=open_source)
    except NotMeasurable as exc:
        raise DomainRefused(400, f"{rule_id} could not be counted: {exc}") from exc
    ov = OntologyOverride(target_kind="rule", target_id=rule_id, fields=fields, source=fields["origin"],
                          binding={"rule": rule_entry(fields, measured)})
    save_organisation_override(*domain.tree, ov)
    return ov


def measure_domain(domain: Domain, open_source: Opener) -> dict:
    """Count every declaration in the domain again — each type's key, each binding against its objects, each link's two
    sides, each process and rule — on the connections they name, and record the counts on their files so the next read
    carries them. The types first, because bindings and links are counted against the objects; processes and rules
    last, because they are counted through all three. No model call. A copied column profile is kept as the rule has it
    now: what the builder measured, and no words."""
    from aughor.ontology.bindings import (
        binding_block, declared_bindings, describe_with, measure_binding, profile_record, recorded_profiles,
    )
    from aughor.ontology.business_rules import measure_override_rules
    from aughor.ontology.declared import measure_declared_backing, measure_declared_link
    from aughor.ontology.overrides import load_overrides, save_organisation_override
    from aughor.ontology.processes import measure_override_processes
    opened: dict[str, Any] = {}

    def source(connection_id: str) -> Any:
        if connection_id not in opened:
            opened[connection_id] = open_source(connection_id)
        return opened[connection_id]

    out: dict = {"domain": domain.key, "entities": [], "bindings": [], "links": [], "processes": [], "rules": []}
    try:
        for ov in load_overrides(*domain.tree):
            if ov.target_kind != "entity" or not ov.fields.get("declared"):
                continue
            connection = str((ov.fields.get("backing") or {}).get("connection_id") or "")
            if not connection:
                out["entities"].append({"entity": ov.target_id, "bound": False, "note": "it names no connection"})
                continue
            kept = ov.binding.get("backing") or {}
            db = source(connection)
            entry = measure_declared_backing(db, ov.fields, describe_with(db))
            if "profiles" in kept:
                entry["profiles"] = profile_record(recorded_profiles(kept["profiles"]))
            ov.binding["backing"] = entry
            save_organisation_override(*domain.tree, ov)
            out["entities"].append({"entity": ov.target_id, "connection_id": connection, "bound": entry.get("bound"),
                                    "unique": entry.get("unique"), "rows": entry.get("rows"),
                                    "note": entry.get("unique_note") or entry.get("note") or ""})
        graph = domain_graph(domain)
        for ov in load_overrides(*domain.tree):
            if ov.target_kind == "entity":
                specs, entity = ov.fields.get("bindings"), graph.entities.get(ov.target_id)
                if not isinstance(specs, dict) or not specs or entity is None:
                    continue
                block = dict(ov.binding.get("bindings") or {})
                entries = dict(block.get("entries") or {})
                built, _ = declared_bindings(entity.model_copy(update={"bindings": []}), specs, block, graph)
                for binding in built:
                    home, where = entity_source(graph, entity), binding_source(graph, entity, binding)
                    m = measure_binding(source(where), entity, binding,
                                        object_db=None if where == home else source(home))
                    entries[binding.name] = {**entries[binding.name],
                                             "measured": {"spec": entries[binding.name]["spec"], **m.counts()}}
                    if "profiles" in entries[binding.name]:
                        entries[binding.name]["profiles"] = profile_record(
                            recorded_profiles(entries[binding.name]["profiles"]))
                    out["bindings"].append({"binding": f"{entity.id}.{binding.name}", "connection_id": where,
                                            "cross_source": where != home, **m.counts()})
                if built:
                    ov.binding["bindings"] = binding_block(entries)
                    save_organisation_override(*domain.tree, ov)
            elif ov.target_kind == "link" and ov.fields.get("declared"):
                a = graph.entities.get(str(ov.fields.get("from_entity") or ""))
                b = graph.entities.get(str(ov.fields.get("to_entity") or ""))
                if a is None or b is None:
                    continue
                left_source, right_source = entity_source(graph, a), entity_source(graph, b)
                entry = measure_declared_link(source(left_source), graph, ov.fields,
                                              to_db=None if left_source == right_source else source(right_source))
                ov.binding["link"] = entry
                save_organisation_override(*domain.tree, ov)
                out["links"].append({"link": ov.target_id,
                                     "traversal": "cross-source" if left_source != right_source else "join",
                                     "measured_cardinality": entry.get("measured_cardinality"),
                                     "value_overlap": entry.get("value_overlap"), "bound": entry.get("bound"),
                                     "note": entry.get("note")})
        # processes, then rules — each over the graph as the counts just recorded leave it (the rules over a second
        # read, so a rule that reads a process's lag sees its fresh verdict), as one connection's measure pass counts
        # them, and each written back through the organisation's own writer
        out["processes"] = measure_override_processes(*domain.tree, None, domain_graph(domain), open_source=open_source,
                                                      save=save_organisation_override)
        out["rules"] = measure_override_rules(*domain.tree, None, domain_graph(domain), open_source=open_source,
                                              save=save_organisation_override)
    finally:
        for db in opened.values():
            db.close()
    return out
