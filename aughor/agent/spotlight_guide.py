"""SP-4 (§3.11) — Spotlight's Guide limb: teach the product from inside it.

`platform_help` answers what a concept IS — curated paragraphs, CI-2's proto-Guide.
This module answers HOW to do a thing HERE, which needs two groundings a concept
paragraph cannot carry: the deployment's own live state (what YOU have built, how it
scored, whether a clock is even running) and an offered next act. Three laws shape
every topic:

* **The steps are the product's, not an impression of it.** Each walkthrough names
  the stations that exist in this build — the agent walkthrough is the create flow's
  own stepper (Start · Scope · Define · Prove · Reach), quoted rather than imagined.
  Curated text, no model, no network, exactly like the help corpus. Deeper prose
  arrives through the packs plane (the SKILL.md intake lands there), which the
  roster already serves.
* **Guidance ends in an offered act** (§3.11's Guide law). Every topic closes with
  the roster tool that starts the act — `draft_agent`, `draft_automation`,
  `set_preference` — or says honestly that the act lives on a page when no chat door
  exists: connecting data means entering credentials, which are a person's to type
  and never a model's to relay, so that topic offers a page and says why.
* **A door this deployment cannot open is never offered** (DS-17's law). The
  automation topic reads the real clock before implying schedules fire; a grounding
  read that fails reports itself unavailable rather than posing as an empty
  deployment — a failed probe and a true negative must never look identical.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aughor.agent.tool_loop import ToolSpec

logger = logging.getLogger(__name__)

_MAX_ROWS = 6
_FAILURE_WINDOW_DAYS = 7


# ── grounding reads — each honest about failure ──────────────────────────────────────

def _tolerate(exc: Exception, why: str, counter: str) -> None:
    from aughor.kernel.errors import tolerate
    tolerate(exc, why, counter=counter)


def _agents_grounding() -> dict | None:
    """The asker's own agents with their evaluation state — or None when unreadable."""
    try:
        from aughor.custom_agents.store import list_agents
        agents = list_agents()
    except Exception as exc:  # noqa: BLE001 — the module docstring's third law
        _tolerate(exc, "guide: could not read the agents store",
                  "spotlight_guide.agents")
        return None

    rows = []
    evaluated = 0
    for a in agents[:_MAX_ROWS]:
        ev = a.last_eval or {}
        basis = a.eval_basis
        if not ev or basis == "none":
            line = "never evaluated — its Prove step is still open"
        else:
            evaluated += 1
            passed, total = int(ev.get("passed") or 0), int(ev.get("total") or 0)
            if basis == "current":
                line = (f"{passed}/{total} golden questions passing, measured on the "
                        f"configuration running now")
            elif basis == "stale":
                line = (f"{passed}/{total} golden questions passing — but the "
                        f"configuration changed since; re-run the suite to re-earn it")
            else:
                line = (f"{passed}/{total} golden questions passing, measured before "
                        f"revision tracking — it cannot be tied to today's configuration")
        rows.append({"name": a.name, "enabled": a.enabled, "evaluation": line})
    out = {"total": len(agents), "evaluated_shown": evaluated, "agents": rows}
    if len(agents) > _MAX_ROWS:
        out["note"] = f"listing capped at {_MAX_ROWS} of {len(agents)}"
    return out


def _automations_grounding() -> dict | None:
    """Automation counts, the trailing failure count, and the clock — or None."""
    try:
        from aughor.automations.store import count_runs_since, list_automations
        autos = list_automations()
        floor = (datetime.now(timezone.utc)
                 - timedelta(days=_FAILURE_WINDOW_DAYS)).strftime("%Y-%m-%d")
        outcomes = count_runs_since(floor)
    except Exception as exc:  # noqa: BLE001
        _tolerate(exc, "guide: could not read the automations store",
                  "spotlight_guide.automations")
        return None
    clock_state, clock_detail = _clock()
    return {
        "total": len(autos),
        "enabled": sum(1 for a in autos if a.enabled),
        "window_days": _FAILURE_WINDOW_DAYS,
        "errors_in_window": int(outcomes.get("error") or 0),
        "clock": {"state": clock_state, "detail": clock_detail},
    }


def _clock() -> tuple[str, str]:
    """The deployment's real clock — `unknown` when the read fails, never a guess."""
    try:
        from aughor.automations.scheduler import clock
        return clock()
    except Exception as exc:  # noqa: BLE001
        _tolerate(exc, "guide: could not read the clock state", "spotlight_guide.clock")
        return "unknown", "clock state unavailable"


def _connections_grounding() -> dict | None:
    try:
        from aughor.db.registry import list_connections
        from aughor.org.context import current_org_id
        conns = list_connections(org_id=current_org_id() or None)
    except Exception as exc:  # noqa: BLE001
        _tolerate(exc, "guide: could not read the connections registry",
                  "spotlight_guide.connections")
        return None
    types = sorted({str(c.get("conn_type") or c.get("type") or "") for c in conns} - {""})
    return {"total": len(conns), "engine_types": types}


