"""The ontology overrides tree as a shipped seed with this install's declarations over it.

The tree the app writes (`data/ontology_overrides/`) is the INSTANCE; overrides the repo ships
live in `data/shipped/ontology_overrides/`, which is never written. A file at the same relative
path shadows the seed's whole, and a withdrawn shipped one leaves a `<file>.hidden` marker.
Both roots are repointed at tmp in every test.
"""
from __future__ import annotations

import pytest
import yaml

from aughor.ontology import overrides as ov
from aughor.ontology.overrides import OntologyOverride
from aughor.ontology.prompt_reach import action_census


@pytest.fixture
def roots(tmp_path, monkeypatch):
    inst, seed = tmp_path / "instance", tmp_path / "seed"
    monkeypatch.setattr(ov, "_ROOT", inst)
    monkeypatch.setattr(ov, "_SEED_ROOT", seed)
    return inst, seed


def ship(seed, conn, schema, kind, target_id, **fields):
    p = seed / conn / schema / kind / f"{target_id}.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(OntologyOverride(target_kind=kind, target_id=target_id,
                                                 fields=fields).model_dump()))
    return p


def ids(conn="c1", schema="main"):
    return [(o.target_kind, o.target_id, o.fields.get("label")) for o in ov.load_overrides(conn, schema)]


def test_O1_a_reader_sees_this_installs_files_over_the_shipped_ones(roots):
    """Kills: a reader of one root only, a merge by FIELD (a shadowed file's other fields leaking
    through), and a fallback to the seed's copy when the instance's will not parse."""
    inst, seed = roots
    ship(seed, "c1", "main", "entity", "orders", label="Shipped orders", owner="shipped-owner")
    ship(seed, "c1", "main", "action", "refund")
    ship(seed, "c1", "seedonly", "entity", "x")
    ov.save_override("c1", "main", OntologyOverride(target_kind="entity", target_id="orders",
                                                    fields={"label": "Our orders"}))
    ov.save_override("c1", "main", OntologyOverride(target_kind="action", target_id="ship_it"))
    assert ids() == [("action", "refund", None), ("action", "ship_it", None),
                     ("entity", "orders", "Our orders")]
    assert "owner" not in ov.find_override("c1", "main", "entity", "orders").fields
    assert ov.override_scopes("c1") == ["main", "seedonly"]
    assert action_census() == {"c1/main": ["refund", "ship_it"]}

    (inst / "c1" / "main" / "entity" / "orders.yaml").write_text(": not yaml :\n  - [")
    assert ("entity", "orders", "Shipped orders") not in ids()


def test_O2_withdrawing_a_shipped_declaration_hides_it_and_redeclaring_brings_it_back(roots):
    """Kills: an unlink that only unlinks (the shipped file answers again), one that deletes the
    SEED, and a `removed` flag that stops meaning "something was visible"."""
    inst, seed = roots
    shipped = ship(seed, "c1", "main", "action", "refund")
    assert ov.delete_override("c1", "main", "action", "refund") is True
    assert shipped.exists(), "the shipped file was deleted"
    assert ids() == []
    assert action_census() == {}
    assert ov.delete_override("c1", "main", "action", "refund") is False     # nothing visible now
    ov.save_override("c1", "main", OntologyOverride(target_kind="action", target_id="refund",
                                                    fields={"label": "ours"}))
    assert ids() == [("action", "refund", "ours")]
    assert not list(inst.rglob("*.hidden"))
    assert ov.delete_override("c1", "main", "action", "refund") is True
    assert ids() == []


def test_a_write_that_dies_halfway_leaves_the_previous_declaration_whole(roots, monkeypatch):
    """Atomicity, tested as a crash rather than as a file listing. Kills: writing in place — the
    half-written file would not parse, and the declaration would vanish."""
    import pathlib

    inst, _ = roots
    ov.save_override("c1", "main", OntologyOverride(target_kind="entity", target_id="o",
                                                    fields={"label": "before"}))
    real = pathlib.Path.write_text

    def dies_halfway(self, data, *a, **k):
        real(self, data[: len(data) // 2], *a, **k)
        raise OSError("disk full")

    with monkeypatch.context() as mp:              # scoped: undo() would also undo the fixture's roots
        mp.setattr(pathlib.Path, "write_text", dies_halfway)
        # and it SAYS so (PENDING item 21): a write that did not land used to be swallowed, so every door reported
        # a save that never happened
        with pytest.raises(ov.OverrideWriteFailed, match="entity 'o' was not saved"):
            ov.save_override("c1", "main", OntologyOverride(target_kind="entity", target_id="o",
                                                            fields={"label": "after"}))
    assert ids() == [("entity", "o", "before")]
    assert [p.name for p in inst.rglob("*") if p.is_file()] == ["o.yaml"], "a temp file leaked"


def test_a_replace_windows_refuses_falls_back_to_writing_in_place(roots, monkeypatch):
    """Windows cannot replace a file another request holds open. Kills: letting that
    PermissionError be swallowed — the route would report a save that never happened."""
    import pathlib

    ov.save_override("c1", "main", OntologyOverride(target_kind="entity", target_id="o",
                                                    fields={"label": "before"}))

    def refused(self, target):
        raise PermissionError(13, "The process cannot access the file")

    with monkeypatch.context() as mp:
        mp.setattr(pathlib.Path, "replace", refused)
        ov.save_override("c1", "main", OntologyOverride(target_kind="entity", target_id="o",
                                                        fields={"label": "after"}))
    assert ids() == [("entity", "o", "after")]


def test_O3_an_instance_tree_inside_the_seed_is_refused_loudly(roots, monkeypatch):
    """The writers swallow every exception, so the guard must fire BEFORE their try blocks.
    Kills: moving the guard inside `_write`'s try — the write would silently not happen."""
    _, seed = roots
    monkeypatch.setattr(ov, "_ROOT", seed / "nested")
    with pytest.raises(RuntimeError, match="shipped seed"):
        ov.save_override("c1", "main", OntologyOverride(target_kind="entity", target_id="o"))
    with pytest.raises(RuntimeError, match="shipped seed"):
        ov.delete_override("c1", "main", "entity", "o")
    assert not seed.exists()


def test_an_absent_seed_is_an_empty_layer(roots):
    """What every install has today: nothing ships under data/shipped/ontology_overrides."""
    ov.save_override("c1", "main", OntologyOverride(target_kind="entity", target_id="o"))
    assert ids() == [("entity", "o", None)]
    assert ov.override_scopes("c1") == ["main"]
