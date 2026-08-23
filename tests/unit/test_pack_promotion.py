"""VA-1 — the two rungs a pack needs before an imported skill is worth anything.

The skills plane could import (`aughor/skills/`) and could steer (`packs/intake.py`), and
between them sat two gaps that made the whole thing inert:

* **`status` was read in four places and written in none.** Import lands a pack at `draft`
  and the ingester's contract is that nothing imported reaches a prompt until someone
  promotes it — with no promotion path, that contract read as "never".
* **the prose was unreachable.** `list_packs` reported id/name/status/domains; nothing
  could read a pack's actual prose, which is the entire content of an imported skill.

The promotion gate FORKS by what a pack is, and that fork is the design decision worth
protecting: `evalgate.evaluate_activation` wants a pinned+verified binding, declared evals
and a clean pass — none of which a prose-only pack can ever have. Gating it that way would
mean "importable but never usable"; skipping the gate for grounded packs would mean a way
around Bet 2. So: prose is gated by the lint, grounded packs by their evals.
"""
from __future__ import annotations

import types

import pytest
import yaml

from aughor.packs.loader import PROSE_FILE, load_pack
from aughor.packs.promote import PromotionRefused, set_status


def _write_pack(root, pack_id, *, partial=True, prose="Cohorts before totals.",
                status="draft", extra_manifest=None, entities=None):
    d = root / pack_id
    d.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": pack_id, "name": pack_id.replace("-", " ").title(), "version": 1,
        "status": status, "partial": partial,
        "source": "awesome-agent-skills", "source_url": "https://example.invalid/s",
        "licence": "MIT", "domains": ["retention"],
    }
    manifest.update(extra_manifest or {})
    (d / "pack.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    (d / PROSE_FILE).write_text(f"# {pack_id}\n\n{prose}\n")
    if entities:
        (d / "entities.yaml").write_text(yaml.safe_dump(entities, sort_keys=False))
    return d


# ── the prose gate ────────────────────────────────────────────────────────────────

def test_a_prose_pack_activates_on_a_clean_lint(tmp_path):
    _write_pack(tmp_path, "cohorts")

    pack = set_status("cohorts", "active", packs_dir=tmp_path, actor="amit")

    assert pack.manifest.status == "active"


def test_activation_runs_the_import_gate_over_the_prose(tmp_path):
    """The lint belongs HERE, not only at import: this is the door prose passes through to
    reach a prompt, and a hand-placed pack never met the importer at all."""
    _write_pack(tmp_path, "pinned-model",
                prose="Always call claude-3-5-sonnet-20241022 for the summary.")

    with pytest.raises(PromotionRefused) as exc:
        set_status("pinned-model", "active", packs_dir=tmp_path)

    assert "model-id" in str(exc.value)
    assert load_pack(tmp_path / "pinned-model").manifest.status == "draft"


def test_demotion_is_never_gated(tmp_path):
    """Taking something out of service must not require passing a test."""
    _write_pack(tmp_path, "bad-prose", status="active",
                prose="Use claude-3-5-sonnet-20241022.")

    pack = set_status("bad-prose", "draft", packs_dir=tmp_path)

    assert pack.manifest.status == "draft"


def test_promotion_rewrites_only_status_and_keeps_provenance(tmp_path):
    """A round trip through the model would drop any key the model does not declare, and
    provenance is exactly the kind of key that gets added after a pack was written."""
    d = _write_pack(tmp_path, "keeps-origin", extra_manifest={"owner_team": "Growth"})
    raw_before = yaml.safe_load((d / "pack.yaml").read_text())

    set_status("keeps-origin", "active", packs_dir=tmp_path)

    raw_after = yaml.safe_load((d / "pack.yaml").read_text())
    assert raw_after.pop("status") == "active"
    assert raw_before.pop("status") == "draft"
    assert raw_after == raw_before


def test_an_unknown_status_is_refused(tmp_path):
    _write_pack(tmp_path, "cohorts")
    with pytest.raises(ValueError):
        set_status("cohorts", "enabled", packs_dir=tmp_path)


# ── the evals gate, for packs that actually steer ─────────────────────────────────

def test_a_grounded_pack_cannot_be_activated_without_its_evals(tmp_path):
    """Not a lint question. A pack that steers a plan is promoted by Bet 2's verdict, and
    this path must not become the way around it."""
    _write_pack(tmp_path, "finance", partial=False)

    with pytest.raises(PromotionRefused) as exc:
        set_status("finance", "active", packs_dir=tmp_path)

    assert "evaluate" in str(exc.value)


def test_a_grounded_pack_is_refused_with_its_own_reasons(tmp_path):
    _write_pack(tmp_path, "finance", partial=False)
    decision = types.SimpleNamespace(
        can_activate=False, reasons=["not deployed on this connection — run Bind + verify"])

    with pytest.raises(PromotionRefused) as exc:
        set_status("finance", "active", packs_dir=tmp_path, gate_decision=decision)

    assert "not deployed" in str(exc.value)


def test_a_grounded_pack_activates_on_a_passing_verdict(tmp_path):
    _write_pack(tmp_path, "finance", partial=False)
    decision = types.SimpleNamespace(can_activate=True, reasons=[])

    pack = set_status("finance", "active", packs_dir=tmp_path, gate_decision=decision)

    assert pack.manifest.status == "active"


# ── the shadowing defect activation would otherwise introduce ────────────────────

def test_an_active_prose_pack_does_not_shadow_a_grounded_one(monkeypatch):
    """`select_pack` returns the single best match. Before this filter, an imported skill
    that outscored a deployed pack would win the routing and then fall out at the
    binding gate — steering would silently STOP on exactly the questions the real pack was
    deployed for, and the only symptom would be a generalist answer."""
    import aughor.packs.intake as intake

    prose = types.SimpleNamespace(id="imported", manifest=types.SimpleNamespace(partial=True))
    grounded = types.SimpleNamespace(id="finance", manifest=types.SimpleNamespace(partial=False))
    seen = {}
    monkeypatch.setattr(intake, "active_packs", lambda packs_dir=None: [prose, grounded])
    monkeypatch.setattr(intake, "select_pack",
                        lambda q, pool: (seen.setdefault("pool", [p.id for p in pool]),
                                         (pool[0], 1.0) if pool else None)[1])
    monkeypatch.setattr(intake, "load_binding", lambda pid, conn, schema: {"bindings": {"t": "x"}})
    monkeypatch.setattr(intake, "build_injection",
                        lambda pack, binding, business_model, currency_code:
                        types.SimpleNamespace(pack_id=pack.id))

    out = intake.injection_for_question("retention question", "conn-1")

    assert seen["pool"] == ["finance"], "a prose pack must never reach routing"
    assert out.pack_id == "finance"


# ── disclosure: the ladder an imported skill is read through ─────────────────────

@pytest.fixture
def packs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("aughor.routers.packs.PACKS_DIR", tmp_path)
    return tmp_path


def test_list_packs_advertises_a_description(packs_dir):
    """The cheap rung. Every pack's description is read on every call, so it must be
    affordable at scale — only the body of the one the model picks is ever fetched."""
    from aughor.agent import platform_tools as pt

    _write_pack(packs_dir, "cohorts", prose="Reasons in cohorts and lifecycles.")

    entry = pt.list_packs("c1", {})["packs"][0]

    assert entry["id"] == "cohorts"
    assert "cohorts" in entry["description"].lower()
    assert entry["partial"] is True
    assert entry["readable"] is False, "a draft pack is advertised but not readable"


def test_read_pack_refuses_a_draft_and_says_why(packs_dir):
    """Serving a draft here would break the importer's contract through a side door —
    and the side door is the one nobody audits."""
    from aughor.agent import platform_tools as pt

    _write_pack(packs_dir, "cohorts")

    out = pt.read_pack("c1", {"pack_id": "cohorts"})

    assert out["readable"] is False and out["status"] == "draft"
    assert "promotes" in out["why"]


def test_read_pack_serves_an_active_pack_with_its_provenance(packs_dir):
    from aughor.agent import platform_tools as pt

    _write_pack(packs_dir, "cohorts", status="active", prose="Reasons in cohorts.")

    out = pt.read_pack("c1", {"pack_id": "cohorts"})

    assert out["readable"] is True
    assert "Reasons in cohorts." in out["prose"]
    assert out["partial"] is True, "an answer leaning on prose must be able to say so"
    assert out["source"] == "awesome-agent-skills" and out["licence"] == "MIT"


def test_read_pack_bounds_the_body(packs_dir):
    """A tool result that eats the window it was fetched into is the VA-5 failure again."""
    from aughor.agent import platform_tools as pt

    _write_pack(packs_dir, "huge", status="active", prose="x" * 40_000)

    out = pt.read_pack("c1", {"pack_id": "huge"})

    assert out["truncated"] is True
    assert len(out["prose"]) <= pt._MAX_PACK_PROSE


def test_read_pack_distinguishes_unknown_from_unreadable(packs_dir):
    from aughor.agent import platform_tools as pt

    assert "no pack" in pt.read_pack("c1", {"pack_id": "nope"})["error"]
    assert "required" in pt.read_pack("c1", {})["error"]


def test_read_pack_is_in_the_roster(packs_dir):
    """Built-but-not-wired is the shape this whole arc keeps finding."""
    from aughor.agent.platform_tools import platform_tools

    names = {t.name for t in platform_tools("c1")}

    assert {"list_packs", "read_pack"} <= names


# ── the HTTP surface ──────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aughor.api import app
    return TestClient(app)


def test_status_route_promotes_a_prose_pack(client, packs_dir):
    _write_pack(packs_dir, "cohorts")

    res = client.post("/packs/cohorts/status", json={"status": "active", "actor": "amit"})

    assert res.status_code == 200, res.text
    assert res.json() == {"id": "cohorts", "status": "active", "partial": True}
    assert load_pack(packs_dir / "cohorts").manifest.status == "active"


def test_status_route_refuses_blocked_prose_with_409(client, packs_dir):
    """409, not 422: the request is well-formed and the pack is real — its own gate says
    no, which is a state conflict a caller resolves by fixing the pack."""
    _write_pack(packs_dir, "pinned", prose="Call claude-3-5-sonnet-20241022 first.")

    res = client.post("/packs/pinned/status", json={"status": "active"})

    assert res.status_code == 409
    assert "model-id" in res.text


def test_status_route_asks_a_grounded_pack_for_a_connection(client, packs_dir):
    _write_pack(packs_dir, "finance", partial=False)

    res = client.post("/packs/finance/status", json={"status": "active"})

    assert res.status_code == 422
    assert "connection_id" in res.text


def test_status_route_404s_an_unknown_pack_and_422s_an_unknown_status(client, packs_dir):
    _write_pack(packs_dir, "cohorts")

    assert client.post("/packs/nope/status", json={"status": "active"}).status_code == 404
    assert client.post("/packs/cohorts/status",
                       json={"status": "enabled"}).status_code == 422


def test_demotion_needs_no_connection_and_no_gate(client, packs_dir):
    _write_pack(packs_dir, "finance", partial=False, status="active")

    res = client.post("/packs/finance/status", json={"status": "deprecated"})

    assert res.status_code == 200 and res.json()["status"] == "deprecated"