def _preferences_grounding() -> dict | None:
    try:
        from aughor.db.user_prefs import get_preferences
        return get_preferences()
    except Exception as exc:  # noqa: BLE001
        _tolerate(exc, "guide: could not read the preferences store",
                  "spotlight_guide.preferences")
        return None


# ── the topics — steps are the product's own, offers are the roster's own ────────────

_UNAVAILABLE = ("the live numbers are unavailable right now — the walkthrough stands, "
                "but do not quote counts you were not given")


def _guide_create_agent() -> dict:
    steps = [
        "Start (Agents page → New agent): begin from a domain pack or from scratch.",
        "Scope: name it and say where it may look — a connection, optionally one "
        "schema. A narrower scope answers more reliably.",
        "Define: write its instructions (its scope and stance, in full sentences) and "
        "attach documents. Attaching none is restrictive, not neutral: an agent with "
        "no documents sees NO documents — fewer than asking with no agent at all.",
        "Prove: add golden questions and run the evaluation suite. The pass chip is "
        "earned by that exact configuration and goes stale if the configuration "
        "changes.",
        "Reach (optional): bind a Slack bot so people can reach it outside this app.",
    ]
    g = _agents_grounding()
    offer = {
        "tool": "draft_agent",
        "sentence": ("I can draft the agent from your description right now — it is "
                     "staged in the approvals inbox, and nothing exists until a "
                     "person accepts it there."),
    }
    if g is None:
        summary = (f"To create an agent: Start → Scope → Define → Prove on the Agents "
                   f"page — or I can draft one from your description and stage it for "
                   f"approval. Your existing agents could not be read just now; "
                   f"{_UNAVAILABLE}.")
    else:
        summary = (f"You have {g['total']} agents (evaluation state per agent listed). "
                   f"To create one: Start → Scope → Define → Prove on the Agents page "
                   f"— or I can draft it from your description now and stage it for "
                   f"your approval.")
    return {"topic": "create_agent", "steps": steps, "grounding": g,
            "offer": offer, "summary": summary}


def _guide_create_automation() -> dict:
    steps = [
        "Describe the outcome in one sentence — the platform drafts the chain itself, "
        "validates it against what this deployment can actually do, and attaches a "
        "dry-run. (You can also build it by hand on the Automations canvas.)",
        "The draft is staged in the approvals inbox: a person accepts or rejects it "
        "there, and acceptance re-validates before anything is saved. Nothing "
        "schedules itself.",
        "Once accepted, enable it and choose its doors — schedule, webhook, Slack, "
        "MCP tool. Each door reports whether THIS deployment can open it.",
    ]
    g = _automations_grounding()
    offer = {
        "tool": "draft_automation",
        "sentence": ("Describe the outcome and I will draft it now, with its dry-run "
                     "attached, staged for your approval — a refusal with a reason is "
                     "an answer, not an error."),
    }
    if g is None:
        summary = (f"To create an automation: describe the outcome, the platform "
                   f"drafts and dry-runs it, a person accepts it in the inbox, then "
                   f"you enable it and pick its doors. The automations store could "
                   f"not be read just now; {_UNAVAILABLE}.")
    else:
        clock = g["clock"]
        clock_line = ""
        if clock["state"] == "stopped":
            clock_line = (" NOTE: no clock is running on this deployment right now, so "
                          "schedules will not fire until the heartbeat starts or an "
                          "external cron drives the tick — say so before promising a "
                          "schedule.")
        err = g["errors_in_window"]
        err_line = (f" {err} runs errored in the last {g['window_days']} days — worth "
                    f"a look before adding more." if err else "")
        summary = (f"You have {g['total']} automations ({g['enabled']} enabled)."
                   f"{err_line} To create one: describe the outcome, the platform "
                   f"drafts and dry-runs it, a person accepts it in the inbox, then "
                   f"you enable it and pick its doors.{clock_line}")
    return {"topic": "create_automation", "steps": steps, "grounding": g,
            "offer": offer, "summary": summary}


def _guide_connect_data() -> dict:
    steps = [
        "Connections page (the plug icon in the sidebar): choose the engine — for "
        "example Snowflake, Postgres, BigQuery or DuckDB — and supply its credentials "
        "or connection string yourself. Credentials never pass through this chat, "
        "deliberately.",
        "Run an exploration on the new connection so the platform can profile the "
        "data and start discovering findings on its own.",
        "From then on chat answers against it, and health checks, query-pattern "
        "mining and the knowledge graph accumulate as it is used.",
    ]
    g = _connections_grounding()
    offer = {
        "tool": "",
        "sentence": ("This act lives on the Connections page — there is no chat door "
                     "for credentials, by design. I can answer questions about the "
                     "connections you already have."),
    }
    if g is None:
        summary = (f"To connect data: add the warehouse on the Connections page "
                   f"(credentials are yours to enter — never sent through chat), then "
                   f"run an exploration. The registry could not be read just now; "
                   f"{_UNAVAILABLE}.")
    else:
        engines = ", ".join(g["engine_types"]) if g["engine_types"] else "none yet"
        summary = (f"This deployment has {g['total']} connections (engines: "
                   f"{engines}). To add one: Connections page, choose the engine, "
                   f"enter its credentials yourself — they never pass through chat — "
                   f"then run an exploration so the platform can profile it.")
    return {"topic": "connect_data", "steps": steps, "grounding": g,
            "offer": offer, "summary": summary}


