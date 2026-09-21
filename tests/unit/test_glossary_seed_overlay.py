"""The glossary as a shipped seed with this install's instance over it.

The autoseed sidecar already took model-written entries out of `data/glossary.yaml`, but a
person's edit, the explorer's column caveats and an agent's grain notes still rewrote the
tracked file, and every save rewrote it whole — so the first upstream edit of it stranded that
install's update. The seed now ships at `data/shipped/glossary.yaml`, this install's entries go
to an ignored instance file, and `data/glossary.yaml` is frozen and read once, to convert.

Every test builds its own files in tmp and repoints the module at them BEFORE any env var is
removed, so none can reach a developer's `data/`.
"""
from __future__ import annotations

import hashlib

import pytest
import yaml

from aughor.semantic import glossary as G
from aughor.semantic.glossary import GlossaryStoreError

BASELINE = {
    "tables": {
        "orders": {"description": "shipped orders", "grain": "one row per order"},
        "customers": {"description": "shipped customers"},
    },
    "connections": {"c1": {"tables": {"orders": {"description": "c1's orders"}}}},
}


def dump(p, doc):
    p.write_text(yaml.safe_dump(doc, sort_keys=False))


@pytest.fixture
def layers(tmp_path, monkeypatch):
    seed, base, legacy = tmp_path / "seed.yaml", tmp_path / "base.yaml", tmp_path / "glossary.yaml"
    inst = tmp_path / "inst" / "glossary.instance.yaml"     # its own dir, so a sidecar resolved
    inst.parent.mkdir()                                     # beside it is told apart from the right one
    for p in (seed, base, legacy):
        dump(p, BASELINE)
    monkeypatch.setattr(G, "_LEGACY_PATH", legacy)
    monkeypatch.setattr(G, "_LEGACY_BASELINE", base)
    monkeypatch.setattr(G, "_DEFAULT_PATH", inst)
    monkeypatch.setenv("AUGHOR_HOME", str(tmp_path / "home"))           # no marker: nothing rehomes
    monkeypatch.setenv("AUGHOR_GLOSSARY_SEED_PATH", str(seed))
    monkeypatch.setenv("AUGHOR_GLOSSARY_PATH", str(inst))

    class L:
        pass
    ns = L()
    ns.tmp, ns.seed, ns.base, ns.legacy, ns.inst = tmp_path, seed, base, legacy, inst
    ns.unset = lambda: monkeypatch.delenv("AUGHOR_GLOSSARY_PATH")     # the production route
    return ns


def pruned(d):
    """Structure without empty containers — the contract is the entries, not empty scaffolding."""
    if isinstance(d, dict):
        out = {k: pruned(v) for k, v in d.items()}
        return {k: v for k, v in out.items() if v not in ({}, None)}
    return d


# ── the differential: the overlay answers what the single file answered ─────────────────────

def _ops(path):
    G.update_table("orders", description="ours", path=path)
    G.update_column("customers", "id", description="the key", path=path)
    G.update_table("new_t", description="a table we added", path=path)
    doc = G.load_glossary(path)
    doc["tables"].pop("customers")
    doc.setdefault("connections", {})["c2"] = {"tables": {"x": {"description": "c2 x"}}}
    doc["connections"]["c1"]["tables"].pop("orders")
    G.save_glossary(doc, path)
    G.update_table("customers", description="back again", path=path)


def test_every_write_leaves_the_same_glossary_as_the_single_file_store(layers):
    """The oracle is today's store — one file, written whole — started from the same content.
    Kills: a removal with no hidden unit (the shipped entry comes back), a re-add that stays
    hidden, merging by FIELD rather than by unit. (A writer that stores the whole merged view
    passes this one; the next test is the one it fails.)"""
    oracle = layers.tmp / "oracle" / "glossary.yaml"
    oracle.parent.mkdir()
    dump(oracle, BASELINE)
    seed_before = layers.seed.read_bytes()
    _ops(None)
    _ops(oracle)
    assert pruned(G.load_glossary()) == pruned(G.load_glossary(oracle))
    assert layers.seed.read_bytes() == seed_before, "a writer wrote the shipped seed"


def test_an_untouched_shipped_entry_follows_an_upstream_edit(layers):
    """Kills: a writer that stores the whole view as this install's — every shipped entry would be
    pinned, and no upstream fix to the glossary would ever arrive."""
    G.update_table("new_t", description="ours")
    edited = {**BASELINE, "tables": {**BASELINE["tables"], "customers": {"description": "upstream fixed it"}}}
    dump(layers.seed, edited)
    assert G.load_glossary()["tables"]["customers"]["description"] == "upstream fixed it"
    assert G.load_glossary()["tables"]["new_t"]["description"] == "ours"


# ── before the first save: the frozen file, read in memory ──────────────────────────────────

def test_a_fresh_install_reads_the_current_seed(layers):
    layers.unset()
    new = {"tables": {"orders": {"description": "upstream v2"}, "returns": {"description": "new"}}}
    dump(layers.seed, new)
    assert pruned(G.load_glossary()) == new
    assert not layers.inst.exists(), "a read wrote the instance file"


