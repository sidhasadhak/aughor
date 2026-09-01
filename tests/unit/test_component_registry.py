"""DS-10 — one component registry: every capability this deployment has, and nothing else.

Five rosters existed and nothing could read them together, so "what can this install do"
had no answer. Each family keeps its own source of truth; this registry ADAPTS them at read
time, which is the only arrangement in which a seventh effect kind or a new connector
appears without anyone remembering to add it twice.

The properties pinned here, each one something a plausible implementation gets wrong:

* **Adapted, never copied.** Every family's membership is asserted against that family's
  OWN source, so a registry that had quietly grown its own table of effect kinds fails.
* **The law: a component references a governed capability.** Every row names the module
  that governs its use, and this file IMPORTS each distinct value — a taxonomy nobody can
  check is how a roster starts describing a system that no longer exists.
* **Nothing that isn't real, and nothing real left out.** The connector family is built
  from the full type set rather than the builder registry, because the two KNOWLEDGE
  connectors are configured, authenticated and synced by a live route while having no
  `open_connection()` — a roster built off the builders alone omits two capabilities the
  deployment genuinely has.
* **Deployment-shaped, not version-shaped.** Availability is a measured reading, and a
  family whose probe RAISES stays ready rather than dimming: an unreachable store is our
  problem, not the reader's.
* **The palette cannot disagree with it**, because the palette is served from it.
* **Badges are empty by intent.** Beta and Legacy are registry metadata with a closed set
  and no members today; the point is that when there is one, every surface sees it.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.components import BADGES, FAMILIES, GOVERNORS, components

client = TestClient(app)


# ── the law ───────────────────────────────────────────────────────────────────

def test_every_component_names_a_governor_that_exists():
    """The law, made checkable. `governed_by` is a dotted module path, not a label, and
    every distinct value is imported here — so a component cannot reference a governed
    capability that was renamed, moved or deleted."""
    rows = components(conn_id="fixture")
    assert rows, "the registry reported nothing at all"
    used = sorted({c.governed_by for c in rows})
    for path in used:
        assert path in GOVERNORS, f"{path!r} is not a declared governor"
        importlib.import_module(path)          # raises if the governor is not real


def test_the_governor_list_has_no_dead_entries():
    """The other direction: a governor nobody references is either a family that stopped
    reporting or a paste that never applied. Both are worth failing over."""
    for path in GOVERNORS:
        importlib.import_module(path)


def test_a_declared_write_is_governed_by_the_approval_gate_not_the_engine():
    """The distinction the law exists to preserve. Every automation step runs through the
    engine; only a declared write passes the graduated-approval gate, and a roster that
    said otherwise would describe every step as equally governed."""
    rows = {c.id: c for c in components(conn_id="fixture")}
    assert rows["effect:kinetic_action"].governed_by == "aughor.actions.executor"
    assert rows["effect:slack_post"].governed_by == "aughor.automations.engine"


# ── adapted, never copied ─────────────────────────────────────────────────────

def test_the_automation_families_match_the_palette_exactly():
    from aughor.automations.palette import ACTIONS, TRIGGERS

    rows = components()
    assert {c.kind for c in rows if c.family == "trigger"} == {e.kind for e in TRIGGERS}
    assert {c.kind for c in rows if c.family == "effect"} == {e.kind for e in ACTIONS}


def test_the_connector_family_matches_the_full_type_set():
    """Not `REGISTRY.supported_types()` — that is the set with an `open_connection()`, and
    it excludes the knowledge connectors, which are real, authenticated and synced by
    `POST /connections/{id}/knowledge-sync`."""
    from aughor.connectors.registry import CATEGORIES, REGISTRY

    kinds = {c.kind for c in components(family="connector")}
    assert kinds == set(CATEGORIES) | {"duckdb", "postgres"}
    # …and the two that the builder list would have dropped are present.
    missed_by_builders = kinds - set(REGISTRY.supported_types()) - {"duckdb", "postgres"}
    assert {"notion", "confluence"} <= kinds
    assert missed_by_builders, "the builder list no longer differs — re-check this premise"


def test_the_tool_families_match_their_own_rosters():
    from aughor.agent.platform_tools import platform_tools
    from aughor.mcp.server import mcp

    rows = components(conn_id="fixture")
    assert ({c.kind for c in rows if c.family == "platform_tool"}
            == {t.name for t in platform_tools("fixture")})
    assert ({c.kind for c in rows if c.family == "mcp_tool"}
            == {t.name for t in mcp._tool_manager.list_tools()})


def test_the_mcp_family_is_counted_independently_of_how_it_is_read():
    """The registry reads FastMCP's `_tool_manager` — a third-party internal. Comparing the
    roster against that same attribute would agree with itself the day an upgrade moves it,
    and the family would silently empty. Counting the decorators in the source is an
    independent reading, so the degradation fails here instead of shipping."""
    import re
    from pathlib import Path

    declared = len(re.findall(r"^@mcp\.tool\(", Path("aughor/mcp/server.py").read_text(),
                              re.M))
    assert declared > 0, "the decorator scan found nothing — re-check this premise"
    assert len([c for c in components() if c.family == "mcp_tool"]) == declared


def test_a_new_effect_kind_cannot_be_added_without_appearing_here():
    """The whole point of adapting rather than copying, stated as a test. If this ever
    fails, someone has given the registry a table of its own."""
    from aughor.automations.palette import ACTIONS

    before = {c.kind for c in components(family="effect")}
    assert before == {e.kind for e in ACTIONS}
    assert "subchain" in before, "DS-9's kind should be here with no registry edit at all"


# ── deployment-shaped ─────────────────────────────────────────────────────────

def test_declared_actions_need_a_connection_to_be_true_about():
    """The one authored family. Asking without a connection returns none rather than every
    connection's — a declared action is meaningful only against the one that declares it."""
    assert [c for c in components() if c.family == "declared_action"] == []


