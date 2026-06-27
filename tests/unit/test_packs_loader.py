"""Specialist pack spec + loader + validator (Phase A · P0, 2026-06-27).

A pack is a declarative folder; the loader is pure I/O and the validator catches every
error findable without a connection (the deploy-time binding/dry-run is P1). The shipped
packs/customer-analytics sample is validated here so the format stays loadable. See
aughor/packs/.
"""
from pathlib import Path

import pytest

from aughor.packs import load_pack, list_packs, validate_pack, PacksError

REPO = Path(__file__).resolve().parents[2]


def _write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _minimal_pack(root: Path):
    _write(root, "pack.yaml", "id: demo\nname: Demo\nstatus: draft\ndefault_temporal_grain: cohort\n")
    _write(root, "expertise.md", "# Demo\nReason in cohorts.\n")
    _write(root, "entities.yaml", "roles:\n  customer:\n    description: the customer\n")
    _write(root, "metrics/m.yaml",
           "name: Retention\nformula: 'COUNT(DISTINCT a)/NULLIF(COUNT(DISTINCT b),0)'\nbinds:\n  required: [customer]\n")
    _write(root, "questions.yaml", "canonical: ['How is retention?']\nintent_tags: [retention]\n")
    _write(root, "evals/e.yaml", "- question: 'retention?'\n  expect: {grain: cohort}\n")


def test_load_minimal_pack(tmp_path):
    _minimal_pack(tmp_path / "demo")
    pack = load_pack(tmp_path / "demo")
    assert pack.id == "demo"
    assert pack.manifest.default_temporal_grain == "cohort"
    assert "cohorts" in pack.expertise
    assert [m.name for m in pack.metrics] == ["Retention"]
    assert "customer" in pack.entities
    assert pack.questions.intent_tags == ["retention"]
    assert len(pack.evals) == 1


def test_missing_manifest_raises(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(PacksError):
        load_pack(tmp_path / "empty")


def test_manifest_without_id_raises(tmp_path):
    _write(tmp_path / "bad", "pack.yaml", "name: No Id\n")
    with pytest.raises(PacksError):
        load_pack(tmp_path / "bad")


def test_validate_minimal_pack_is_clean(tmp_path):
    _minimal_pack(tmp_path / "demo")
    r = validate_pack(tmp_path / "demo")
    assert r.ok, r.errors
    assert r.pack_id == "demo"


def test_metric_binding_unknown_role_is_error(tmp_path):
    root = tmp_path / "demo"
    _minimal_pack(root)
    # rebind the metric to a role that isn't declared
    _write(root, "metrics/m.yaml",
           "name: Retention\nformula: x\nbinds:\n  required: [ghost_role]\n")
    r = validate_pack(root)
    assert not r.ok
    assert any("ghost_role" in e for e in r.errors)


def test_bad_status_and_grain_are_errors(tmp_path):
    _write(tmp_path / "demo", "pack.yaml",
           "id: demo\nname: Demo\nstatus: live\ndefault_temporal_grain: weekly\n")
    r = validate_pack(tmp_path / "demo")
    assert not r.ok
    assert any("status" in e for e in r.errors)
    assert any("default_temporal_grain" in e for e in r.errors)


def test_empty_pack_warns_but_no_crash(tmp_path):
    _write(tmp_path / "demo", "pack.yaml", "id: demo\nname: Demo\n")
    r = validate_pack(tmp_path / "demo")
    assert r.ok  # no hard errors
    assert any("no metrics" in w for w in r.warnings)
    assert any("no evals" in w for w in r.warnings)


def test_list_packs(tmp_path):
    _minimal_pack(tmp_path / "a")
    _write(tmp_path / "b", "pack.yaml", "id: bee\nname: B\n")
    (tmp_path / "not_a_pack").mkdir()
    assert sorted(list_packs(tmp_path)) == ["bee", "demo"]


def test_shipped_customer_analytics_pack_validates():
    # Leverage on the real path: the dogfooded sample must load + validate clean.
    pack_dir = REPO / "packs" / "customer-analytics"
    pack = load_pack(pack_dir)
    assert pack.id == "customer-analytics"
    r = validate_pack(pack_dir)
    assert r.ok, r.errors


def test_specialist_packs_flag_registered():
    from aughor.kernel.flags import FLAG_ENV, FLAG_META
    assert "specialist_packs" in FLAG_ENV
    assert "specialist_packs" in FLAG_META
