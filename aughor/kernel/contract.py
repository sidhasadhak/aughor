"""The agent contract — published from the code that enforces it (the 2027 study §H, §Q and
§W; phase 7, P7-2).

An agent is defined by the kind of entry it is licensed to book in the ledger, not by the name it is
given: seven duties, each booking its own kinds. An outside agent (any vendor's) takes the same duties
through the two doors — the MCP server and the ledger API — under a service principal, held to the
same contract as the platform's own agents, which are held to it first. This module is the one
authority for what the contract says; `docs/AGENT_CONTRACT.md` is rendered from it and a test holds
the two equal, so the published document can never drift from the code.

What the contract covers: the duties and what each books; the typed verdicts a run ends in; what
an entry must carry (the claim's kinds, tiers, statuses, warrants and the three laws at the door);
who may book (principal kinds, how a service principal is minted and recognised); the levels
(the agent policy's read · run · act, the authority ladder's L0–L5); the doors; how an agent is
scored (by what became of its entries, never by a judge); and the refusals, each with its stable
code. Nothing here is prose a model interprets — every list is read from the module that enforces it.
"""
from __future__ import annotations

from typing import Any, get_args

VERSION = "2027.1"

#: The seven duties (the study §H): what each books, and which built-in agent carries it today.
DUTIES: tuple[dict[str, Any], ...] = (
    {"duty": "Observe", "books": ["observation", "reading"], "proposes": ["monitor"],
     "today": "Explorer, Watcher", "why": "somebody has to look where nobody asked"},
    {"duty": "Inquire", "books": ["hypothesis", "finding"], "proposes": [],
     "today": "Analyst (SQL Engineer, Narrator, Orchestrator inside it)", "why": "explanation is a search over causes"},
    {"duty": "Challenge", "books": ["cause"], "proposes": ["refutation of a hypothesis"],
     "today": "Verifier; the skeptic step and its causal_checks record",
     "why": "a claim rises a tier only after an attempt to break it — by a different binding where the install has two"},
    {"duty": "Forecast", "books": ["prediction"], "proposes": ["scenario"],
     "today": "the scenario ladder's methods (code); no model forecasts",
     "why": "a system that never commits to an expectation can never be scored"},
    {"duty": "Steward", "books": ["definition", "said"], "proposes": ["duplicate", "coverage gap"],
     "today": "Curator, the business explorer", "why": "the model of the business goes stale; people confirm what a steward proposes"},
    {"duty": "Operate", "books": ["action"], "proposes": ["preview"],
     "today": "the executor, under a person's approval or a standing grant", "why": "closes the loop"},
    {"duty": "Deliver", "books": ["departure"], "proposes": [],
     "today": "Responder, Briefer", "why": "attention is spent at this door and nowhere else"},
)

#: The three laws at the ledger's door (`record/claims.py`), as sentences an outside author reads.
LAWS: tuple[str, ...] = (
    "No fact without a warrant: a claim at tier `measured` carries a `run` warrant (the receipt of the statement that "
    "produced it); `approved` and `declared` need a person as author or an `attestation` warrant. A tier a claim cannot "
    "warrant is refused, never quietly lowered.",
    "No model-authored fact: tier `inferred` is not a claim. What a model concludes without a run behind it is a "
    "`hypothesis` at tier `said`, and stays one until a run or a person raises it.",
    "Confidence is counted or absent: no author sets it. It is filled on read as the hit rate of the claim's reference "
    "class with its n, or left empty.",
)

#: The ledger API's door for outside authors adds one more: every posted claim names at least one warrant.
API_LAW = ("The ledger API refuses a claim that names no warrant at all, whatever its tier: an outside author's claim "
           "enters through the one door, with what entitles it to be relied on.")


def _claim_vocabulary() -> dict[str, Any]:
    from aughor.record import claims as C
    return {
        "kinds": list(get_args(C.ClaimKind)), "tiers": list(C.TIERS), "statuses": list(get_args(C.Status)),
        "about_kinds": list(get_args(C.AboutKind)), "author_kinds": list(get_args(C.AuthorKind)),
        "warrant_kinds": list(get_args(C.WarrantKind)),
        "fields": [n for n in C.Claim.model_fields if n not in ("id", "key", "version", "recorded_at", "supersedes", "superseded_by", "confidence")],
        "read_only": ["id", "key", "version", "recorded_at", "supersedes", "superseded_by", "confidence"],
        "states": {"hypothesis": ["open", "supported", "refuted", "abandoned"], "prediction": ["open", "scored"]},
    }


def _verdicts() -> list[str]:
    from aughor.record.inquiry import VERDICTS
    return list(VERDICTS)