def _guide_appearance() -> dict:
    steps = [
        "Say the preference — theme dark, light or system; density; or your default "
        "connection — and it is applied to your stored profile immediately, no "
        "approval and no page visit.",
        "The preference is stored to your user, not to one browser: every surface "
        "that reads stored preferences follows it, and this screen picks it up from "
        "its next load. The Settings page carries the same switch.",
    ]
    g = _preferences_grounding()
    offer = {
        "tool": "set_preference",
        "sentence": ("Tell me the value and I will set it now — the same tool is the "
                     "reset door."),
    }
    if g is None:
        summary = (f"Appearance is one stored preference away — say the theme or "
                   f"density you want and it applies to your profile immediately. "
                   f"Your current preferences could not be read just now; "
                   f"{_UNAVAILABLE}.")
    else:
        prefs = g.get("preferences") or {}
        current = (", ".join(f"{k} = {v}" for k, v in sorted(prefs.items()))
                   or "none set — every surface uses its default")
        summary = (f"Your stored preferences: {current}. Say the theme (dark, light, "
                   f"system), density or default connection you want and I will set "
                   f"it immediately — it follows your user, and this screen picks it "
                   f"up from its next load.")
    return {"topic": "appearance", "steps": steps, "grounding": g,
            "offer": offer, "summary": summary}


_GUIDE_TOPICS = {
    "create_agent": _guide_create_agent,
    "create_automation": _guide_create_automation,
    "connect_data": _guide_connect_data,
    "appearance": _guide_appearance,
}

_GUIDE_ALIASES = {
    "agent": "create_agent", "agents": "create_agent",
    "custom agent": "create_agent", "new agent": "create_agent",
    "automation": "create_automation", "automations": "create_automation",
    "schedule": "create_automation", "scheduling": "create_automation",
    "cron": "create_automation", "workflow": "create_automation",
    "connect": "connect_data", "connection": "connect_data",
    "connections": "connect_data", "warehouse": "connect_data",
    "database": "connect_data", "data source": "connect_data",
    "theme": "appearance", "dark mode": "appearance", "light mode": "appearance",
    "density": "appearance", "preferences": "appearance",
    "preference": "appearance", "look": "appearance",
}


def platform_guide(args: dict) -> dict:
    """One grounded walkthrough — or, for an unknown topic, the honest topic list."""
    raw = str(args.get("topic") or "").strip().lower()
    resolved = _GUIDE_ALIASES.get(raw, raw)
    if resolved in _GUIDE_TOPICS:
        out = _GUIDE_TOPICS[resolved]()
        out["topics"] = sorted(_GUIDE_TOPICS)
        return out
    # An unknown topic is an answer: name what CAN be walked through, and route
    # concept questions to the concept tool rather than guessing a walkthrough.
    return {
        "topic": raw, "topics": sorted(_GUIDE_TOPICS),
        "summary": (f"No walkthrough exists for {raw!r} — the topics are: "
                    + ", ".join(sorted(_GUIDE_TOPICS)) +
                    ". For what a concept IS (briefings, monitors, packs, "
                    "governance), use the help tool instead."),
    }


# ── the roster ───────────────────────────────────────────────────────────────────────

_GUIDE_PARAMS = {
    "type": "object",
    "properties": {"topic": {
        "type": "string",
        "description": "What to walk through: create_agent, create_automation, "
                       "connect_data, or appearance (theme, density, defaults). "
                       "Plain words like 'agent' or 'dark mode' resolve too.",
    }},
    "required": ["topic"],
}


def spotlight_guide_tools(connection_id: str, *, session_id: str = "") -> list[ToolSpec]:
    """SP-4's Guide roster — one tool, read-only; the offer is prose, never an act."""
    return [
        ToolSpec(
            name="platform_guide",
            description=(
                "HOW to do something on this platform, step by step, grounded in "
                "THIS deployment's live state and ending in an offered next action. "
                "Topics: creating an agent, creating or scheduling an automation, "
                "connecting data, appearance (theme, density, defaults). Use it for "
                "'how do I / how should I…' questions about USING the product; for "
                "what a concept IS use platform_help, and for questions about the "
                "data itself use the data tools. Walk the steps in order, cite the "
                "user's own objects from the grounding field, and END your answer by "
                "making the offer the result names — the offer's tool is on your "
                "roster. Quote the summary field verbatim for the numbers — never "
                "re-derive them from the other fields."
            ),
            parameters=_GUIDE_PARAMS,
            run=lambda a: platform_guide(a),
        ),
    ]