def test_a_used_install_reads_what_it_read_before(layers):
    """An edited shipped entry stays edited, an added one stays, a removed one stays removed —
    and nothing is written by reading. Kills: a derive that hides nothing, one that drops echoes
    against the CURRENT seed instead of the frozen baseline, a conversion on read."""
    used = {"tables": {"orders": {"description": "ours"}, "extra": {"description": "added here"}},
            "connections": {"c1": {"tables": {"orders": {"description": "c1's orders"}}}}}
    dump(layers.legacy, used)
    dump(layers.seed, {**BASELINE, "tables": {**BASELINE["tables"], "orders": {"description": "upstream"}}})
    layers.unset()
    assert pruned(G.load_glossary()) == used
    assert not layers.inst.exists()


def test_the_first_save_converts_and_never_touches_the_frozen_file(layers):
    used = {"tables": {"extra": {"description": "added here"}}}          # both shipped tables removed
    dump(layers.legacy, used)
    before = layers.legacy.read_bytes()
    layers.unset()
    G.update_table("t2", description="now")
    assert layers.legacy.read_bytes() == before
    doc = yaml.safe_load(layers.inst.read_text())
    assert doc["format"] == G.INSTANCE_FORMAT
    assert doc["converted_from"]["sha256"] == hashlib.sha256(before).hexdigest()
    assert ["tables", "orders"] in doc["hidden"]
    assert set(G.load_glossary()["tables"]) == {"extra", "t2"}
    assert G._converted_marker(layers.inst).exists()


def test_a_missing_instance_after_conversion_is_an_error_not_a_quiet_reread(layers):
    """After the first save the frozen file is stale; re-reading it would silently drop every entry
    saved since. Kills: deriving whenever the instance is absent, and a save that re-converts."""
    layers.unset()
    G.update_table("t2", description="saved after conversion")
    layers.inst.rename(layers.tmp / "aside.yaml")
    with pytest.raises(GlossaryStoreError, match="Restore it from a backup"):
        G.load_glossary()
    with pytest.raises(GlossaryStoreError):
        G.save_glossary({"tables": {}})
    assert not layers.inst.exists()


# ── reads that must not quietly answer less ─────────────────────────────────────────────────

@pytest.mark.parametrize("body", [": not: yaml: [", "- a list\n", "just a string\n"])
def test_an_unreadable_instance_is_an_error_and_is_left_alone(layers, body):
    layers.inst.write_text(body)
    with pytest.raises(GlossaryStoreError):
        G.load_glossary()
    with pytest.raises(GlossaryStoreError):
        G.update_table("x", description="y")
    assert layers.inst.read_text() == body


def test_a_named_instance_path_never_reads_the_checkouts_file(layers):
    """Kills: deriving from the frozen file while AUGHOR_GLOSSARY_PATH names an absent instance —
    on a developer's machine that is their live glossary."""
    dump(layers.legacy, {"tables": {"live_only": {"description": "developer's"}}})
    assert "live_only" not in (G.load_glossary().get("tables") or {})


def test_a_plain_glossary_at_a_named_path_reads_as_it_did_alone(layers):
    """A pre-overlay file an operator (or a test) names is a WHOLE glossary: a shipped entry it
    lacks stays gone, and only an entry shipped since arrives. Kills: reading it with nothing hidden."""
    dump(layers.inst, {"tables": {"orders": {"description": "mine"}}})
    dump(layers.seed, {"tables": {**BASELINE["tables"], "returns": {"description": "shipped since"}}})
    assert set(G.load_glossary()["tables"]) == {"orders", "returns"}
    assert G.load_glossary()["tables"]["orders"]["description"] == "mine"


def test_the_shipped_files_are_never_a_write_target(layers, monkeypatch):
    monkeypatch.setenv("AUGHOR_GLOSSARY_PATH", str(layers.seed))
    with pytest.raises(GlossaryStoreError, match="shipped"):
        G.update_table("x", description="y")
    with pytest.raises(GlossaryStoreError, match="shipped"):
        G.save_glossary({"tables": {}}, layers.legacy)


# ── the generated sidecar stays where it always resolved ────────────────────────────────────

def test_generated_entries_still_go_to_the_sidecar_beside_the_frozen_file(layers):
    """The sidecar is resolved from the FROZEN file's place, never the instance's: the instance
    rehomes after `migrate-state`, and an install that migrated before this change kept writing
    its sidecar in the checkout. Kills: deriving the sidecar from the instance path."""
    layers.unset()
    G.save_glossary({**BASELINE, "tables": {**BASELINE["tables"],
                                            "gen": {"description": "m", "auto_generated": True}}})
    assert G.generated_path() == layers.tmp / "glossary_generated.yaml"
    assert "gen" in yaml.safe_load(G.generated_path().read_text())["tables"]
    assert "gen" not in (yaml.safe_load(layers.inst.read_text())["glossary"].get("tables") or {})


def test_a_migrated_home_moves_the_instance_but_not_the_sidecar(tmp_path, monkeypatch):
    """Checkout-shaped paths, so rehoming really applies. The instance is new state and follows the
    home; the sidecar has always resolved beside the frozen file, which never rehomes — so an
    install that migrated before this change keeps reading the sidecar it kept writing."""
    data = tmp_path / "checkout" / "data"
    data.mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".aughor-home").write_text("migrated")
    monkeypatch.setenv("AUGHOR_HOME", str(home))
    monkeypatch.setattr(G, "_LEGACY_PATH", data / "glossary.yaml")
    monkeypatch.setattr(G, "_DEFAULT_PATH", data / "glossary.instance.yaml")
    monkeypatch.delenv("AUGHOR_GLOSSARY_PATH")
    assert G._default_path() == home / "state" / "glossary.instance.yaml"
    assert G.generated_path() == data / "glossary_generated.yaml"
