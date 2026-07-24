"""The glossary's two-file split — authored terms tracked, generated ones not.

147 of the glossary's 151 entries are written by the ontology autodoc, so merely RUNNING
the app rewrote a tracked file and buried four hand-authored analyst notes in the churn.
The split routes by ``auto_generated``, which was ALREADY the weakest layer in
:func:`load_merged_glossary`'s precedence — so this makes storage agree with a layering
that existed rather than inventing one.

The contract that matters is that **reading is unchanged**. Every caller still sees one
dict, marker and all, so the three-layer merge below it keeps working untouched. These
tests hold that line, and hold the two directions a split can go wrong: losing an authored
entry, or leaking a generated one back into the tracked file.
"""
from __future__ import annotations

import pytest
import yaml

from aughor.semantic import glossary as G


def _authored(desc="hand-written guidance"):
    return {"description": desc, "grain": "one row per thing"}


def _generated(desc="machine-written"):
    return {"description": desc, "auto_generated": True}


@pytest.fixture
def gpath(tmp_path):
    return tmp_path / "glossary.yaml"


# ── the split itself ──────────────────────────────────────────────────────────

def test_saving_routes_each_entry_to_the_file_that_owns_it(gpath):
    G.save_glossary({"tables": {"customers": _authored(), "default.airports": _generated()}}, gpath)

    authored = yaml.safe_load(gpath.read_text())["tables"]
    generated = yaml.safe_load(G.generated_path(gpath).read_text())["tables"]
    assert set(authored) == {"customers"}
    assert set(generated) == {"default.airports"}


def test_the_tracked_file_never_holds_a_generated_entry(gpath):
    """The whole point: what gets committed must be reviewable, not machine churn."""
    G.save_glossary({"tables": {f"t{i}": _generated() for i in range(50)} | {"real": _authored()}},
                    gpath)
    authored = yaml.safe_load(gpath.read_text())["tables"]
    assert not any(e.get("auto_generated") for e in authored.values())
    assert set(authored) == {"real"}


def test_reading_rejoins_both_files_into_one_dict(gpath):
    G.save_glossary({"tables": {"customers": _authored(), "default.airports": _generated()}}, gpath)
    back = G.load_glossary(gpath)["tables"]
    assert set(back) == {"customers", "default.airports"}
    assert back["default.airports"]["auto_generated"] is True   # marker survives the round trip


def test_a_real_glossary_round_trips_byte_for_byte(gpath):
    """Split then re-join must be the identity. Anything less loses a term."""
    original = {"tables": {
        "customers": _authored("Master customer list."),
        "kpi_daily": _authored("Pre-aggregated daily KPI summary."),
        **{f"default.t{i}": _generated(f"table {i}") for i in range(40)},
    }}
    G.save_glossary(original, gpath)
    assert G.load_glossary(gpath) == original


# ── the migration path ────────────────────────────────────────────────────────

def test_a_combined_legacy_file_is_read_unchanged(gpath):
    """Before any save, the tracked file still holds both kinds. Reading it must work
    exactly as it did — a deployment that has not yet written is not broken."""
    gpath.write_text(yaml.dump({"tables": {"customers": _authored(),
                                           "default.airports": _generated()}}))
    assert not G.generated_path(gpath).exists()
    back = G.load_glossary(gpath)["tables"]
    assert set(back) == {"customers", "default.airports"}


def test_the_first_save_migrates_a_combined_file_in_place(gpath):
    """An app run cleans up after itself; no migration script to remember to run."""
    gpath.write_text(yaml.dump({"tables": {"customers": _authored(),
                                           "default.airports": _generated()}}))
    G.save_glossary(G.load_glossary(gpath), gpath)
    assert set(yaml.safe_load(gpath.read_text())["tables"]) == {"customers"}
    assert set(yaml.safe_load(G.generated_path(gpath).read_text())["tables"]) == {"default.airports"}


