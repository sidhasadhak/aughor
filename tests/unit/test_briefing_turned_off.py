"""A schema turned off has no Briefing (`ontology.visibility.briefing_off`).

Measured on LuxExperience, 2026-10-11: all three schemas of the Postgres connection were turned off for analysis, and a
rebuilt standing Briefing still synthesised a narrative from the findings made before — the re-validation set aside
the ones it re-ran, and the rest stayed. Off means off: the read and the build say the schema is off, re-validate and
write nothing; a scheduled send says why it was not sent; and the connection read whole leaves an off schema out.
"""
from __future__ import annotations

import uuid

import pytest

from aughor.ontology import visibility as V
from aughor.ontology.visibility import SCHEMA_WIDE, briefing_off, declare_exclusion


def _conn() -> str:
    return f"off-{uuid.uuid4().hex[:8]}"


def test_a_schema_turned_off_whole_has_no_briefing_and_a_table_alone_leaves_it_on():
    conn = _conn()
    assert briefing_off(conn, "luxexperience") is None
    declare_exclusion(conn, "luxexperience", "etl_load_log", "system_table", declared_by="amit")
    assert briefing_off(conn, "luxexperience") is None                    # one table off: the schema still briefs
    declare_exclusion(conn, "gold_finance", SCHEMA_WIDE, "out_of_domain", declared_by="amit")
    off = briefing_off(conn, "gold_finance")
    assert off == {"schemas": ["gold_finance"], "reason": "out_of_domain", "declared_by": "amit",
                   "said": "gold_finance is turned off for analysis, so no Briefing is written for it."}
    assert briefing_off(conn, "luxexperience") is None


def test_a_connection_read_whole_is_off_only_when_every_schema_is():
    conn = _conn()
    asked: list = []

    def schemas():
        asked.append(1)
        return ["gold_finance", "luxexperience"]

    assert briefing_off(conn, None, schemas=schemas) is None and asked == []   # nothing off: no warehouse read
    declare_exclusion(conn, "gold_finance", SCHEMA_WIDE, "out_of_domain", declared_by="amit")
    assert briefing_off(conn, None, schemas=schemas) is None                    # one of two
    declare_exclusion(conn, "luxexperience", SCHEMA_WIDE, "other", declared_by="sam")
    off = briefing_off(conn, None, schemas=schemas)
    assert off["schemas"] == ["gold_finance", "luxexperience"] and off["declared_by"] == "amit, sam"
    assert off["said"].startswith("Every schema of this connection is turned off")
    assert briefing_off(conn, None, schemas=lambda: []) is None                 # schemas unread: no claim


def test_the_connection_read_whole_leaves_an_off_schemas_findings_out(tmp_path, monkeypatch):
    from aughor.explorer import store
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    conn = _conn()
    for sch, words in (("gold_finance", "12 loads failed"), ("luxexperience", "Conversion is 31%")):
        store.save(f"{conn}__{sch}", {**store._empty(), store.FINDINGS: [
            {"id": f"{sch}:pinned__0", "domain": "Key Questions", "finding": words, "sql": "SELECT 1"}]})
    read = lambda: sorted(f["finding"] for items in store.get_aggregate_domain_findings(conn).values() for f in items)
    assert read() == ["12 loads failed", "Conversion is 31%"]
    declare_exclusion(conn, "gold_finance", SCHEMA_WIDE, "out_of_domain")
    assert read() == ["Conversion is 31%"]


@pytest.fixture
def briefing_route(monkeypatch):
    from aughor.routers import exploration as ex
    monkeypatch.setattr("aughor.routers._shared.canonical_schema", lambda c, s: s)
    monkeypatch.setattr("aughor.routers._shared.schemas_of_connection", lambda c: ["gold_finance"])

    def _never(*a, **k):
        raise AssertionError("an off schema's Briefing re-validated, measured or wrote something")

    monkeypatch.setattr("aughor.knowledge.briefing.get_briefing", _never)
    monkeypatch.setattr("aughor.explorer.revalidate_live.revalidate_for_briefing", _never)
    return ex


def test_building_or_reading_an_off_schemas_briefing_says_it_is_off(briefing_route):
    ex, conn = briefing_route, _conn()
    declare_exclusion(conn, "gold_finance", SCHEMA_WIDE, "out_of_domain", declared_by="amit")
    for schema, scope in (("gold_finance", f"{conn}:gold_finance"), (None, conn)):
        out = ex.generate_briefing(conn, refresh=True, schema=schema)
        assert (out["available"], out["narrative"], out["citations"], out["scope_key"]) == (False, "", [], scope)
        assert out["off"]["reason"] == "out_of_domain"


def test_a_range_briefing_of_an_off_schema_is_read_as_off(briefing_route, monkeypatch):
    ex, conn = briefing_route, _conn()
    declare_exclusion(conn, "gold_finance", SCHEMA_WIDE, "other")
    spec = type("Spec", (), {"key": "yesterday"})()
    monkeypatch.setattr(ex, "_range_spec_or_refuse", lambda *a: spec)
    monkeypatch.setattr("aughor.briefing.ranges.range_block", lambda s: {"start": "2026-10-10", "end": "2026-10-10"})
    monkeypatch.setattr("aughor.knowledge.briefing.peek_entry",
                        lambda key: {"narrative": "from before", "period": {"start": "2026-10-10", "end": "2026-10-10"}})
    out = ex.read_briefing(conn, schema="gold_finance", preset="yesterday")
    assert out["off"]["schemas"] == ["gold_finance"] and out["available"] is False and "narrative" in out
    assert out["narrative"] == ""
    built = ex.generate_briefing(conn, schema="gold_finance", preset="yesterday")
    assert built["off"] and built["available"] is False


def test_a_subscription_to_an_off_schema_is_not_sent_and_says_why(monkeypatch):
    from aughor.briefing import delivery
    from aughor.briefing.models import BriefSubscription
    from aughor.knowledge import period_brief
    conn = _conn()
    declare_exclusion(conn, "gold_finance", SCHEMA_WIDE, "other")
    monkeypatch.setattr(period_brief, "refusal", lambda period: "")
    monkeypatch.setattr(delivery, "build_period_departure",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("built for an off schema")))
    sub = BriefSubscription(conn_id=conn, name="n", trigger_id="t", period="day", content="briefing",
                            schema_name="gold_finance")
    result: dict = {}
    delivery._deliver_period(sub, object(), result)
    assert result["error"] == "not sent — gold_finance is turned off for analysis, so no Briefing is written for it."
    assert delivery.preview_subscription(sub)["error"].startswith("gold_finance is turned off")
    assert V.briefing_off(conn, "luxexperience") is None
