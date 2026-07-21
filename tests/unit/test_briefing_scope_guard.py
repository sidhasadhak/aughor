"""The briefing's scope plane — fail-closed schema filtering + held-back grouping.

Two independent defects produced one screenshot: a NETFLIX-headed brief whose synthesis prose
and 15 trust-gate reasons belonged to a DIFFERENT schema (luxexperience), with the same reason
repeated 7× and 6×.

* Cross-scope leak — a schema view that falls back to the CONNECTION-level exploration state
  must prove each finding belongs to the schema. When the schema's table set can't be resolved
  the filter used to fail OPEN and return everything, i.e. another schema's findings under this
  schema's header. It now fails CLOSED, and the briefing response stamps the scope it was built
  for so the client can refuse a mismatch.
* Reason spam — a trust-gate reason derives from the SQL *idiom*, so N findings sharing one bad
  idiom emit N byte-identical strings. They are grouped, with the total preserved.
"""
from __future__ import annotations

import pytest

from aughor.knowledge.briefing import group_held_back
from aughor.routers.exploration import (
    SchemaScopeUnavailable,
    _filter_by_schema,
    _filter_findings_by_schema,
)

# ── Fail-closed schema filtering ──────────────────────────────────────────────

# Two findings, each unambiguously in ONE schema (both reference a `orders` table, so only the
# qualified form can tell them apart — the exact shape that made the leak invisible).
DOMAIN_DATA = {
    "Revenue": [
        {"id": "a", "finding": "womenswear is the largest cost driver",
         "sql": "SELECT SUM(cost) FROM luxexperience.orders"},
        {"id": "b", "finding": "mature-rated content is 45% of the library",
         "sql": "SELECT COUNT(*) FROM netflix.orders"},
    ],
}


def _no_table_set(monkeypatch):
    """Make the schema's table set unresolvable — the DB hiccup that used to fail open."""
    monkeypatch.setattr(
        "aughor.routers.exploration._schema_table_set", lambda conn_id, schema: None
    )


def test_filter_by_schema_fails_closed_when_table_set_unresolvable(monkeypatch):
    _no_table_set(monkeypatch)
    with pytest.raises(SchemaScopeUnavailable) as exc:
        _filter_by_schema(DOMAIN_DATA, "workspace", "netflix")
    assert "netflix" in str(exc.value)
    assert exc.value.schema == "netflix"


def test_findings_filter_fails_closed_when_table_set_unresolvable(monkeypatch):
    _no_table_set(monkeypatch)
    with pytest.raises(SchemaScopeUnavailable):
        _filter_findings_by_schema({"insights": [], "null_meanings": {}}, "workspace", "netflix")


def test_no_schema_requested_is_not_a_failure(monkeypatch):
    """`schema=None` means "no scope asked for" — pass through, never raise."""
    _no_table_set(monkeypatch)
    assert _filter_by_schema(DOMAIN_DATA, "workspace", None) == DOMAIN_DATA
    payload = {"insights": [{"id": "a"}], "null_meanings": {}}
    assert _filter_findings_by_schema(payload, "workspace", None) == payload


def test_resolvable_schema_still_filters_by_qualified_name(monkeypatch):
    """The happy path must keep discriminating same-named tables across schemas."""
    monkeypatch.setattr(
        "aughor.routers.exploration._schema_table_set", lambda conn_id, schema: {"orders"}
    )
    out = _filter_by_schema(DOMAIN_DATA, "workspace", "netflix")
    kept = [i["id"] for i in out["Revenue"]]
    assert kept == ["b"], "only the netflix-qualified finding may survive a netflix scope"


# ── Held-back grouping ────────────────────────────────────────────────────────

RATE = "AVG('return_rate') averages an already-computed rate"
TEXT = "SUM() over the text column 'signup_fy' (VARCHAR)"