def _levels() -> dict[str, Any]:
    from aughor.actions.authority import GRADUATION_N, LEVELS
    from aughor.orgsettings.agent_policy import LEVELS as POLICY_LEVELS
    return {
        "agent_policy": {"levels": list(POLICY_LEVELS), "default": "run",
                         "read": "look things up", "run": "start work or book an entry with its warrant",
                         "act": "change something outside the conversation — given only by a person"},
        "authority": {"ladder": {f"L{k}": v for k, v in LEVELS.items()}, "graduation_n": GRADUATION_N,
                      "rule": "the lower of the ceiling a person set and what the record earned; L4 only on a graduation receipt; "
                              "an irreversible action never passes L3; L5 only on an L5 receipt a person books on a long L4 record "
                              "inside a mission whose ceiling sets it, and the agent then chooses among the declared actions at L5 "
                              "by their measured effect on the mission's objective, one action per review period"},
    }


def _principals() -> dict[str, Any]:
    from aughor.security.service_principals import KEY_HEADER, NAME_HEADER
    return {
        "kinds": ["person (user:<id>)", "agent (agent:<id>, the platform's own)", "service (service:<name>, an outside vendor's)",
                  "group (group:<id>)"],
        "service_principal": {
            "minted_by": "a person, at POST /ledger/v1/principals/service — the key is returned once, stored hashed",
            "presented_as": {NAME_HEADER: "the service name", KEY_HEADER: "the key"},
            "held_to": "the organisation's agent policy (read · run · act, connection and tool allowlists), audited as an agent",
            "author": "every entry it books carries `service:<name>` as author with author_kind `agent`",
            "scored": "like every author: by what became of its entries (GET /ledger/v1/principals/{principal}/record)",
        },
    }


def _doors() -> dict[str, Any]:
    return {
        "ledger_api": {
            "prefix": "/ledger/v1",
            "routes": [
                "GET /contract — this contract", "POST /claims — post a claim with its warrant (run)",
                "GET /claims?as_of= — claims as recorded on a date", "GET /claims/{id} · GET /claims/{id}/versions",
                "GET /restatements?since= — what changed since a cursor",
                "POST /subscriptions · GET /subscriptions · DELETE /subscriptions/{id} — webhooks for events out",
                "GET /events?kind=&since_seq= · GET /events/catalogue", "GET /export — the ledger as JSON lines",
                "GET /principals/{principal}/record", "GET /methods · POST /methods — the method interface",
                "GET /aggregates · POST /aggregates/export",
            ],
        },
        "mcp": {"server": "aughor.mcp.server", "tools": ["read_contract", "post_claim", "read_claims", "read_restatements"],
                "note": "the same policy and audit as every other tool; no raw query tool, by design"},
        "never": ["a write path around the warrant", "anything that runs inside the platform's process", "anything that grades itself"],
    }


def _scoring() -> dict[str, Any]:
    from aughor.record import confidence as CF
    return {
        "principle": "an agent's score is a count of what became of its entries, never a model's opinion",
        "by_entry": {"observation": "restated or held on re-check", "hypothesis": "supported · refuted · abandoned",
                     "finding": "survived a challenge and a person's verdict", "prediction": "inside its band at settle",
                     "action": "verification passed and outcome inside expectation", "departure": "opened and not marked wrong"},
        "reference_classes": [CF.RECHECKED, CF.CHALLENGED, CF.PREDICTED], "min_n": CF.MIN_N,
        "calibration": "interval coverage by method, metric and author (GET /record/calibration)",
        "cost": "cost per warranted claim",
    }


def _refusals() -> dict[str, str]:
    from aughor.mcp import policy as P
    return {
        P.CODE_LEVEL: "the policy's level is below what the tool or route needs",
        P.CODE_TOOL: "the tool is not on the organisation's allowlist",
        P.CODE_CONNECTION: "the connection is not on the organisation's allowlist",
        P.CODE_SELF_SET: "an agent tried to set its own policy",
        "CLAIM_REFUSED": "the ledger's door said no: a tier without its warrant, a model-authored fact, a stated confidence, "
                         "a claim with no warrant at all, or a restatement of another author's claim",
        "SERVICE_KEY_REFUSED": "a service header was presented and did not match a minted, unrevoked key",
    }


def contract() -> dict[str, Any]:
    """The contract as data — what the API, the MCP server and the document all read."""
    return {"version": VERSION, "duties": [dict(d) for d in DUTIES], "verdicts": _verdicts(),
            "entry": {**_claim_vocabulary(), "laws": list(LAWS) + [API_LAW]},
            "principals": _principals(), "levels": _levels(), "doors": _doors(), "scoring": _scoring(),
            "refusals": _refusals()}


def duty_for(kind: str) -> str:
    """The duty licensed to book a claim kind — "" when none is (the test that holds the platform's own
    writers to the contract reads this)."""
    return next((d["duty"] for d in DUTIES if kind in d["books"]), "")


