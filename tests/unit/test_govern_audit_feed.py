"""Wave G3b — one category vocabulary over the audit sinks that already exist.

The carrying test is :func:`test_every_governance_kind_is_categorized` — the ratchet that
stops a sixth sink from appearing unlabelled, which is exactly how the five became
mutually unaware in the first place.
"""
from __future__ import annotations

import pytest

import pathlib

import aughor.govern.audit_categories
from aughor.govern.audit_categories import (
    AUDIT_TABLE_CATEGORY,
    CATEGORIES,
    GOVERNANCE_SHAPED_UNCATEGORIZED,
    KIND_CATEGORY,
    NON_GOVERNANCE_KINDS,
    AuditEvent,
    _summarize,
    category_for,
    feed,
    uncategorized_kinds,
)


# ── the vocabulary ──────────────────────────────────────────────────────────────────

def test_every_mapped_kind_lands_in_a_known_category():
    """A mapping to a category nobody can filter by is a mapping to nothing."""
    assert set(KIND_CATEGORY.values()) <= set(CATEGORIES)
    assert AUDIT_TABLE_CATEGORY in CATEGORIES


def _emitted_kinds_in_tree() -> set[str]:
    """Every event kind `aughor/` emits, discovered by parsing it.

    Resolves module-level string constants as well as literals, because the guardrail
    sink emits `EVENT_KIND` rather than `"guardrail"` — a scanner that saw only literals
    would miss it and call the omission a clean bill of health.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "aughor"
    kinds: set[str] = set()
    for f in root.rglob("*.py"):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        consts = {
            n.targets[0].id: n.value.value
            for n in tree.body
            if isinstance(n, ast.Assign) and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
        }
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "emit" and n.args):
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    kinds.add(a.value)
                elif isinstance(a, ast.Name) and a.id in consts:
                    kinds.add(consts[a.id])
    return kinds


def test_the_scanner_finds_the_kinds_it_exists_to_find():
    """The ratchet's own premise, checked. A scanner that silently matched nothing would
    make the assertion below vacuous — a passing test proving only that zero is a subset
    of everything, which is the failure this file has already shipped once."""
    found = _emitted_kinds_in_tree()
    assert len(found) > 20, f"scanner found only {len(found)} kinds — it stopped matching"
    # One literal and one resolved through a module-level constant.
    assert "chat.feedback" in found
    assert "guardrail" in found, "constant resolution regressed — EVENT_KIND went unseen"


def test_every_governance_kind_is_categorized():
    """The ratchet. Five sinks record governance events and none knew about the others;
    a sixth arriving uncategorized is how that happens again.

    DISCOVERED, not listed. The previous version of this test hand-wrote the emitted set
    and asserted it against the hand-written KIND_CATEGORY — two halves of one edit, so a
    kind nobody remembered was missing from both and the assertion passed anyway. It stayed
    green while `chat.feedback` and `trace.feedback` went uncategorized from the day they
    shipped. A guard whose population is supplied by the same hand as its expectation is
    not a guard, and this one now fails CLOSED: a new kind is unknown until someone
    categorizes it or declares it non-governance.
    """
    unknown = (_emitted_kinds_in_tree()
               - set(KIND_CATEGORY)
               - NON_GOVERNANCE_KINDS
               - GOVERNANCE_SHAPED_UNCATEGORIZED)
    assert unknown == set(), (
        f"undeclared event kind(s): {sorted(unknown)} — add each to KIND_CATEGORY (with a "
        "sink in _SINKS, or the feed still renders nothing), or to NON_GOVERNANCE_KINDS if "
        "it is operational telemetry. Deciding is the point; defaulting is what broke this.")


def test_every_categorized_kind_has_a_sink_that_reads_it():
    """`feed` walks _SINKS, never KIND_CATEGORY, so a mapping entry on its own renders
    nothing. Two parallel hand-maintained lists is exactly the shape that let the audit
    feed's own timestamps be read from a column that did not exist — assert they agree
    instead of trusting that whoever edited one edited the other."""
    import re

    src = (pathlib.Path(aughor.govern.audit_categories.__file__)).read_text()
    sinks_block = src.split("_SINKS: list[")[1].split("]\n")[0]
    read_by_sink = set(re.findall(r'_from_ledger\("([^"]+)"', sinks_block))
    # `llm_call` and the audit table ride dedicated readers, not `_from_ledger`.
    mapped = set(KIND_CATEGORY) - {"llm_call"}
    assert mapped <= read_by_sink, (
        f"categorized but unreadable: {sorted(mapped - read_by_sink)} — KIND_CATEGORY "
        "claims the kind, no sink reads it, so the feed shows nothing")


def test_an_unmapped_kind_reports_itself():
    assert uncategorized_kinds({"brand.new.sink"}) == ["brand.new.sink"]
    assert category_for("brand.new.sink") is None


def test_category_lookup():
    assert category_for("govern.tag") == "governance_change"
    assert category_for("metric.governance") == "governance_change"
    assert category_for("action.approval") == "action_decision"
    assert category_for("llm_call") == "model_call"


# ── summaries are reader-facing, not payload dumps ──────────────────────────────────

def test_action_decision_summary_names_the_decision():
    s = _summarize("action.approval",
                   {"decision": "blocked", "action": "connection.delete", "scope": "c1"})
    assert "blocked" in s and "connection.delete" in s and "c1" in s


def test_tag_set_summary_shows_the_value_and_clear_does_not():
    assert "=restricted" in _summarize(
        "govern.tag", {"action": "set", "key": "tier", "value": "restricted",
                       "securable": "table:c.s.t"})
    assert "=" not in _summarize(
        "govern.tag", {"action": "clear", "key": "tier", "securable": "table:c.s.t"})


def test_metric_transition_summary_shows_the_move():
    s = _summarize("metric.governance",
                   {"action": "approve", "metric": "gmv", "from": "proposed",
                    "to": "approved"})
    assert "gmv" in s and "proposed" in s and "approved" in s


def test_an_unknown_kind_summarizes_as_itself_rather_than_crashing():
    assert _summarize("nope", {}) == "nope"


# ── the feed ────────────────────────────────────────────────────────────────────────

def test_an_unknown_category_raises_rather_than_returning_empty():
    """'No events' and 'that category does not exist' are different answers, and only
    one of them is actionable."""
    with pytest.raises(ValueError, match="unknown audit category"):
        feed(category="not_a_category")


def test_each_known_category_is_queryable():
    for category in CATEGORIES:
        events = feed(category=category, limit=5)
        assert isinstance(events, list)
        assert all(e.category == category for e in events)


def test_the_feed_is_newest_first_and_respects_the_limit(monkeypatch):
    import aughor.govern.audit_categories as AC

    made = [AuditEvent(category="model_call", kind="llm_call", at=f"2026-07-{d:02d}")
            for d in (10, 28, 19)]
    monkeypatch.setattr(AC, "_SINKS", [("model_call", lambda n: list(made))])
    out = AC.feed(limit=2)
    assert [e.at for e in out] == ["2026-07-28", "2026-07-19"]


def test_an_unreadable_sink_degrades_the_feed_instead_of_failing_it(monkeypatch):
    """One broken sink must not blank the rest.

    Written first with a raising sink and it FAILED: the tolerate lived inside the reader
    functions, so a sink that raised before reaching one propagated and emptied the whole
    feed — a governance surface returning nothing, indistinguishable from a quiet week.
    `feed` now guards each sink read itself.
    """
    import aughor.govern.audit_categories as AC

    def _broken(_n):
        raise RuntimeError("sink is down")

    good = [AuditEvent(category="model_call", kind="llm_call", at="2026-07-28")]
    monkeypatch.setattr(AC, "_SINKS", [
        ("governance_change", _broken),
        ("model_call", lambda n: list(good)),
    ])
    out = AC.feed()
    assert [e.kind for e in out] == ["llm_call"]


def test_events_serialize_for_a_response():
    e = AuditEvent(category="governance_change", kind="govern.tag", at="2026-07-28",
                   actor="alice", summary="set tier=restricted on table:c.s.t")
    d = e.to_dict()
    assert d["category"] == "governance_change" and d["actor"] == "alice"
    assert d["detail"] == {}


# ── the routes are declared in the auditable policy table ───────────────────────────

def test_the_governance_routes_are_in_the_rbac_policy():
    """`policy.py` is the auditable map of the whole surface — a route that gated itself
    with a decorator would be invisible to anyone reading it."""
    from aughor.rbac.policy import POLICY

    for route in ("/usage", "/usage/cost-sql", "/audit/feed"):
        assert ("GET", route) in POLICY, f"{route} is not declared in the RBAC policy table"


def test_the_governance_router_is_registered():
    from aughor.api import app

    paths = {r.path for r in app.routes}
    assert {"/usage", "/usage/cost-sql", "/audit/feed"} <= paths


def test_model_calls_are_read_from_the_session_log_not_the_generic_event_path():
    """Regression: the llm_call reader was pointed at `Ledger.events`, which returns
    NOTHING for that kind — the session log is a separate query path.

    Every other test here builds its own events, so a reader aimed at an empty path
    passed them all while reporting "no model calls" on a system making them constantly.
    Found by probing the live Ledger, and pinned here by asserting the SOURCE rather than
    a count, since a fixture-free environment legitimately has zero rows.
    """
    import inspect

    import aughor.govern.audit_categories as AC

    src = inspect.getsource(AC._from_session_log)
    assert "session_events" in src
    sinks = {cat: fn for cat, fn in AC._SINKS}
    assert sinks["model_call"] is AC._from_session_log


# ── the timestamp every sink was dropping ───────────────────────────────────────

def test_every_sink_reports_a_real_timestamp():
    """Measured on the live feed: **505 of 505 events had `at == ""`**.

    Each of the three sinks read a column name its table does not have — the ledger and
    the session log call it `at`, the audit table calls it `ts`, and the code asked for
    `created_at`/`timestamp`. Nothing raised, because `.get()` on a missing key returns
    None and the code coalesced it to "".

    That is not a cosmetic defect. `feed()` sorts on this field, so "newest first" was a
    claim about hundreds of identical empty strings; and Arc VA's decision ③ requires the
    audit trail to answer *who, whose trace, and WHEN* — the third of which was blank on
    every row.
    """
    import aughor.govern.audit_categories as ac

    import inspect

    # The ledger sink, driven with a row keyed the way the events table keys it.
    orig_ledger = ac._ledger_events
    ac._ledger_events = lambda kind, limit: [
        {"at": "2026-08-23T10:00:00Z", "org_id": "default",
         "payload": {"read_by": "admin-7", "trace_id": "t1"}}]
    try:
        (ev,) = ac._from_ledger("trace.payload_access", 10)
        assert ev.at == "2026-08-23T10:00:00Z", (
            f"the ledger sink reported at={ev.at!r} — it is reading a column the events "
            f"table does not have")
    finally:
        ac._ledger_events = orig_ledger

    # The other two readers open real stores, so pin the COLUMN each one asks for. The
    # bug was never in the logic; it was one wrong key in each mapping.
    assert '"ts"' in inspect.getsource(ac._from_audit_table), \
        "the audit-table sink must read `ts` — that is what the audit_log column is called"
    assert '"at"' in inspect.getsource(ac._from_session_log), \
        "the session-log sink must read `at` — that is what the session_events column is called"
