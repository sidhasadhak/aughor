"""Phase 7 of the 2027 study, P7-2 — the agent contract published from the code that enforces it
(`aughor/kernel/contract.py`, `docs/AGENT_CONTRACT.md`), and the platform's own agents held to it first.

What these hold: the document equals what the module renders, so it cannot drift; the seven duties are
the study's and every claim kind the writers book belongs to one; the verdicts are the inquiry's own; the
MCP server registers the four ledger tools with their levels; the refusal codes are the policy's.
"""
from __future__ import annotations

from pathlib import Path
from typing import get_args

from aughor.kernel import contract as K

REPO = Path(__file__).resolve().parents[2]


def test_the_published_document_is_what_the_code_renders():
    rendered = K.render_markdown()
    on_disk = (REPO / "docs" / "AGENT_CONTRACT.md").read_text(encoding="utf-8")
    assert on_disk == rendered, "docs/AGENT_CONTRACT.md drifted from aughor/kernel/contract.py — regenerate with `uv run python -m aughor.kernel.contract`"


def test_the_seven_duties_cover_every_claim_kind_the_platforms_own_writers_book():
    from aughor.record import claims as C
    assert [d["duty"] for d in K.DUTIES] == ["Observe", "Inquire", "Challenge", "Forecast", "Steward", "Operate", "Deliver"]
    for kind in get_args(C.ClaimKind):
        assert K.duty_for(kind), f"no duty is licensed to book {kind!r}"
    assert K.duty_for("prediction") == "Forecast" and K.duty_for("hypothesis") == "Inquire" and K.duty_for("action") == "Operate"
    assert K.duty_for("not-a-kind") == ""


def test_the_contract_reads_the_enforcing_modules_never_a_copy():
    from aughor.actions.authority import LEVELS
    from aughor.mcp import policy as P
    from aughor.record import claims as C
    from aughor.record.inquiry import VERDICTS
    c = K.contract()
    assert c["version"] == K.VERSION and c["verdicts"] == list(VERDICTS)
    assert c["entry"]["tiers"] == list(C.TIERS) and "inferred" not in c["entry"]["tiers"]
    assert c["entry"]["kinds"] == list(get_args(C.ClaimKind)) and len(c["entry"]["laws"]) == 4
    assert "confidence" in c["entry"]["read_only"] and "confidence" not in c["entry"]["fields"]
    assert c["levels"]["authority"]["ladder"] == {f"L{k}": v for k, v in LEVELS.items()}
    assert set(c["refusals"]) >= {P.CODE_LEVEL, P.CODE_TOOL, P.CODE_CONNECTION, P.CODE_SELF_SET, "CLAIM_REFUSED"}
    assert c["principals"]["service_principal"]["presented_as"] == {"X-Aughor-Service": "the service name", "X-Aughor-Service-Key": "the key"}


def test_the_mcp_door_carries_the_ledger_tools_with_their_levels():
    from aughor.mcp import policy as P
    from aughor.mcp.server import mcp
    registered = set(mcp._tool_manager._tools)
    assert {"read_contract", "post_claim", "read_claims", "read_restatements"} <= registered
    assert P.tool_level("post_claim") == "run" and P.tool_level("read_contract") == "read" and P.tool_level("read_restatements") == "read"
    assert P.route_level("POST", "/ledger/v1/claims") == "run" and P.route_level("POST", "/ledger/v1/methods") == "act"
    assert P.route_level("GET", "/ledger/v1/export") == "read" and P.route_level("DELETE", "/ledger/v1/subscriptions/{subscription_id}") == "act"
    doc = (REPO / "docs" / "MCP_SERVER.md").read_text(encoding="utf-8")
    for tool in ("read_contract", "post_claim", "read_claims", "read_restatements"):
        assert f"`{tool}`" in doc, f"docs/MCP_SERVER.md does not list {tool}"
