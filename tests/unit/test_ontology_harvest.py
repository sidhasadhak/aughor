"""What the harvester is allowed to assert about a definition it found.

The load-bearing test is `test_the_registry_is_never_marked_verified`: `verified` means
the formula BOUND against the live database, and if anything else is ever allowed to set
it, `authority`'s tier silently collapses into the popularity ranking it exists to beat.
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.ontology.authority import choose
from aughor.ontology.harvest import Evidence, from_override, from_registry, harvest, reliance


def _ov(**kw):
    base = dict(fields={"formula_sql": "SUM(net)"}, edited_by="Priya",
                edited_at="2026-09-01T10:00:00Z", source="human", note="",
                binding={"formula_sql": {"bound": True, "note": ""}})
    base.update(kw)
    ns = SimpleNamespace(**base)
    ns.sql_field_ok = lambda f: bool((ns.binding.get(f) or {}).get("bound") is True)
    return ns


def _md(**kw):
    base = dict(sql="SUM(gross)", label="Revenue", name="revenue")
    base.update(kw)
    return SimpleNamespace(**base)


# ── an override is a real authored claim ─────────────────────────────────────────────

def test_an_override_carries_its_author_date_and_bind_receipt():
    d = from_override(_ov())
    assert d is not None
    assert d.author == "Priya" and d.recorded_at == "2026-09-01T10:00:00Z"
    assert d.verified is True and "bound against the live database" in d.verification_note


def test_an_override_that_never_bound_is_a_claim_not_a_fact():
    d = from_override(_ov(binding={"formula_sql": {"bound": False, "note": "bad column"}}))
    assert d is not None and d.verified is False
    assert "recorded as a claim, not as a fact" in d.verification_note


def test_an_unattributed_edit_stays_unattributed():
    """Filling in 'system' or the current user would be a lie that ranks BETTER than the
    truth — `authority` scores an unattributed claim lower on purpose."""
    assert from_override(_ov(edited_by="")).author == ""


def test_an_override_that_did_not_touch_the_formula_is_not_a_definition():
    assert from_override(_ov(fields={"description": "nicer words"})) is None
    assert from_override(_ov(fields={"formula_sql": "   "})) is None


# ── the registry may never be flattered ──────────────────────────────────────────────

def test_the_registry_is_never_marked_verified():
    """The incumbent definition, with no author and no bind receipt. Marking it verified
    because it is curated would collapse the tier that makes `authority` safe."""
    d = from_registry(_md())
    assert d is not None
    assert d.verified is False and d.author == "" and d.certified is False
    assert "no bind receipt" in d.verification_note


def test_the_registry_entry_names_itself_readably():
    d = from_registry(_md())
    assert d is not None and "Revenue" in d.source_asset


def test_a_registry_entry_with_no_sql_is_not_a_definition():
    assert from_registry(_md(sql="")) is None


# ── reliance ─────────────────────────────────────────────────────────────────────────

def test_reliance_counts_executed_statements_ignoring_spelling():
    ran = ["SELECT  sum(NET)  FROM orders", "select 1", "SELECT SUM(net) FROM o WHERE x"]
    assert reliance("SUM(net)", ran) == 2


def test_reliance_of_an_empty_formula_is_zero_not_everything():
    assert reliance("   ", ["SELECT 1", "SELECT 2"]) == 0


# ── the harvest as a whole ───────────────────────────────────────────────────────────

def test_harvest_produces_competing_claims_the_law_can_rank():
    ev = Evidence(overrides=[_ov()], registry=_md(),
                  executed_sql=["SELECT SUM(net) FROM orders"] * 3)
    ds = harvest(ev)
    assert len(ds) == 2
    verified = [d for d in ds if d.verified]
    assert len(verified) == 1 and verified[0].author == "Priya"
    assert verified[0].use_count == 3

    # ...and the law picks the bound one over the incumbent registry entry.
    c = choose(ds)
    assert c.winner.author == "Priya" and c.contested
    assert "verified against the live database" in c.why


def test_the_same_formula_from_two_places_is_merged_not_double_counted():
    """A definition copied into three places must not out-rank a verified one by being
    repeated — that is the exact failure this design exists to avoid."""
    ds = harvest(Evidence(overrides=[_ov(), _ov(edited_by="Sam")],
                          registry=_md(sql="SUM(net)")))
    assert len(ds) == 1
    assert ds[0].verified is True and ds[0].author in ("Priya", "Sam")


def test_the_stronger_record_survives_a_merge():
    unbound = _ov(edited_by="", binding={"formula_sql": {"bound": False}})
    bound = _ov(edited_by="Priya")
    assert harvest(Evidence(overrides=[unbound, bound]))[0].verified is True
    assert harvest(Evidence(overrides=[bound, unbound]))[0].verified is True


def test_a_deployment_with_only_a_registry_still_harvests_something():
    ds = harvest(Evidence(registry=_md()))
    assert len(ds) == 1 and ds[0].verified is False


def test_nothing_at_all_harvests_nothing_without_raising():
    assert harvest(Evidence()) == []



def _isolate(monkeypatch, *, overrides=(), registry=(), executed=()):
    """Cut the route off from the real stores.

    Without this the route reads data/metrics.json and the live history DB, so the test
    measures whatever happens to be on the machine — it caught a real `SUM(total_amount)`
    the first time it ran.
    """
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics",
                        lambda *a, **k: list(registry))
    monkeypatch.setattr("aughor.ontology.overrides.load_overrides",
                        lambda *a, **k: list(overrides))
    monkeypatch.setattr("aughor.db.history.recent_executed_sql",
                        lambda *a, **k: list(executed))


# ── the route the panel reads ────────────────────────────────────────────────────────

def test_provenance_route_returns_the_graphs_own_formula_as_a_claim(client, monkeypatch):
    """Even with no overrides and no registry, the metric's own formula is a CLAIM —
    and it is verified only if the graph says it bound, never because it is incumbent."""
    from aughor.ontology.models import OntologyGraph, OntologyMetric
    import aughor.routers.ontology as mod

    graph = OntologyGraph(connection_id="c1", schema_fingerprint="fp", entities={}, metrics={"revenue": OntologyMetric(
        id="revenue", display_name="Revenue", entity="orders",
        formula_sql="SUM(net)", verified=False,
        verification_note="never bound", known_divergent_calculations=["gross elsewhere"])})
    monkeypatch.setattr(mod, "_get_ontology_graph", lambda *a, **k: graph)
    _isolate(monkeypatch)

    body = client.get("/ontology/metrics/revenue/provenance").json()
    assert body["display_name"] == "Revenue"
    assert len(body["definitions"]) == 1
    assert body["definitions"][0]["verified"] is False
    assert body["chosen"]["formula_sql"] == "SUM(net)"
    assert body["contested"] is False
    assert "NOTHING here is verified" in body["why"]
    assert body["known_divergent_calculations"] == ["gross elsewhere"]


def test_provenance_route_404s_for_a_metric_that_does_not_exist(client, monkeypatch):
    from aughor.ontology.models import OntologyGraph
    import aughor.routers.ontology as mod
    _isolate(monkeypatch)
    monkeypatch.setattr(mod, "_get_ontology_graph",
                        lambda *a, **k: OntologyGraph(connection_id="c1",
                                                      schema_fingerprint="fp",
                                                      entities={}, metrics={}))
    assert client.get("/ontology/metrics/nope/provenance").status_code == 404


def test_a_source_that_raises_does_not_lose_the_other_sources(client, monkeypatch):
    """Per-source best-effort: a broken history store must not cost us the definitions
    the graph and the overrides could evidence."""
    from aughor.ontology.models import OntologyGraph, OntologyMetric
    import aughor.routers.ontology as mod

    graph = OntologyGraph(connection_id="c1", schema_fingerprint="fp", entities={}, metrics={"revenue": OntologyMetric(
        id="revenue", display_name="Revenue", entity="orders", formula_sql="SUM(net)")})
    monkeypatch.setattr(mod, "_get_ontology_graph", lambda *a, **k: graph)
    _isolate(monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("history store is unreadable")
    monkeypatch.setattr("aughor.db.history.recent_executed_sql", _boom)

    body = client.get("/ontology/metrics/revenue/provenance").json()
    assert len(body["definitions"]) == 1 and body["definitions"][0]["use_count"] == 0
