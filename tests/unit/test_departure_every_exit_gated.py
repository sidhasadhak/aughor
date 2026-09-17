"""HB-2 — every way information leaves the platform asks the departure gate.

The population is DISCOVERED, never hand-listed: every call to a message transport —
``fire_action`` (the Action Hub: Slack webhooks, Jira, webhooks) and ``post_as_bot`` (the
Slack bot) — found anywhere under ``aughor/`` by walking the syntax tree. A call site passes
when the function that makes it also asks the gate in its own body (``gate_departure``, or
the engine's ``_gate_departure``), or when ``UNGATED_BY_DESIGN`` names it with a reason. A
send added next month that forgets the gate fails here, and an exemption whose call site is
gone fails too — the list cannot quietly outlive what it excuses.

Not this test's population: a governed WRITE to another system (an integration call, an MCP
tool, a declared action) — those answer to the grant law and the approval gate, which decide
whether an act may happen; this gate decides whether information may leave.
"""
from __future__ import annotations

import ast
from pathlib import Path

from aughor.govern.departure import UNGATED_BY_DESIGN

ROOT = Path(__file__).resolve().parents[2]
TRANSPORTS = {"fire_action", "post_as_bot"}
GATES = {"gate_departure", "_gate_departure"}


class _OwnCalls(ast.NodeVisitor):
    """The names a function calls in its OWN body — a nested function is its own site."""

    def __init__(self, root: ast.AST):
        self.root = root
        self.names: set[str] = set()

    def visit_FunctionDef(self, node):
        if node is self.root:
            self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call):
        f = node.func
        if isinstance(f, ast.Name):
            self.names.add(f.id)
        elif isinstance(f, ast.Attribute):
            self.names.add(f.attr)
        self.generic_visit(node)


def _call_sites() -> dict[str, bool]:
    """``{"aughor/x.py::function": asks_the_gate}`` for every function that calls a transport."""
    sites: dict[str, bool] = {}
    for path in sorted((ROOT / "aughor").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = _OwnCalls(node)
            calls.visit(node)
            if calls.names & TRANSPORTS:
                sites[f"{rel}::{node.name}"] = bool(calls.names & GATES)
    return sites


def test_every_transport_call_asks_the_gate_or_is_excused_by_name():
    ungated = sorted(site for site, gated in _call_sites().items()
                     if not gated and site not in UNGATED_BY_DESIGN)
    assert not ungated, (
        "these functions send a message out of the platform without asking the departure "
        "gate (aughor/govern/departure.py) in the same function: " + ", ".join(ungated)
        + " — gate the send, or add the site to UNGATED_BY_DESIGN with the reason a "
          "person (not the gate) is the check there")


def test_every_exemption_still_names_a_real_call_site():
    sites = _call_sites()
    stale = sorted(site for site in UNGATED_BY_DESIGN if site not in sites)
    assert not stale, (
        f"UNGATED_BY_DESIGN excuses call sites that no longer send anything: {stale} — "
        f"remove them, so the list cannot outlive what it excuses")
    assert all(reason.strip() for reason in UNGATED_BY_DESIGN.values())


def test_the_scan_is_not_vacuous():
    """A walk that found nothing would pass the first test by construction. The wave gated
    seven sends and excused three; the population must stay at least that large."""
    sites = _call_sites()
    assert len(sites) >= 10, sites
    gated = {s for s, g in sites.items() if g}
    for expected in ("aughor/automations/engine.py::_dispatch_slack_post",
                     "aughor/automations/engine.py::_dispatch_notify",
                     "aughor/monitors/notify.py::dispatch_alert",
                     "aughor/briefing/delivery.py::deliver_subscription",
                     "aughor/obs/agent_alert_runner.py::deliver",
                     "aughor/routers/actions.py::send_finding_to_trigger",
                     "aughor/routers/actions.py::execute_recommendation_action"):
        assert expected in gated, f"{expected} no longer asks the gate"
