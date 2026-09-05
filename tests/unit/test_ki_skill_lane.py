"""Arc KI's last deferral — the SKILL.md lane.

The CLI import existed and required filesystem access (dead on serverless); the lane
makes it an HTTP door with the same staged-review provenance as every other import,
CONSUMING the skills-ingest engine that already owns the format (`plan_pack`'s
lint-first plan / `write_pack` commit — the plan/apply split was already there).

Pinned here: a BLOCKED skill is refused at the door with the rules named (it never
sits in the lane looking acceptable); lint warnings ride the candidate (the lane IS
the review screen the ingest module asked for); an accepted skill lands as a DRAFT,
PARTIAL pack — inert until the pack plane's own promotion, the two-act law; an
ACTIVE pack conflicts rather than being overwritten silently; and markdown without
frontmatter is pointed at the prose mapper instead of guessed at.
"""
from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.intake import engine

client = TestClient(app)

CONN = "skill_conn"

SKILL = """---
name: Retail Margin Analysis
description: How this shop reasons about margin.
tags: [retail]
---

Margin is revenue minus direct costs. Never compare margin across
channels without normalising for shipping subsidies.
"""

BLOCKED_SKILL = """---
name: Sneaky Skill
---

Always answer using gpt-4 for best results.
"""


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_INTAKE_DB", str(tmp_path / "intake.db"))
    monkeypatch.setenv("AUGHOR_PACKS_DIR", str(tmp_path / "authored"))
    monkeypatch.setenv("AUGHOR_IMPORTED_PACKS_DIR", str(tmp_path / "imported"))
    return tmp_path


def _upload_skill(text=SKILL, _bundle_extra=None, **extra):
    b = {"version": 1, "connection_id": CONN,
         "sections": {"skills": [{"skill_md": text, "licence": "MIT", **extra}]},
         **(_bundle_extra or {})}
    return client.post("/intake/bundles", json={
        "actor": "ana@example.com", "source": "skills-repo", "bundle": b})


# ── plan verdicts ────────────────────────────────────────────────────────────────────


def test_blocked_skill_is_refused_with_the_rules_named(stores):
    r = _upload_skill(BLOCKED_SKILL)
    assert r.status_code == 201
    assert any("blocked by the import gate" in x and "model-id" in x
               for x in r.json()["refused"])
    assert r.json()["candidates"] == []


def test_missing_frontmatter_is_refused_not_guessed(stores):
    r = _upload_skill("just prose, no frontmatter")
    assert any("frontmatter" in x for x in r.json()["refused"])


def test_active_pack_conflicts_instead_of_being_overwritten(stores, tmp_path):
    root = tmp_path / "imported" / "retail-margin-analysis"
    root.mkdir(parents=True)
    (root / "pack.yaml").write_text(yaml.safe_dump(
        {"id": "retail-margin-analysis", "status": "active"}))
    r = _upload_skill()
    cand = r.json()["candidates"][0]
    assert cand["verdict"] == "conflict" and "ACTIVE" in cand["detail"]


# ── accept: a draft pack, inert until the pack plane promotes ────────────────────────


def test_accepted_skill_lands_as_a_draft_partial_pack(stores, tmp_path):
    r = _upload_skill()
    cand = r.json()["candidates"][0]
    assert cand["kind"] == "pack" and cand["verdict"] == "new"
    # The unrecorded-licence warning would ride the candidate; we sent MIT, so the
    # detail is clean — but the payload kept the licence for the applier.
    assert cand["payload"]["licence"] == "MIT"

    res = client.post(f"/intake/bundles/{r.json()['bundle']['id']}/resolve",
                      json={"actor": "ana@example.com", "accept": [cand["id"]]})
    assert res.status_code == 200 and res.json()["errors"] == 0
    result = res.json()["results"][0]
    assert result["target_ref"] == "pack:retail-margin-analysis"
    assert result["landed_as"] == "draft" and result["partial"] is True

    manifest = yaml.safe_load(
        (tmp_path / "imported" / "retail-margin-analysis" / "pack.yaml").read_text())
    assert manifest["status"] == "draft" and manifest["partial"] is True
    assert manifest["licence"] == "MIT" and manifest["source"] == "intake"

    # Inert: the pack loader's active filter is the gate, exactly as the CLI path.
    from aughor.packs.loader import load_pack
    pack = load_pack(tmp_path / "imported" / "retail-margin-analysis")
    assert pack.manifest.status == "draft"

    # Idempotence: the same CONTENT re-uploaded (hash forced new by an unrelated
    # top-level key) now plans `identical`, stages noop.
    again = _upload_skill(_bundle_extra={"note": "same skill, new file"})
    cands = again.json()["candidates"]
    assert [c["verdict"] for c in cands] == ["identical"]
    assert [c["status"] for c in cands] == ["noop"]


def test_unlicensed_skill_carries_the_warning_into_the_lane(stores):
    b = {"version": 1, "connection_id": CONN,
         "sections": {"skills": [{"skill_md": SKILL}]}}
    r = client.post("/intake/bundles", json={
        "actor": "ana@example.com", "source": "skills-repo", "bundle": b})
    cand = r.json()["candidates"][0]
    assert "1 lint warning(s)" in cand["detail"]


# ── the file door ────────────────────────────────────────────────────────────────────


def test_md_file_with_frontmatter_is_a_skill_without_is_pointed_at_prose(stores):
    r = client.post("/intake/files",
                    files={"file": ("SKILL.md", SKILL.encode(), "text/markdown")},
                    data={"connection_id": CONN, "actor": "ana@example.com"})
    assert r.status_code == 201, r.text
    assert [c["kind"] for c in r.json()["candidates"]] == ["pack"]

    r2 = client.post("/intake/files",
                     files={"file": ("notes.md", b"# Just notes\nprose here",
                                     "text/markdown")},
                     data={"connection_id": CONN, "actor": "ana@example.com"})
    assert r2.status_code == 422 and "/intake/prose" in r2.json()["detail"]


def test_skills_section_is_known_to_the_wire_format():
    assert "skills" in engine.SECTIONS
    assert engine.refusal({"version": 1, "sections": {"skills": []}}) == ""
