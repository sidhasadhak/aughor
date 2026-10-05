"""The 2027 study's close-out, C9 — the platform writes into a pack's manifest without erasing what its
author wrote (`aughor/packs/manifest.py`).

What these hold: a rewrite changes exactly the keys asked for — in place, a block value removed with the line,
a trailing comment kept, an absent key appended — and every other byte, comments first, stays; `yaml.safe_load`
of the result is the loaded original with those keys changed; the promotion door and the kit's upload go through
it, so a manifest's provenance survives both.
"""
from __future__ import annotations

import uuid

import yaml

from aughor.packs.manifest import rewrite_scalars, scalar

MANIFEST = """id: banking
name: Banking and lending
version: 1
description: >
  The banking and lending industry package: the net interest margin with the yield and funding cost behind it,
  returns, efficiency and credit quality.
layer: industry
# IP-4 (2026-09-17): drafted by the generator — a draft is read by no agent; a person's review makes it active.
anatomy: 1
domains:
  - banking
  - lending
status: draft   # gate 6
source: aughor
"""


def test_a_rewrite_changes_the_keys_asked_for_and_nothing_else():
    out = rewrite_scalars(MANIFEST, {"status": "active", "uploaded_by": "user:ana", "uploaded_at": "2026-10-05T10:00:00Z"})
    assert "# IP-4 (2026-09-17): drafted by the generator" in out
    assert "status: active   # gate 6\n" in out                    # in place, the trailing comment kept
    assert out.endswith("source: aughor\nuploaded_by: user:ana\nuploaded_at: '2026-10-05T10:00:00Z'\n")
    before, after = yaml.safe_load(MANIFEST), yaml.safe_load(out)
    before.update({"status": "active", "uploaded_by": "user:ana", "uploaded_at": "2026-10-05T10:00:00Z"})
    assert after == before
    # every line the author wrote that was not asked for is byte-identical, in order
    kept = [line for line in MANIFEST.splitlines() if not line.startswith("status:")]
    assert [line for line in out.splitlines() if not line.startswith(("status:", "uploaded_"))] == kept


def test_a_block_value_is_replaced_whole_and_a_scalar_that_reads_as_another_type_is_quoted():
    out = rewrite_scalars(MANIFEST, {"description": "One line now.", "version": 2})
    assert "description: One line now.\nlayer: industry\n" in out
    assert "returns, efficiency" not in out
    assert yaml.safe_load(out)["description"] == "One line now." and yaml.safe_load(out)["version"] == 2
    assert scalar("2026-10-05T10:00:00Z") == "'2026-10-05T10:00:00Z'" and scalar("draft") == "draft"
    assert scalar("yes") == "'yes'" and scalar(True) == "true"
    # a `#` inside quotes is not a comment, so nothing is kept as one
    assert rewrite_scalars("status: 'a # b'\n", {"status": "draft"}) == "status: draft\n"


def test_the_promotion_door_keeps_the_authors_comments(tmp_path):
    from aughor.packs.loader import PROSE_FILE
    from aughor.packs.promote import set_status
    d = tmp_path / "commented"
    d.mkdir()
    text = ("id: commented\nname: Commented\nversion: 1\n# why this pack exists, in the author's words\n"
            "partial: true\nsource: awesome-agent-skills\nstatus: draft # promoted by a person\ndomains: [retention]\n")
    (d / "pack.yaml").write_text(text)
    (d / PROSE_FILE).write_text("# Commented\n\nCohorts before totals.\n")
    assert set_status("commented", "active", packs_dir=tmp_path, actor="user:ana").manifest.status == "active"
    after = (d / "pack.yaml").read_text()
    assert "# why this pack exists, in the author's words" in after and "status: active # promoted by a person" in after
    assert after.replace("status: active", "status: draft") == text


def test_the_kits_upload_keeps_the_uploaders_comments(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_IMPORTED_PACKS_DIR", str(tmp_path / "imported"))
    from aughor.packs import kit as KIT
    from aughor.packs.roots import imported_root
    pid = "kept-" + uuid.uuid4().hex[:6]
    manifest = (f"id: {pid}\nname: Kept\nversion: 1\n# the uploader's reason for this watch\nstatus: active\ndomains: [testing]\n")
    KIT.upload({"pack.yaml": manifest, "monitors/return_rate.yaml": "id: return_rate\nmetric: return_rate\nunmeasured: true\n"},
               by="user:ana", source_url="https://example.com/kept")
    after = (imported_root() / pid / "pack.yaml").read_text()
    assert "# the uploader's reason for this watch" in after and "status: draft\n" in after and "status: active" not in after
    raw = yaml.safe_load(after)
    assert raw["uploaded_by"] == "user:ana" and raw["source_url"] == "https://example.com/kept" and raw["source"] == "upload"
    assert after.startswith(f"id: {pid}\nname: Kept\nversion: 1\n# the uploader's reason for this watch\nstatus: draft\ndomains: [testing]\n")