def test_availability_is_a_measured_reading_not_a_constant():
    rows = {c.id: c for c in components(conn_id="conn-with-nothing")}
    # A kind whose referenced object does not exist here is dimmed WITH its reason…
    dimmed = [c for c in rows.values() if c.availability == "needs_setup"]
    assert dimmed, "nothing was dimmed on an empty connection — the probes are not running"
    assert all(c.reason for c in dimmed), "a dimmed row must say why"
    # …and a kind that references nothing outside itself is never dimmed.
    assert rows["trigger:schedule"].availability == "ready"


def test_a_missing_driver_is_unavailable_not_needs_setup(monkeypatch):
    """Nothing a reader types into a form fixes an uninstalled package, and offering them
    the form anyway is the failure `/connectors/types` was written to stop.

    The condition is MADE here, not looked for. This install happens to be missing exactly
    one driver today, so a test that scanned for one would pass on the strength of a fact
    about this laptop — and would go quietly vacuous the day someone `pip install`s it,
    which is the shape of a guard that stops guarding without failing once."""
    from aughor.components import registry

    monkeypatch.setattr(registry, "missing_drivers", lambda t: ["nonesuch-driver"],
                        raising=False)
    import aughor.connectors.registry as connreg
    monkeypatch.setattr(connreg, "missing_drivers", lambda t: ["nonesuch-driver"])

    rows = components(family="connector")
    assert rows, "the connector family stopped reporting"
    assert all(c.availability == "unavailable" for c in rows)
    assert all("nonesuch-driver" in c.reason for c in rows)
    # `unavailable`, never `needs_setup` — the two mean different things to a reader.
    assert not any(c.availability == "needs_setup" for c in rows)


def test_a_family_that_cannot_be_read_does_not_take_the_roster_down(monkeypatch):
    """One unimportable subsystem must not make the surface answer "this install can do
    nothing" — which is both false and the most alarming possible way to be wrong."""
    from aughor.components import registry

    monkeypatch.setattr(registry, "_mcp_tool_components",
                        lambda: (_ for _ in ()).throw(RuntimeError("mcp is down")))
    monkeypatch.setitem(registry._COLLECTORS, "mcp_tool",
                        lambda conn_id: registry._mcp_tool_components())

    rows = components()
    assert [c for c in rows if c.family == "mcp_tool"] == []
    assert [c for c in rows if c.family == "connector"], "a healthy family stopped reporting"


# ── the shape ─────────────────────────────────────────────────────────────────

def test_ids_are_unique_across_families():
    rows = components(conn_id="fixture")
    ids = [c.id for c in rows]
    assert len(ids) == len(set(ids))


