"""`scope.connections` was declared, validated for presence, and read by nothing.

`PackManifest` has carried the field since P0 and `validate` warned when it was missing,
so every pack on disk states which connections it is for — and every pack was offered to
every connection regardless. Both ends of the feature existed; the feature did not.

That was harmless while packs were general and authored here. Engine packs made it a
defect: a Bigtable pack and a BigQuery pack both say `['*']`, so a DuckDB question could
route to either, and the roster a model reads could not tell it that neither had anything
to do with the warehouse in front of it.

These tests hold the wiring, not the matcher — a matcher nothing calls is what was already
there. Each surface that can put a pack in front of a model is asserted separately:
the tool loop's two rungs, the steering path, and the activation gate.
"""
from __future__ import annotations

import types

import pytest
import yaml

from aughor.packs import scope as pack_scope
from aughor.packs.loader import PROSE_FILE, load_pack
from aughor.packs.promote import PromotionRefused, set_status


def _write_pack(root, pack_id, *, scope=None, status="draft", partial=True,
                prose="Partition by ingestion time before scanning.", **manifest_extra):
    d = root / pack_id
    d.mkdir(parents=True, exist_ok=True)
    manifest = {"id": pack_id, "name": pack_id, "version": 1, "status": status,
                "partial": partial, "domains": ["Databases"]}
    if scope is not None:
        manifest["scope"] = {"connections": scope}
    manifest.update(manifest_extra)
    (d / "pack.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    (d / PROSE_FILE).write_text(f"# {pack_id}\n\n{prose}\n")
    return d


@pytest.fixture
def packs_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_PACKS_DIR", str(tmp_path))
    monkeypatch.setenv("AUGHOR_IMPORTED_PACKS_DIR", str(tmp_path / "_none"))
    return tmp_path


@pytest.fixture
def engine(monkeypatch):
    """Declare what engine the connection under test is, without a live registry."""
    def _set(conn_type):
        monkeypatch.setattr(pack_scope, "conn_type_of", lambda _cid: conn_type)
    return _set


# ── reading the field ────────────────────────────────────────────────────────────

def test_a_pack_that_says_nothing_applies_everywhere():
    """The default has to survive: every pack on disk today omits the key or says `*`,
    and a stricter reading would silently un-deploy all of them."""
    for stated in (None, {}, {"connections": None}, {"connections": ["*"]}):
        assert pack_scope.entries(stated) == ["*"], stated


def test_a_scalar_is_read_as_a_one_entry_list():
    """`connections: bigquery` is what a human writes. Reading it character-by-character
    would match nothing and report no error."""
    assert pack_scope.entries({"connections": "engine:BigQuery"}) == ["engine:bigquery"]


def test_an_empty_list_matches_nothing_rather_than_everything():
    """The one unambiguous way to say 'no connection' must not be read as its opposite.
    Failing open here would be a silent widening of what a model may read."""
    assert pack_scope.entries({"connections": []}) == []
    assert not pack_scope.matches([], connection_id="c1", conn_type="duckdb")


def test_an_engine_entry_matches_that_connector_type_only():
    ents = pack_scope.entries({"connections": ["engine:bigquery"]})
    assert pack_scope.matches(ents, connection_id="c1", conn_type="bigquery")
    assert not pack_scope.matches(ents, connection_id="c1", conn_type="duckdb")


def test_an_unresolvable_engine_is_not_a_match():
    """An empty conn_type means 'could not be determined'. Treating it as a match would
    fail open on exactly the question this module exists to answer."""
    ents = pack_scope.entries({"connections": ["engine:bigquery"]})
    assert not pack_scope.matches(ents, connection_id="c1", conn_type="")
    assert pack_scope.matches(["*"], connection_id="c1", conn_type=""), (
        "'*' claims nothing about the engine, so it still applies")


def test_a_bare_entry_is_a_connection_id():
    ents = pack_scope.entries({"connections": ["conn-abc"]})
    assert pack_scope.matches(ents, connection_id="conn-abc", conn_type="duckdb")
    assert not pack_scope.matches(ents, connection_id="conn-xyz", conn_type="duckdb")


def test_every_registered_connector_type_is_a_legal_engine_name():
    """The known-engine set is what tells a typo apart from an engine nobody has
    connected yet. If it drifts from the connector registry, activating a correct scope
    starts failing — so it is asserted against the registry itself, not a copy."""
    from aughor.connectors.registry import REGISTRY

    known = pack_scope.known_engines()
    missing = [t for t in REGISTRY.supported_types() if t not in known]
    assert not missing, f"registered connectors no scope may name: {missing}"
    for opened_outside_the_registry in ("duckdb", "postgres"):
        assert opened_outside_the_registry in known


def test_unknown_engines_are_named_individually():
    ents = pack_scope.entries({"connections": ["engine:bigquery", "engine:bigqeury", "c1"]})
    assert pack_scope.unknown_engines(ents) == ["bigqeury"]


# ── the connector-type lookup ────────────────────────────────────────────────────

def test_the_type_of_a_connection_is_readable_without_its_secret_key(monkeypatch):
    """`get_dsn` was the only way to ask, and it decrypts — so an install with no
    `AUGHOR_SECRET_KEY` could not answer a question that has nothing to do with secrets."""
    from aughor.db import registry

    def _boom(_v):
        raise RuntimeError("no secret key configured")
    monkeypatch.setattr(registry, "_decrypt", _boom)

    assert registry.get_conn_type(registry.WORKSPACE_ID) == "local_upload"
    assert registry.get_conn_type(registry.POSTGRES_BUILTIN_ID) == "postgres"


def test_an_unreadable_registry_means_unknown_not_a_crash(monkeypatch):
    """This is called to paint a roster. It must degrade, never take the roster down."""
    def _boom(_cid):
        raise RuntimeError("registry is gone")
    monkeypatch.setattr("aughor.db.registry.get_conn_type", _boom)

    assert pack_scope.conn_type_of("c1") == ""


def test_the_type_is_resolved_once_for_a_whole_roster(monkeypatch):
    calls = []
    monkeypatch.setattr(pack_scope, "conn_type_of",
                        lambda cid: calls.append(cid) or "bigquery")
    read = pack_scope.lazy_conn_type("c1")

    assert [read(), read(), read()] == ["bigquery"] * 3
    assert calls == ["c1"], "one lookup, memoised for the loop"


def test_an_all_star_roster_never_opens_the_registry(monkeypatch):
    """Every pack on disk today is `*`-scoped. Resolving the connector type for them
    would add a store read to every roster and every plan for an answer nobody asked."""
    monkeypatch.setattr(pack_scope, "conn_type_of",
                        lambda _cid: pytest.fail("resolved a type no pack asked about"))
    pack = types.SimpleNamespace(manifest=types.SimpleNamespace(scope={"connections": ["*"]}))

    assert pack_scope.filter_applicable([pack], "c1") == [pack]


# ── rung 1: the roster the model scans ───────────────────────────────────────────

def test_the_roster_marks_an_out_of_scope_pack_unreadable(packs_dir, engine):
    from aughor.agent import platform_tools as pt

    _write_pack(packs_dir, "bigtable", scope=["engine:bigtable"], status="active")
    engine("duckdb")

    entry = pt.list_packs("c1", {})["packs"][0]

    assert entry["applies_to_this_connection"] is False
    assert entry["readable"] is False, "active is not enough — it must also be FOR here"
    assert "bigtable" in entry["why_not"]


def test_an_out_of_scope_pack_is_listed_but_costs_no_description(packs_dir, engine):
    """Listed, because hiding it makes 'no pack for this' and 'no such pack' identical to
    anyone asking what is installed. Without a description, because rung 1 is scanned on
    every call and a paragraph about another engine can only mislead."""
    from aughor.agent import platform_tools as pt

    _write_pack(packs_dir, "bigtable", scope=["engine:bigtable"], status="active",
                prose="Design a row key that avoids hotspotting.")
    engine("duckdb")

    entry = pt.list_packs("c1", {})["packs"][0]

    assert entry["id"] == "bigtable", "still in the inventory"
    assert "description" not in entry
    assert "hotspotting" not in str(entry)


def test_the_roster_serves_a_pack_scoped_to_this_engine(packs_dir, engine):
    from aughor.agent import platform_tools as pt

    _write_pack(packs_dir, "bq", scope=["engine:bigquery"], status="active",
                prose="Partition before you scan.")
    engine("bigquery")

    entry = pt.list_packs("c1", {})["packs"][0]

    assert entry["applies_to_this_connection"] is True
    assert entry["readable"] is True
    assert "Partition" in entry["description"]


# ── rung 2: the body ─────────────────────────────────────────────────────────────

def test_read_pack_refuses_another_engines_pack_and_says_which(packs_dir, engine):
    """The failure this gate exists for: prose that is confident, specific, and about a
    system the reader is not connected to — indistinguishable, once read, from prose that
    fits."""
    from aughor.agent import platform_tools as pt

    _write_pack(packs_dir, "spanner", scope=["engine:spanner"], status="active",
                prose="Interleave child tables under their parent.")
    engine("duckdb")

    out = pt.read_pack("c1", {"pack_id": "spanner"})

    assert out["readable"] is False
    assert "Interleave" not in str(out), "the body must not leak through the refusal"
    assert "spanner" in out["why"] and out["scope"] == ["engine:spanner"]


def test_read_pack_distinguishes_wrong_engine_from_not_promoted(packs_dir, engine):
    """Two different problems. 'promote it' and 'that advice is for another engine' lead
    the reader to opposite next steps."""
    from aughor.agent import platform_tools as pt

    _write_pack(packs_dir, "draft-here", scope=["engine:duckdb"], status="draft")
    _write_pack(packs_dir, "wrong-engine", scope=["engine:spanner"], status="active")
    engine("duckdb")

    assert "promotes" in pt.read_pack("c1", {"pack_id": "draft-here"})["why"]
    assert "not one of them" in pt.read_pack("c1", {"pack_id": "wrong-engine"})["why"]


def test_read_pack_serves_the_body_when_the_engine_matches(packs_dir, engine):
    from aughor.agent import platform_tools as pt

    _write_pack(packs_dir, "bq", scope=["engine:bigquery"], status="active",
                prose="Partition before you scan.")
    engine("bigquery")

    out = pt.read_pack("c1", {"pack_id": "bq"})

    assert out["readable"] is True and "Partition before you scan." in out["prose"]
    assert out["scope"] == ["engine:bigquery"]


# ── the steering path ────────────────────────────────────────────────────────────

def test_a_pack_for_another_engine_does_not_steer_a_plan(monkeypatch):
    """The binding gate does not catch this on its own: a role binds against whatever
    tables fit, and tables fit regardless of which engine holds them."""
    from aughor.packs import intake

    bq = types.SimpleNamespace(
        id="bq", manifest=types.SimpleNamespace(
            partial=False, status="active", scope={"connections": ["engine:bigquery"]}))
    monkeypatch.setattr(intake, "active_packs", lambda: [bq])
    monkeypatch.setattr(pack_scope, "conn_type_of", lambda _cid: "duckdb")
    monkeypatch.setattr(intake, "select_pack",
                        lambda *a, **k: pytest.fail("routed a pack for another engine"))

    assert intake.injection_for_question("partitioning question", "conn-1") is None


def test_a_pack_for_this_engine_still_steers(monkeypatch):
    """The other half — a filter that removes everything passes the test above for the
    wrong reason."""
    from aughor.packs import intake

    bq = types.SimpleNamespace(
        id="bq", manifest=types.SimpleNamespace(
            partial=False, status="active", scope={"connections": ["engine:bigquery"]}))
    monkeypatch.setattr(intake, "active_packs", lambda: [bq])
    monkeypatch.setattr(pack_scope, "conn_type_of", lambda _cid: "bigquery")
    monkeypatch.setattr(intake, "select_pack", lambda q, pool: (pool[0], 2.0))
    monkeypatch.setattr(intake, "load_binding", lambda *a, **k: {"bindings": {"x": "y"}})
    monkeypatch.setattr(intake, "build_injection",
                        lambda pack, binding, business_model, currency_code:
                        types.SimpleNamespace(pack_id=pack.id))

    assert intake.injection_for_question("partitioning question", "conn-1").pack_id == "bq"


# ── the activation gate ──────────────────────────────────────────────────────────

def test_activating_a_pack_scoped_to_nothing_is_refused(packs_dir):
    """Activation that changes nothing must say so. A no-op reporting success is how the
    governed-action plane ended up complete and inert."""
    _write_pack(packs_dir, "nowhere", scope=[])

    with pytest.raises(PromotionRefused) as exc:
        set_status("nowhere", "active", packs_dir=packs_dir)

    assert "no connection" in str(exc.value)
    assert load_pack(packs_dir / "nowhere").manifest.status == "draft"


def test_activating_a_pack_with_a_misspelled_engine_is_refused(packs_dir):
    """A typo and a correct scope for an unconnected engine look identical at match time:
    both never match. This is the one moment they can be told apart."""
    _write_pack(packs_dir, "typo", scope=["engine:bigqeury"])

    with pytest.raises(PromotionRefused) as exc:
        set_status("typo", "active", packs_dir=packs_dir)

    assert "bigqeury" in str(exc.value)


def test_a_scope_for_an_engine_nobody_has_connected_activates_fine(packs_dir):
    """Legitimate and common: the pack is installed before the warehouse is."""
    _write_pack(packs_dir, "bq", scope=["engine:bigquery"])

    assert set_status("bq", "active", packs_dir=packs_dir).manifest.status == "active"


def test_promotion_preserves_the_scope_it_was_gated_on(packs_dir):
    """`set_status` re-dumps the raw manifest. A scope dropped by the round trip would
    silently widen the pack to every connection at the moment it became readable."""
    _write_pack(packs_dir, "bq", scope=["engine:bigquery"], source_url="https://x.invalid")

    set_status("bq", "active", packs_dir=packs_dir)

    raw = yaml.safe_load((packs_dir / "bq" / "pack.yaml").read_text())
    assert raw["scope"] == {"connections": ["engine:bigquery"]}
    assert raw["source_url"] == "https://x.invalid"


# ── validation ───────────────────────────────────────────────────────────────────

def test_validate_warns_about_a_scope_that_can_never_match(packs_dir):
    from aughor.packs import validate_pack

    _write_pack(packs_dir, "typo", scope=["engine:bigqeury"])
    _write_pack(packs_dir, "nowhere", scope=[])

    assert any("bigqeury" in w for w in validate_pack(packs_dir / "typo").warnings)
    assert any("NO connection" in w for w in validate_pack(packs_dir / "nowhere").warnings)


def test_validate_is_quiet_about_a_scope_that_can(packs_dir):
    from aughor.packs import validate_pack

    _write_pack(packs_dir, "bq", scope=["engine:bigquery"])

    assert not [w for w in validate_pack(packs_dir / "bq").warnings if "scope" in w]
