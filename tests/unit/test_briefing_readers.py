"""Arc BG-4 (ROADMAP §3.66) — readers: who a Briefing is written for.

A reader is one of the organisation's function groups, or the organisation. A person reads as their own
setting, else their first group, else the organisation. A reader is added to the guide from a proposal
(no model) or from plain words (one call, which may add checks — each measured before it is kept). A
subscription sends the edition written for its reader.
"""
from __future__ import annotations

import contextlib
from datetime import date

import duckdb
import pytest

from aughor.briefing import guide as G
from aughor.briefing import ranges

OCT29 = date(2026, 10, 29)


@pytest.fixture
def groups():
    from aughor.rbac.groups import add_member, upsert_group
    upsert_group("default", "finance", "Finance", "money")
    upsert_group("default", "product", "Product", "the storefront")
    add_member("default", "product", "user:dana")
    return ["finance", "product"]


def test_the_reader_setting_names_a_function_group_or_the_organisation(groups):
    from aughor.db.user_prefs import ALLOWED_KEYS
    check = ALLOWED_KEYS["briefing_reader"][0]
    assert check("finance") == "finance"
    assert check("") == ""
    with pytest.raises(ValueError):
        check("marketing")


def test_a_person_reads_as_their_setting_else_their_group_else_the_organisation(groups):
    from aughor.db.user_prefs import set_preference
    assert G.default_reader("user:dana") == "product"            # their first function group
    assert G.default_reader("user:nobody") == ""                  # no group: the organisation
    set_preference("briefing_reader", "finance")
    assert G.default_reader("user:dana") == "finance"             # their own choice wins
    set_preference("briefing_reader", "")
    assert G.default_reader("user:dana") == ""                    # an explicit "the organisation" too


def _guide():
    return G.BriefingGuide(
        checks=[G.Check(id="refunds", label="Refunds", sql="SUM(refund_eur)", tables=["returns"],
                        time_column="returns.return_date")],
        proposed_readers=[G.Reader(name="Product", watches="pages", check_ids=["refunds"])])


def test_a_proposed_reader_is_added_without_a_model(groups):
    G.save("readers_c1", None, _guide(), by="explorer")
    G.add_reader("readers_c1", None, group_id="product", name="Product", watches="pages", by="user:amit",
                 check_ids=["refunds", "ghost"], llm=object())         # any model call would fail
    guide, rev = G.working_copy("readers_c1", None)
    assert rev.by == "user:amit" and rev.state == "draft"
    assert [(r.group_id, r.check_ids) for r in guide.readers] == [("product", ["refunds"])]
    assert guide.proposed_readers == []                                # accepted, no longer proposed


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("""CREATE TABLE returns AS
        SELECT d::DATE AS return_date, 50.0 AS refund_eur, 'size_fit' AS reason
        FROM range(DATE '2026-08-01', DATE '2026-10-29', INTERVAL 1 DAY) t(d), range(4) k(i)""")
    yield c
    c.close()


def _run(con):
    def run(sql):
        try:
            cur = con.execute(sql)
            return [d[0] for d in cur.description], cur.fetchall(), None
        except Exception as exc:  # noqa: BLE001
            return [], [], str(exc)
    return run


class _LLM:
    def __init__(self, out):
        self.out, self.calls = out, 0

    def complete(self, *, system, user, response_model, temperature):
        self.calls += 1
        assert response_model is G._ReaderDraft and "pages and size returns" in user
        return self.out


def test_a_reader_from_plain_words_maps_to_checks_and_may_add_measured_ones(groups, con, monkeypatch):
    monkeypatch.setattr("aughor.business_profile.infer.gather_context", lambda c, s: ("schema", []))
    monkeypatch.setattr(ranges, "governed_metrics", lambda *a, **k: [])
    monkeypatch.setattr(ranges, "resolve_for", lambda *a, **k: ranges.resolve_range(
        "last_week", today=OCT29, lag_days=1, lag_source="learned"))
    G.save("readers_c2", None, _guide(), by="explorer")
    llm = _LLM(G._ReaderDraft(check_ids=["refunds"], new_checks=[
        G.Check(id="size_returns", label="Size returns", sql="COUNT(*)", tables=["returns"],
                filters=["reason = 'size_fit'"], time_column="returns.return_date"),
        G.Check(id="bad", label="Bad", sql="SUM(nope)", tables=["returns"], time_column="returns.return_date")]))
    G.add_reader("readers_c2", None, group_id="product", name="Product", watches="pages and size returns",
                 by="user:amit", llm=llm, runner=lambda: contextlib.nullcontext((_run(con), "duckdb")))
    guide, _ = G.working_copy("readers_c2", None)
    assert llm.calls == 1
    assert guide.reader("product").check_ids == ["refunds", "size_returns"]
    assert [c.id for c in guide.checks] == ["refunds", "size_returns"]   # the new check measured, kept
    assert [d.id for d in guide.dropped] == ["bad"]                       # the broken one said


def test_no_guide_no_reader(groups):
    with pytest.raises(LookupError):
        G.add_reader("none", None, group_id="finance", name="Finance", watches="", by="user:amit", check_ids=[])


def test_a_subscription_sends_the_edition_written_for_its_reader(monkeypatch):
    from aughor.briefing import delivery
    from aughor.briefing.compose import write as W
    from aughor.briefing.models import BriefSubscription
    from aughor.govern.departure import Measurement

    spec, _ = ranges.resolve_range("last_week", today=OCT29, lag_days=1, lag_source="learned")
    monkeypatch.setattr(ranges, "resolve_for", lambda *a, **k: (spec, ""))
    monkeypatch.setattr("aughor.knowledge.period_brief.scope_inputs", lambda *a, **k: ({}, None))
    monkeypatch.setattr(G, "current", lambda *a, **k: (G.BriefingGuide(), None))
    asked = {}

    def compose(conn_id, spec, **kw):
        asked.update(kw)
        return {"blocks": [{"type": "lead", "text": "Baskets far above usual."},
                           {"type": "figure", "text": "The average order sat outside its usual range."}],
                "period": ranges.range_block(spec)}

    monkeypatch.setattr(W, "compose", compose)
    monkeypatch.setattr(ranges, "fresh_measurement", lambda *a, **k: Measurement(
        source="test", values=[], measured_at="2026-10-29T00:00:00Z", as_of="2026-10-25"))
    out = delivery.build_period_departure(BriefSubscription(conn_id="readers_c3", name="Weekly", period="week",
                                                            reader="group:finance"))
    assert asked["reader_id"] == "finance"
    assert "Baskets far above usual" in out["markdown"]
