"""IP-4 — gate 6 enforced: the agents read a knowledge package only once a person has made it active.

Every knowledge package used to say `status: draft` and be read anyway, so a package the generator drafted would
have reached every agent on the next restart with nobody having reviewed it (ROADMAP §3.17, "How a package is
made", gate 6). The packages that were already read are active now and read exactly as before — the IP-1 parity
tests are that receipt. Active still never makes a knowledge package steer: it is reference, not a pack a question
is routed to, disclosed as or read through.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from aughor.packs import knowledge
from aughor.packs.gate4 import package_fingerprint
from aughor.packs.loader import load_pack
from aughor.packs.models import KNOWLEDGE_LAYERS

REPO_PACKS = Path(__file__).resolve().parents[2] / "packs"


def _knowledge_manifests() -> list[dict]:
    manifests = [yaml.safe_load(p.read_text(encoding="utf-8")) or {} for p in sorted(REPO_PACKS.glob("*/pack.yaml"))]
    return [m for m in manifests if m.get("layer") in KNOWLEDGE_LAYERS]


def test_the_agents_read_exactly_the_active_knowledge_packages():
    """The population is the repository's packs/, read here rather than listed."""
    manifests = _knowledge_manifests()
    assert manifests
    knowledge.reset()
    assert sorted(p.pack_id for p in knowledge.packages()) == sorted(
        m["id"] for m in manifests if m.get("status") == "active")


def test_an_active_knowledge_package_never_steers():
    from aughor.packs.intake import active_packs
    from aughor.packs.routing import select_pack

    knowledge_ids = {m["id"] for m in _knowledge_manifests()}
    assert not knowledge_ids & {p.id for p in active_packs()}
    retail = load_pack(REPO_PACKS / "retail")
    assert retail.manifest.status == "active" and not retail.manifest.steers
    assert select_pack(" ".join(retail.manifest.domains), [retail], min_score=0.0) is None


def test_the_chat_tool_does_not_read_a_knowledge_package_as_a_pack():
    from aughor.agent.platform_tools import read_pack

    answer = read_pack("any-connection", {"pack_id": "retail"})
    assert answer["readable"] is False
    assert "knowledge package" in answer["why"]


def test_a_review_does_not_stale_a_measurement(tmp_path):
    """Moving a package from draft to active changes nothing gate 4 measured, so its receipt stays current; any
    other change to pack.yaml still stales it."""
    package = tmp_path / "airline"
    shutil.copytree(REPO_PACKS / "airline", package)
    manifest = package / "pack.yaml"
    text = manifest.read_text(encoding="utf-8")
    measured = package_fingerprint(package)
    manifest.write_text(text.replace("status: active", "status: draft"), encoding="utf-8")
    assert package_fingerprint(package) == measured
    manifest.write_text(text.replace("version: 1", "version: 2"), encoding="utf-8")
    assert package_fingerprint(package) != measured