def test_no_sidecar_is_created_when_nothing_is_generated(gpath):
    """A deployment that never runs the autodoc keeps exactly one file, as before."""
    G.save_glossary({"tables": {"customers": _authored()}}, gpath)
    assert not G.generated_path(gpath).exists()


def test_removing_the_last_generated_entry_does_not_leave_it_resurrectable(gpath):
    """A stale sidecar would make a deleted entry reappear on the next read."""
    G.save_glossary({"tables": {"a": _generated()}}, gpath)
    assert G.generated_path(gpath).exists()
    G.save_glossary({"tables": {"b": _authored()}}, gpath)
    assert set(G.load_glossary(gpath)["tables"]) == {"b"}


# ── the sidecar follows the authored path ─────────────────────────────────────

def test_the_sidecar_is_derived_from_the_authored_path(tmp_path):
    """Derived, not separately configured — so it follows AUGHOR_GLOSSARY_PATH automatically
    and there is no second env var for the suite to forget to isolate."""
    assert G.generated_path(tmp_path / "glossary.yaml").name == "glossary_generated.yaml"
    assert G.generated_path(tmp_path / "glossary.yaml").parent == tmp_path


def test_the_sidecar_lands_in_the_suites_temp_dir_not_the_repo(monkeypatch, tmp_path):
    """The hermeticity property, stated for the new file: a test write can never reach
    data/glossary_generated.yaml."""
    monkeypatch.setenv("AUGHOR_GLOSSARY_PATH", str(tmp_path / "glossary.yaml"))
    G.save_glossary({"tables": {"x": _generated()}})
    assert (tmp_path / "glossary_generated.yaml").exists()
    assert "aughor/data" not in str(G.generated_path())


# ── the layering it must not disturb ──────────────────────────────────────────

def test_merge_precedence_is_untouched_by_the_split(gpath, monkeypatch):
    """`auto_generated` stays the WEAKEST layer. If the split had stripped the marker or
    changed the join direction, an authored term would stop overriding its generated
    namesake — the one regression that would be silent and wrong."""
    monkeypatch.setenv("AUGHOR_GLOSSARY_PATH", str(gpath))
    monkeypatch.delenv("AUGHOR_DBT_MANIFEST", raising=False)
    G.save_glossary({"tables": {
        "orders": _authored("AUTHORITATIVE: use gross_amount"),
        "orders_gen": _generated(),
    }}, gpath)
    merged = G.load_merged_glossary(gpath)["tables"]
    assert merged["orders"]["description"] == "AUTHORITATIVE: use gross_amount"
    assert merged["orders_gen"].get("auto_generated") is True


def test_an_authored_entry_wins_over_a_generated_one_with_the_same_key(gpath):
    """Both files can carry the same key — the authored one must win, which is the same
    direction the single-file merge used."""
    G.generated_path(gpath).write_text(yaml.dump({"tables": {"orders": _generated("machine")}}))
    gpath.write_text(yaml.dump({"tables": {"orders": _authored("human")}}))
    assert G.load_glossary(gpath)["tables"]["orders"]["description"] == "human"


# ── the repo's own file ───────────────────────────────────────────────────────

def test_the_committed_glossary_carries_only_authored_terms():
    """The ratchet. If a generated entry ever lands back in the tracked file, the next
    `git status` is 5,000 lines of machine output again and this whole split is undone."""
    import pathlib

    p = pathlib.Path("data/glossary.yaml")
    if not p.exists():
        pytest.skip("no repo glossary in this checkout")
    tables = (yaml.safe_load(p.read_text()) or {}).get("tables") or {}
    leaked = [t for t, e in tables.items() if isinstance(e, dict) and e.get("auto_generated")]
    assert not leaked, (
        f"{len(leaked)} auto-generated entr(ies) leaked into the TRACKED glossary: {leaked[:5]} — "
        "run `save_glossary(load_glossary())` to re-split")
