"""IP-1 — the package resolver's own laws, on packages built in a temp root.

Parity with the pre-move KB is `test_ip1_package_parity.py`; these lock what the resolver
decides when packages disagree: authored wins an id, a deprecated package is not read, a file
carried twice or an industry carried twice is a named problem and never a silent overwrite, an
industry is read only with its curated file, a package's `kb_files` must match what it carries,
the index is keyed by the pack roots, and the validator and roster tell a package from a pack.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aughor.packs import knowledge


def _package(root: Path, pid: str, *, layer: str, industry: str = "", status: str = "active",
             kb: dict | None = None, curated: dict | None = None, raw_kb: dict | None = None) -> Path:
    d = root / pid
    (d / "kb").mkdir(parents=True, exist_ok=True)
    lines = [f"id: {pid}", f"name: {pid.title()}", f"layer: {layer}", f"status: {status}"]
    if industry:
        lines.append(f"industry: {industry}")
    (d / "pack.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name, entries in (kb or {}).items():
        (d / "kb" / f"{name}.json").write_text(json.dumps(entries), encoding="utf-8")
    for name, text in (raw_kb or {}).items():
        (d / "kb" / f"{name}.json").write_text(text, encoding="utf-8")
    if curated is not None:
        (d / "industry.json").write_text(json.dumps(curated), encoding="utf-8")
    return d


def _curated(name: str, kb_files: list[str]) -> dict:
    return {"industry": name, "aliases": [name.lower()], "generic_aliases": [],
            "kb_files": kb_files, "description": "", "metrics": []}


@pytest.fixture()
def roots(tmp_path, monkeypatch):
    authored, imported = tmp_path / "authored", tmp_path / "imported"
    authored.mkdir()
    imported.mkdir()
    monkeypatch.setenv("AUGHOR_PACKS_DIR", str(authored))
    monkeypatch.setenv("AUGHOR_IMPORTED_PACKS_DIR", str(imported))
    knowledge.reset()
    yield authored, imported
    knowledge.reset()


def test_an_industry_package_owns_its_entries_and_a_function_shares_them(roots):
    authored, _ = roots
    _package(authored, "rail", layer="industry", industry="rail",
             kb={"rail_ops": [{"id": "rail_otp"}]}, curated=_curated("Rail", ["rail_ops"]))
    _package(authored, "finance", layer="function", kb={"fin_x": [{"id": "fin_margin"}]})
    assert knowledge.problems() == ()
    assert [kb["id"] for kb in knowledge.industry_kbs()] == ["rail"]
    assert knowledge.entry_industry("rail_otp") == "rail"
    assert knowledge.entry_industry("fin_margin") == ""
    assert [f.name for f in knowledge.kb_files()] == ["fin_x.json", "rail_ops.json"]


def test_authored_wins_an_id_collision(roots):
    authored, imported = roots
    _package(authored, "rail", layer="industry", industry="rail",
             kb={"rail_ops": [{"id": "rail_otp"}]}, curated=_curated("Rail", ["rail_ops"]))
    _package(imported, "rail", layer="industry", industry="rail",
             kb={"rail_imported": [{"id": "rail_shadow"}]}, curated=_curated("Rail", ["rail_imported"]))
    assert [f.name for f in knowledge.kb_files()] == ["rail_ops.json"]
    assert knowledge.entry_industry("rail_shadow") == ""


def test_a_deprecated_package_is_not_read(roots):
    authored, _ = roots
    _package(authored, "rail", layer="industry", industry="rail", status="deprecated",
             kb={"rail_ops": [{"id": "rail_otp"}]}, curated=_curated("Rail", ["rail_ops"]))
    assert knowledge.kb_files() == ()
    assert knowledge.industry_kbs() == ()


def test_a_draft_package_is_not_read_until_a_person_makes_it_active(roots):
    """§3.17 gate 6: a draft is still being authored — its industry is not matched and its entries reach no
    agent until its pack.yaml says active."""
    authored, _ = roots
    package = _package(authored, "rail", layer="industry", industry="rail", status="draft",
                       kb={"rail_ops": [{"id": "rail_otp"}]}, curated=_curated("Rail", ["rail_ops"]))
    assert knowledge.kb_files() == ()
    assert knowledge.industry_kbs() == ()
    assert knowledge.entry_industry("rail_otp") == ""
    manifest = package / "pack.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("status: draft", "status: active"),
                        encoding="utf-8")
    knowledge.reset()
    assert [kb["id"] for kb in knowledge.industry_kbs()] == ["rail"]
    assert knowledge.entry_industry("rail_otp") == "rail"


def test_a_file_carried_twice_is_a_problem_and_never_an_overwrite(roots):
    authored, _ = roots
    _package(authored, "alpha", layer="base", kb={"shared": [{"id": "a"}]})
    _package(authored, "beta", layer="base", kb={"shared": [{"id": "b"}]})
    assert [f.pack_id for f in knowledge.kb_files()] == ["alpha"]
    assert any("kb/shared.json is also carried by package alpha" in p for p in knowledge.problems())


def test_an_industry_carried_twice_is_read_once(roots):
    authored, _ = roots
    _package(authored, "rail", layer="industry", industry="rail",
             kb={"rail_ops": [{"id": "rail_otp"}]}, curated=_curated("Rail", ["rail_ops"]))
    _package(authored, "rail-two", layer="industry", industry="rail",
             kb={"rail_more": [{"id": "rail_more_otp"}]}, curated=_curated("Rail", ["rail_more"]))
    assert [kb["id"] for kb in knowledge.industry_kbs()] == ["rail"]
    assert knowledge.entry_industry("rail_more_otp") == ""
    assert any("already carried by package rail" in p for p in knowledge.problems())


def test_an_industry_is_read_only_with_its_curated_file(roots):
    authored, _ = roots
    _package(authored, "rail", layer="industry", industry="rail", kb={"rail_ops": [{"id": "rail_otp"}]})
    assert knowledge.industry_kbs() == ()
    assert knowledge.entry_industry("rail_otp") == ""
    assert any("needs industry.json" in p for p in knowledge.problems())


def test_curated_kb_files_must_match_what_the_package_carries(roots):
    authored, _ = roots
    _package(authored, "rail", layer="industry", industry="rail",
             kb={"rail_ops": [{"id": "rail_otp"}]}, curated=_curated("Rail", ["rail_ops", "rail_gone"]))
    assert any("lists kb_files ['rail_gone', 'rail_ops'] but the package carries ['rail_ops']" in p
               for p in knowledge.problems())


def test_an_unparseable_file_is_named_not_skipped_silently(roots):
    authored, _ = roots
    _package(authored, "base", layer="base", raw_kb={"broken": "{not json", "fine": "[]"})
    assert [f.name for f in knowledge.kb_files()] == ["fine.json"]
    assert any("kb/broken.json could not be parsed" in p for p in knowledge.problems())


def test_files_are_read_as_utf8(roots):
    authored, _ = roots
    _package(authored, "base", layer="base",
             raw_kb={"prose": json.dumps([{"id": "p", "title": "Café — Größe"}], ensure_ascii=False)})
    [(_file, data)] = list(knowledge.iter_kb_payloads())
    assert data[0]["title"] == "Café — Größe"


def test_the_index_is_keyed_by_the_roots_and_reset_rereads_in_place(roots, tmp_path, monkeypatch):
    authored, _ = roots
    _package(authored, "base", layer="base", kb={"one": [{"id": "x"}]})
    assert [f.name for f in knowledge.kb_files()] == ["one.json"]

    other = tmp_path / "other"
    _package(other, "base", layer="base", kb={"two": [{"id": "y"}]})
    monkeypatch.setenv("AUGHOR_PACKS_DIR", str(other))
    assert [f.name for f in knowledge.kb_files()] == ["two.json"]      # a moved root is never stale

    (other / "base" / "kb" / "three.json").write_text("[]", encoding="utf-8")
    assert [f.name for f in knowledge.kb_files()] == ["two.json"]      # cached per roots…
    knowledge.reset()
    assert [f.name for f in knowledge.kb_files()] == ["three.json", "two.json"]   # …until reset


def test_the_validator_checks_a_package_by_its_own_rules(roots):
    from aughor.packs.validate import validate_pack

    authored, _ = roots
    ok = _package(authored, "rail", layer="industry", industry="rail",
                  kb={"rail_ops": [{"id": "rail_otp"}]}, curated=_curated("Rail", ["rail_ops"]))
    report = validate_pack(ok)
    assert report.ok, report.errors
    assert not any("no evals" in w or "no metrics" in w for w in report.warnings)

    missing = _package(authored, "sea", layer="industry", industry="sea", kb={"sea_ops": []})
    assert "an industry package needs industry.json (an object)" in validate_pack(missing).errors

    wrong = _package(authored, "fin", layer="function", industry="finance", kb={"fin": []})
    assert any("only meaningful on layer industry" in e for e in validate_pack(wrong).errors)

    bogus = _package(authored, "odd", layer="vertical", kb={"odd": []})
    assert any("not in ('industry', 'function', 'base')" in e for e in validate_pack(bogus).errors)


def test_the_shipped_packages_validate_clean():
    """The eleven packages IP-1 moved the KB into, read from the session's authored copy."""
    from aughor.packs.roots import authored_root
    from aughor.packs.validate import validate_pack

    knowledge.reset()
    ids = {"airline", "food-delivery", "logistics", "manufacturing", "retail", "saas",
           "finance", "marketing", "product", "customer", "analytics-base"}
    assert {p.pack_id for p in knowledge.packages()} == ids
    for pid in sorted(ids):
        report = validate_pack(authored_root() / pid)
        assert report.ok, (pid, report.errors)
    assert knowledge.problems() == ()


def test_a_package_is_not_an_agent_template_and_the_roster_names_its_layer():
    from fastapi.testclient import TestClient

    from aughor.api import app
    from aughor.custom_agents.templates import get_template, list_templates

    template_ids = {t.get("id") or t.get("pack_id") for t in list_templates()}
    assert "retail" not in template_ids and "analytics-base" not in template_ids
    assert get_template("retail") is None

    roster = {p["id"]: p for p in TestClient(app).get("/packs").json()["packs"]}
    assert roster["retail"]["layer"] == "industry" and roster["retail"]["industry"] == "retail"
    assert roster["finance"]["layer"] == "function" and roster["finance"]["industry"] == ""
    assert roster["core-ecommerce"]["layer"] == ""
