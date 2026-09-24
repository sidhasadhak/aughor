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