def render_markdown() -> str:
    """`docs/AGENT_CONTRACT.md`, rendered from the data above."""
    c = contract()
    out = [f"# The agent contract (v{c['version']})", "",
           "> Rendered from `aughor/kernel/contract.py`; `tests/unit/test_agent_contract.py` holds this file equal to the code. "
           "Edit the module, then regenerate with `uv run python -m aughor.kernel.contract`.", "",
           "An agent is defined by the kind of entry it is licensed to book in the ledger, not by the name it is given. An outside "
           "agent takes the same duties through the MCP server and the ledger API, under a service principal, held to the "
           "same contract as the platform's own agents — which are held to it first.", "",
           "## The seven duties", "", "| Duty | Books | Proposes | Today | Why it exists |", "|---|---|---|---|---|"]
    for d in c["duties"]:
        out.append(f"| **{d['duty']}** | {', '.join(d['books'])} | {', '.join(d['proposes']) or '—'} | {d['today']} | {d['why']} |")
    out += ["", "## The typed verdicts a run ends in", "",
            "Every run books one, never an empty result: " + " · ".join(f"`{v}`" for v in c["verdicts"]) + ".", "",
            "## What an entry must carry", ""]
    e = c["entry"]
    out += [f"- **kinds**: {', '.join(f'`{k}`' for k in e['kinds'])}",
            f"- **tiers** (the authority ladder, minus the one that is not a claim): {', '.join(f'`{t}`' for t in e['tiers'])}",
            f"- **statuses**: {', '.join(f'`{s}`' for s in e['statuses'])}",
            f"- **about**: {', '.join(f'`{a}`' for a in e['about_kinds'])}",
            f"- **author kinds**: {', '.join(f'`{a}`' for a in e['author_kinds'])}",
            f"- **warrants**: {', '.join(f'`{w}`' for w in e['warrant_kinds'])}",
            f"- **fields an author writes**: {', '.join(f'`{f}`' for f in e['fields'])}",
            f"- **filled by the ledger, never by an author**: {', '.join(f'`{f}`' for f in e['read_only'])}",
            f"- **states**: hypothesis {' · '.join(e['states']['hypothesis'])}; prediction {' · '.join(e['states']['prediction'])}",
            "", "### The laws at the door", ""]
    out += [f"{i}. {law}" for i, law in enumerate(e["laws"], 1)]
    p = c["principals"]
    out += ["", "## Who may book", "", "Principal kinds: " + "; ".join(p["kinds"]) + ".", "", "A **service principal** is:", ""]
    out += [f"- {k.replace('_', ' ')}: {v if isinstance(v, str) else ', '.join(f'`{h}`: {w}' for h, w in v.items())}"
            for k, v in p["service_principal"].items()]
    lv = c["levels"]
    out += ["", "## Levels", "", f"The agent policy: {' · '.join(f'`{x}`' for x in lv['agent_policy']['levels'])} (default `{lv['agent_policy']['default']}`). "
            f"Read: {lv['agent_policy']['read']}. Run: {lv['agent_policy']['run']}. Act: {lv['agent_policy']['act']}.", "",
            "The authority ladder for actions: " + " · ".join(f"{k} {v}" for k, v in lv["authority"]["ladder"].items())
            + f". {lv['authority']['rule']}; graduation needs {lv['authority']['graduation_n']} verified executions.", "",
            "## The doors", "", f"The ledger API, under `{c['doors']['ledger_api']['prefix']}`:", ""]
    out += [f"- {r}" for r in c["doors"]["ledger_api"]["routes"]]
    out += ["", f"The MCP server (`{c['doors']['mcp']['server']}`) adds {', '.join(f'`{t}`' for t in c['doors']['mcp']['tools'])}; "
            f"{c['doors']['mcp']['note']}.", "", "What no door offers: " + "; ".join(c["doors"]["never"]) + ".", "",
            "## How an agent is scored", "", c["scoring"]["principle"] + ".", ""]
    out += [f"- **{k}**: {v}" for k, v in c["scoring"]["by_entry"].items()]
    out += ["", f"Reference classes counted today: {', '.join(c['scoring']['reference_classes'])}; a hit rate is shown from "
            f"n = {c['scoring']['min_n']}. {c['scoring']['calibration'].capitalize()}. The cost measure is {c['scoring']['cost']}.",
            "", "## Refusals", "", "| Code | Meaning |", "|---|---|"]
    out += [f"| `{code}` | {why} |" for code, why in c["refusals"].items()]
    return "\n".join(out) + "\n"


if __name__ == "__main__":  # pragma: no cover — the regeneration command the document names
    from pathlib import Path
    target = Path(__file__).resolve().parents[2] / "docs" / "AGENT_CONTRACT.md"
    target.write_text(render_markdown(), encoding="utf-8")
    print(f"wrote {target}")
