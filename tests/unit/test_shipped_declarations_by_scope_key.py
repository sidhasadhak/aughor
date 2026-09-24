"""PENDING.md item 14 — declared business terms survive a fresh clone (ROADMAP §3.34).

The Olist and LuxExperience declarations behind §3.15's receipts lived only on the builder's
machine, keyed by random connection ids. They now ship under `data/shipped/ontology_overrides/
key=<scope key>/`, and the overlay resolves a connection's scope key to them at read time. What
this proves, with no database and no model: a connection with a RANDOM id and the scope key gets
every declaration back — processes, rules and the action, each with the measurement it was served
with — and the frame matcher scores the rebuilt graph exactly as it scores the snapshot.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aughor.ontology import overrides as OV
from aughor.ontology.models import OntologyGraph

REPO = Path(__file__).resolve().parents[2]
HOSTS = {"luxexperience": ("evals/ablation_luxexperience_business_ontology.json", "luxexperience"),
         "olist": ("evals/ablation_olist_business_ontology.json", "ecommerce")}
RANDOM_ID = "c0ffee42"


@pytest.fixture
def fresh_install(tmp_path, monkeypatch):
    """An install that declared nothing, whose connection this machine happened to mint as c0ffee42."""
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(OV, "_SEED_ROOT", REPO / "data" / "shipped" / "ontology_overrides")
    keys: dict[str, str] = {}
    import aughor.db.registry as registry
    monkeypatch.setattr(registry, "scope_key_of", lambda conn: keys.get(conn, ""))
    return keys


def _stripped(snapshot: dict) -> OntologyGraph:
    # what a fresh build serves before any declaration: the snapshot without its declared parts
    # (the actions' field keeps its frozen wire name)
    return OntologyGraph.model_validate({**snapshot, "processes": {}, "rules": {}, "kinetic_actions": {}})


@pytest.mark.parametrize("key", sorted(HOSTS))
def test_a_random_connection_with_the_scope_key_gets_every_declaration_back(fresh_install, key):
    path, schema = HOSTS[key]
    snapshot = json.loads((REPO / path).read_text())
    fresh_install[RANDOM_ID] = key
    graph, _report = OV.apply_overrides(_stripped(snapshot), RANDOM_ID, schema)
    want = OntologyGraph.model_validate(snapshot)
    assert sorted(graph.processes) == sorted(want.processes) and sorted(graph.rules) == sorted(want.rules)
    assert sorted(a.id for a in graph.declared_actions()) == sorted(a.id for a in want.declared_actions())
    for rid, rule in want.rules.items():
        assert graph.rules[rid].model_dump() == rule.model_dump(), rid          # measurement included
    for pid, proc in want.processes.items():
        assert graph.processes[pid].model_dump() == proc.model_dump(), pid


def test_without_the_key_nothing_ships_to_it(fresh_install):
    path, schema = HOSTS["olist"]
    graph, _ = OV.apply_overrides(_stripped(json.loads((REPO / path).read_text())), RANDOM_ID, schema)
    assert graph.processes == {} and graph.rules == {}


def test_the_frame_matcher_scores_the_rebuilt_graphs_as_it_scores_the_snapshots(fresh_install):
    """Item 12's receipt, re-proved on a fresh checkout: no data, no builder's machine."""
    import sys
    sys.path.insert(0, str(REPO))
    from evals.framing_matcher_eval import DATASET, score
    from aughor.ontology.framing import frame_question
    rebuilt, original = {}, {}
    for key, (path, schema) in HOSTS.items():
        snapshot = json.loads((REPO / path).read_text())
        fresh_install[RANDOM_ID] = key
        rebuilt[key], _ = OV.apply_overrides(_stripped(snapshot), RANDOM_ID, schema)
        original[key] = OntologyGraph.model_validate(snapshot)
    host = {"lux": "luxexperience", "olist": "olist"}
    items = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    for it in items:
        a = score(frame_question(it["question"], original[host[it["host"]]]).model_dump(), it["expect"])
        b = score(frame_question(it["question"], rebuilt[host[it["host"]]]).model_dump(), it["expect"])
        assert a["ok"] == b["ok"], it["id"]


def test_withdrawing_a_shipped_declaration_hides_it_on_this_install_only(fresh_install):
    path, schema = HOSTS["luxexperience"]
    fresh_install[RANDOM_ID] = "luxexperience"
    assert OV._unlink(RANDOM_ID, schema, "rule", "vip_customers") is True
    graph, _ = OV.apply_overrides(_stripped(json.loads((REPO / path).read_text())), RANDOM_ID, schema)
    assert "vip_customers" not in graph.rules and "eu_markets" in graph.rules
    assert (REPO / "data/shipped/ontology_overrides/key=luxexperience/luxexperience/rule/vip_customers.yaml").exists()
    assert OV.override_scopes(RANDOM_ID) == ["luxexperience"]


# ── PENDING item 26 — every shipped declaration compiles on a clone ─────────────────────────────

def _clone(snapshot: dict) -> OntologyGraph:
    """What a fresh clone builds before any declaration: the snapshot without ANY part a person declared — the
    processes, rules and actions `_stripped` removes, and also the bindings a person set and the links a person
    declared. `_stripped` kept those, which is how the shipped `order_to_shipment` could not compile on a clone (its
    shipped stage reads `ship_date`, which only the `shipments` binding supplies) while this file stayed green."""
    clone = json.loads(json.dumps(snapshot))
    for entity in clone["entities"].values():
        entity["bindings"] = [b for b in (entity.get("bindings") or []) if b.get("source") != "human"]
    rels = clone.get("relationships") or {}
    declared = {rid for rid, r in rels.items() if r.get("declared") or r.get("origin") == "human"}
    clone["relationships"] = {rid: r for rid, r in rels.items() if rid not in declared}
    kept = {frozenset((r["from_entity"], r["to_entity"])) for r in clone["relationships"].values()}
    clone["relationship_index"] = {a: [b for b in bs if frozenset((a, b)) in kept]
                                   for a, bs in (clone.get("relationship_index") or {}).items()}
    return _stripped(clone)


def _problems(graph: OntologyGraph) -> list[str]:
    """Each declaration through its OWN door's resolver — the check that runs before a person's declaration is
    written, so a shipped one is held to exactly the same law."""
    from aughor.ontology.business_rules import resolve_rule
    from aughor.ontology.processes import resolve_process
    from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query, find_object_type
    out = []
    for pid, p in graph.processes.items():
        fields = json.loads(json.dumps({"entity": p.entity, "stages": [s.model_dump(exclude_none=True) for s in p.stages]}))
        problem, _ = resolve_process(graph, pid, fields)
        out += [f"process {pid}: {problem}"] if problem else []
    for rid, r in graph.rules.items():
        problem, _ = resolve_rule(graph, rid, {k: v for k, v in r.model_dump().items()
                                               if k in ("entity", "kind", "property", "values", "conditions")})
        out += [f"rule {rid}: {problem}"] if problem else []
    for mid, m in graph.metrics.items():
        if not m.verified:
            continue
        try:
            entity = find_object_type(graph, m.entity)
            compile_object_query({"object_type": entity.api_name, "measures": [{"name": "v", "metric": mid}]}, graph)
        except ObjectQueryRefused as exc:
            out.append(f"metric {mid}: {exc.reason}")
    for action in graph.declared_actions():
        try:
            find_object_type(graph, action.entity or action.object_type)
        except ObjectQueryRefused as exc:
            out.append(f"action {action.id}: {exc.reason}")
    return out


@pytest.mark.parametrize("key", sorted(HOSTS))
def test_every_shipped_declaration_compiles_on_a_clone(fresh_install, key):
    path, schema = HOSTS[key]
    fresh_install[RANDOM_ID] = key
    graph, _ = OV.apply_overrides(_clone(json.loads((REPO / path).read_text())), RANDOM_ID, schema)
    assert graph.processes or graph.rules, "nothing shipped — the check would be vacuous"
    assert _problems(graph) == []


def test_the_check_sees_a_declaration_that_cannot_compile(fresh_install, monkeypatch):
    """The other direction: without the shipped bindings, the shipped process is refused — as it was on a clone."""
    path, schema = HOSTS["luxexperience"]
    fresh_install[RANDOM_ID] = "luxexperience"
    real = OV._visible

    def without_bindings(rel_dir, pattern, **kw):
        return [f for f in real(rel_dir, pattern, **kw) if "entity" not in f.parts]
    monkeypatch.setattr(OV, "_visible", without_bindings)
    graph, _ = OV.apply_overrides(_clone(json.loads((REPO / path).read_text())), RANDOM_ID, schema)
    assert any(p.startswith("process order_to_shipment: stage 'shipped'") for p in _problems(graph)), _problems(graph)


def test_the_shipped_bindings_and_links_rebuild_what_was_served(fresh_install):
    path, schema = HOSTS["luxexperience"]
    snapshot = json.loads((REPO / path).read_text())
    fresh_install[RANDOM_ID] = "luxexperience"
    graph, _ = OV.apply_overrides(_clone(snapshot), RANDOM_ID, schema)
    served = OntologyGraph.model_validate(snapshot)
    fields = ("name", "kind", "table", "key", "rows", "objects", "covered", "verified")
    for eid, entity in served.entities.items():
        want = {b.name: ({f: getattr(b, f) for f in fields}, sorted(b.properties)) for b in entity.bindings
                if b.source == "human"}
        got = {b.name: ({f: getattr(b, f) for f in fields}, sorted(b.properties)) for b in graph.entities[eid].bindings
               if b.name in want}
        assert got == want, eid
    for rid, rel in served.relationships.items():
        if rel.origin == "human":
            built = graph.relationships[rid]
            assert (built.from_entity, built.to_entity, built.from_col, built.to_col, built.cardinality) == (
                rel.from_entity, rel.to_entity, rel.from_col, rel.to_col, rel.cardinality), rid