def test_group_held_back_collapses_identical_reasons_and_keeps_the_total():
    # The exact distribution from the reported brief: 6× + 7× + 2 singletons = 15.
    held = (
        [{"finding": f"f{i}", "domain": "Returns", "severity": "implausible", "reason": RATE}
         for i in range(6)]
        + [{"finding": f"g{i}", "domain": "Growth", "severity": "implausible", "reason": TEXT}
           for i in range(7)]
        + [{"finding": "h", "domain": "Duty", "severity": "implausible", "reason": "duty_rate"},
           {"finding": "i", "domain": "Reserve", "severity": "confound", "reason": "reservation"}]
    )
    groups = group_held_back(held)

    assert len(groups) == 4, "one line per DISTINCT reason"
    assert sum(g["count"] for g in groups) == len(held) == 15, "no signal is silently dropped"
    assert [g["count"] for g in groups] == [7, 6, 1, 1], "most frequent first"
    assert groups[0]["reason"] == TEXT
    assert groups[0]["domains"] == ["Growth"]


def test_group_held_back_separates_severities_with_the_same_reason():
    held = [
        {"finding": "a", "domain": "D", "severity": "implausible", "reason": RATE},
        {"finding": "b", "domain": "D", "severity": "confound", "reason": RATE},
    ]
    assert len(group_held_back(held)) == 2


def test_group_held_back_accumulates_distinct_domains():
    held = [
        {"finding": "a", "domain": "Returns", "severity": "implausible", "reason": RATE},
        {"finding": "b", "domain": "Growth", "severity": "implausible", "reason": RATE},
        {"finding": "c", "domain": "Returns", "severity": "implausible", "reason": RATE},
    ]
    (group,) = group_held_back(held)
    assert group["count"] == 3
    assert group["domains"] == ["Returns", "Growth"], "each domain once, in first-seen order"


def test_group_held_back_empty_is_empty():
    assert group_held_back([]) == []


# ── The response stamps the scope it was built FOR ────────────────────────────
#
# Without this the client cannot tell a brief for `workspace:netflix` from one for
# `workspace:luxexperience` — a retained narrative from the previous schema is
# structurally undetectable, which is exactly what shipped to the screenshot.

def test_briefing_stamps_scope_key_when_unavailable(monkeypatch):
    from aughor.routers import exploration as ex

    monkeypatch.setattr(ex, "_domain_insights_for", lambda c, s: {})
    monkeypatch.setattr(ex, "_needs_filter", lambda c, s: False)

    out = ex.generate_briefing("workspace", refresh=False, schema="netflix")
    assert out["available"] is False
    assert out["scope_key"] == "workspace:netflix"


def test_briefing_stamps_scope_key_on_the_generated_brief(monkeypatch):
    from aughor.routers import exploration as ex

    monkeypatch.setattr(ex, "_domain_insights_for", lambda c, s: {"D": [{"id": "a"}]})
    monkeypatch.setattr(ex, "_needs_filter", lambda c, s: False)
    monkeypatch.setattr(ex, "_load_state", lambda c, s: {})
    monkeypatch.setattr(ex, "_load_business_profile", lambda c, s: None)
    monkeypatch.setattr(ex, "_connection_col_types", lambda c: {})
    monkeypatch.setattr(ex, "_metric_moves_provider", lambda c, p: None)
    monkeypatch.setattr("aughor.knowledge.patterns.get_patterns", lambda *a, **k: [])
    monkeypatch.setattr(
        "aughor.knowledge.briefing.get_briefing",
        lambda **kw: {"narrative": "n", "headline_theme": "t", "citations": [],
                      "held_back": [], "generated_at": "now"},
    )

    out = ex.generate_briefing("workspace", refresh=False, schema="netflix")
    assert out["available"] is True
    assert out["scope_key"] == "workspace:netflix"


def test_briefing_scope_key_is_bare_connection_when_no_schema(monkeypatch):
    """Must mirror the client's `narrativeScope` exactly — `<conn>`, not `<conn>:`."""
    from aughor.routers import exploration as ex

    monkeypatch.setattr(ex, "_domain_insights_for", lambda c, s: {})
    monkeypatch.setattr(ex, "_needs_filter", lambda c, s: False)

    assert ex.generate_briefing("workspace", refresh=False, schema=None)["scope_key"] == "workspace"