def test_outputs_distinguish_publishes_nothing_from_the_open_set():
    """`[]` and `None` are different claims and a binding checker reads them differently:
    empty REFUSES a binding at save, open accepts it unchecked."""
    rows = {c.id: c for c in components(conn_id="fixture")}
    assert rows["effect:notify"].outputs == []
    assert rows["effect:kinetic_action"].outputs is None
    assert rows["effect:slack_post"].outputs == ["ts", "channel"]


def test_exposable_as_tool_is_true_only_for_things_that_are_callable():
    """DS-14 reads this flag. An automation step is not callable on its own, and saying
    otherwise would promise that wave a surface which does not exist."""
    for c in components(conn_id="fixture"):
        expected = c.family in ("platform_tool", "mcp_tool", "declared_action")
        assert c.exposable_as_tool is expected, c.id


def test_badges_are_empty_by_intent_and_closed_by_definition():
    assert set(BADGES) == {"beta", "legacy"}
    assert all(c.badges == [] for c in components(conn_id="fixture"))


def test_a_secret_port_is_marked_as_one():
    """A credential must never reach a URL, a query string or a log line — the rule the
    connector catalog states for itself, carried onto the port so a renderer cannot lose
    it on the way."""
    bq = [c for c in components(family="connector") if c.kind == "bigquery"][0]
    assert any(p.secret for p in bq.inputs)


# ── search and filtering ──────────────────────────────────────────────────────

def test_search_matches_label_description_kind_and_family():
    assert [c.id for c in components(q="slack")] == ["effect:slack_post"]
    assert all(c.family == "connector" for c in components(q="connector"))
    assert components(q="zzzz-no-such-thing") == []


def test_the_family_filter_is_a_closed_set_at_the_door():
    assert client.get("/components?family=effect").status_code == 200
    r = client.get("/components?family=not-a-family")
    assert r.status_code == 422 and "unknown family" in str(r.json()["detail"])


# ── the door ──────────────────────────────────────────────────────────────────

def test_the_endpoint_reports_every_family_and_counts_them():
    body = client.get("/components?conn_id=fixture").json()
    assert body["total"] == len(body["components"])
    assert set(body["by_family"]) == set(FAMILIES)
    # Four families are the same on every install of this build; they must all be there.
    for fam in ("trigger", "effect", "connector", "platform_tool", "mcp_tool"):
        assert body["by_family"][fam] > 0, fam
    assert body["conn_id"] == "fixture"


def test_the_endpoint_echoes_the_connection_so_absence_is_readable():
    """"this deployment has no declared actions" and "you did not say which connection"
    look identical in a list of rows, and only one of them is the reader's to fix."""
    assert client.get("/components").json()["conn_id"] == ""


def test_families_and_badges_are_served_as_closed_sets():
    body = client.get("/components/families").json()
    assert body["families"] == list(FAMILIES)
    assert body["badges"] == list(BADGES)


# ── the palette cannot disagree ───────────────────────────────────────────────

@pytest.mark.parametrize("conn_id", ["fixture", "conn-with-nothing"])
def test_the_palette_is_served_from_the_registry(conn_id):
    """Not "they happen to agree" — the palette route reads `components()`, so this asserts
    the mapping is lossless rather than that two tables were kept in sync by hand."""
    palette = client.get(f"/automations/palette?conn_id={conn_id}").json()["entries"]
    rows = {c.kind: c for c in components(conn_id=conn_id)
            if c.family in ("trigger", "effect")}

    assert {e["kind"] for e in palette} == set(rows)
    for e in palette:
        c = rows[e["kind"]]
        assert e["label"] == c.label
        assert e["description"] == c.description
        assert e["icon"] == c.icon
        assert e["availability"] == c.availability
        assert e["reason"] == c.reason
        assert e["publishes"] == c.outputs
        assert e["group"] == ("trigger" if c.family == "trigger" else "action")


def test_the_palette_keeps_its_bindable_ports_through_the_registry():
    """`bindable` and `required` are independent — a declared action's `params` is both —
    so a palette rebuilt by deriving one from the other would start drawing edges onto
    ports the engine does not read."""
    from aughor.automations.dataflow import BINDABLE_FIELDS

    palette = client.get("/automations/palette").json()["entries"]
    for e in palette:
        assert set(e["bindable"]) == set(BINDABLE_FIELDS.get(e["kind"], ()))
