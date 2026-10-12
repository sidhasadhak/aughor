"""The Briefing's desk: Trends, Gaps and Decide come from what the platform already recorded — and say
so when a store cannot be read. Fixtures are shaped on theLook's live Record (2026-10-12): three runs
of one question that answered $2.10M, $608.5K and $610.2K; a delivery question parked for data; a
process watch's proposed run; a metric approved with no formula; one proposed."""
from __future__ import annotations

import datetime as _dt

import pytest

from aughor.briefing import desk as D
from aughor.record.claims import About, Claim, Statement
from aughor.record.inquiry import Inquiry, OpenItem, RunNote

NOW = _dt.datetime(2026, 10, 12, 12, 0, tzinfo=_dt.timezone.utc)


def claim(kind, text, *, days=3, **extra):
    return Claim(kind=kind, about=About(kind="connection", key="c1"), statement=Statement(text=text), tier="measured",
                 status="Provisional", as_of="2026-10-05", recorded_at=(NOW - _dt.timedelta(days=days)).isoformat(),
                 extra=extra, id=f"id-{abs(hash(text)) % 10**6}")


REVENUE_2025 = Inquiry(question="What was revenue from completed orders in 2025?", connection_id="c1", id="q-rev", state="waiting",
                       runs=[RunNote(run="r1", verdict="answered", why="Revenue from Completed Orders in 2025: Totaling 2,098,609.88 USD"),
                             RunNote(run="r2", verdict="answered", why="2025 Revenue from Completed Orders Totalled 608,504.54 Across All Traffic Sources"),
                             RunNote(run="r3", verdict="answered", why="Completed Order Revenue for 2025 Totalled 610,184.21 USD")],
                       open=[OpenItem(what="no comparison to 2024")], next_check="2026-11-07")
DELAYS = Inquiry(question="What is causing delivery delays?", connection_id="c1", id="q-del", state="waiting",
                 runs=[RunNote(run="r4", verdict="answered", why="Delivery breach rate remains stable at 10.1% across all segments")],
                 open=[OpenItem(what="Lack of granular carrier-level data.")], waiting_for="data that would settle the open items",
                 next_check="2026-11-08")
PROPOSED = Inquiry(question="Why did the delivered stage of order_fulfilment slowed: p90 4.0 → 5.0 days?", connection_id="c1",
                   id="q-proc", state="open", opened_by="process:order_fulfilment",
                   extra={"proposed_run": {"kind": "investigation", "question": "Why did the delivered stage slow?"}})


class M:
    def __init__(self, name, status, sql="SELECT 1", label="", tables=None, proposed_by="", connection="c1", time_column="t.created_at"):
        self.name, self.status, self.sql, self.label = name, status, sql, label
        self.tables, self.proposed_by, self.connection, self.time_column = tables or [], proposed_by, connection, time_column


METRICS = [M("revenue", "approved", label="Revenue"),
           M("cart_to_order_conversion_rate", "approved", sql="", label="Cart-to-order conversion rate"),
           M("average_delivery_time", "proposed", label="Average Delivery Time", tables=["orders"], proposed_by="amitkamlapure")]


def test_an_answer_states_its_largest_figure_and_a_bare_year_is_not_one():
    assert D.answer_figure("Revenue from Completed Orders in 2025: Totaling 2,098,609.88 USD") == 2098609.88
    assert D.answer_figure("In 2025 nothing was sold") is None
    assert D.answer_figure("stable at 10.1% across 2019-2026") == 10.1
    assert D.answer_figure("revenue reached $396.6K in 3 weeks") == 396600.0
    assert D.answer_figure("2.10 million in total") == 2100000.0


def test_three_runs_that_disagree_are_a_gap_and_agreeing_runs_are_not():
    runs = [r.model_dump() for r in REVENUE_2025.runs]
    assert D.disagreeing_answers(runs) == [608504.54, 610184.21, 2098609.88]
    same = [{"verdict": "answered", "why": "total 610,184.21"}, {"verdict": "answered", "why": "total 610.2K"}]
    assert D.disagreeing_answers(same) == []                         # 610.2K is 610,184.21 rounded: one answer
    refused = [{"verdict": "refused", "why": "total 1,000"}, {"verdict": "answered", "why": "total 2,000"}]
    assert D.disagreeing_answers(refused) == []                      # a refusal states no answer


def test_a_scheduled_run_answering_a_new_day_each_time_is_not_a_disagreement():
    daily = [{"verdict": "answered", "why": "Revenue declined to $14,200.10 on September 28, 2026"},
             {"verdict": "answered", "why": "Revenue increased to $17,113.56 on September 30, 2026"}]
    assert D.disagreeing_answers(daily) == []


def test_gaps_say_the_disagreement_the_parked_question_the_missing_formula_and_the_lag():
    out = D.gaps([REVENUE_2025, DELAYS, PROPOSED], METRICS, {"lag_days": 29, "key": "range:yesterday",
                                                             "still_moving": ["events", "orders", "users", "products", "order_items"]})
    kinds = [g["kind"] for g in out]
    assert kinds == ["disagree", "unmeasured", "waiting", "lag"]
    assert out[0]["text"].startswith("3 runs gave 3 different answers: $608.5K, $610.2K and $2.10M")
    assert out[0]["action"] == {"verb": "Settle it", "kind": "inquiry", "ref": "q-rev"}
    assert out[2]["title"] == "Still open: What is causing delivery delays?" and "until 2026-11-08" in out[2]["text"]
    assert out[1]["title"] == "Cart-to-order conversion rate isn't measured"
    assert out[3]["title"] == "The newest settled day is 29 days old" and "5 tables" in out[3]["text"]


def test_a_disagreeing_question_is_said_once_not_also_as_parked():
    out = D.gaps([REVENUE_2025], [], None)
    assert [g["kind"] for g in out] == ["disagree"]


def test_a_question_written_by_code_is_never_a_story():
    sched = Inquiry(question="[Scheduled-run context — written by code, not inferred]\nThis is a scheduled daily run",
                    connection_id="c1", id="q-s", state="waiting", open=[OpenItem(what="x")])
    assert D.gaps([sched], [], None) == [] and D.decide([sched], []) == []


def test_an_investigations_sub_finding_is_its_evidence_not_a_trend():
    cs = [claim("finding", "Revenue Contribution by Product Department: The growth is concentrated in Men.", days=1),
          claim("finding", "Delivery Breach Rate Trend: no consistent trend.", days=1)]
    assert [t["title"] for t in D.trends(cs, NOW)] == ["Delivery Breach Rate Trend"]


def test_a_short_lag_is_not_news():
    assert D.gaps([], [], {"lag_days": 2}) == []


def test_decide_holds_the_proposed_run_and_the_proposed_metric():
    out = D.decide([REVENUE_2025, DELAYS, PROPOSED], METRICS)
    assert [d["kind"] for d in out] == ["proposed_run", "proposed_metric"]
    assert out[0]["title"] == "Why did the delivered stage slow?" and "order fulfilment watch" in out[0]["text"]
    assert out[1]["title"] == "Average Delivery Time is waiting as a metric" and "from orders" in out[1]["text"]
    ran = PROPOSED.model_copy(update={"runs": [RunNote(run="r9", verdict="answered", why="x")]})
    assert D.decide([ran], []) == []                                 # run already: nothing to decide


def test_trends_are_recent_answers_and_trend_findings_newest_first():
    cs = [claim("observation", "August 2026 Revenue Increased by 13.2% Driven by Search Traffic", days=7,
                investigation_id="inv1", question="Why did Revenue change by +13% for August 2026?"),
          claim("finding", "Inventory Sell-Through Rate Trend: grew from about 7% to over 70%.", days=4),
          claim("finding", "Delivery Breach Rate by Country: uniform at 9-10%.", days=2),           # not a trend
          claim("observation", "Revenue 2025 Totalled 610,184.21 USD", days=3),                      # not an answer's report
          claim("finding", "Order Volume Trend: climbed.", days=45),                               # booked too long ago
          claim("finding", "Monthly order volume climbed from 5 in January 2019 to 309 in August 2020.", days=1),  # history
          claim("observation", "Inventory Sell-Through Rate Trend holds steady", days=5, investigation_id="inv2", question="q"),  # same subject
          claim("observation", "2025 Revenue Totalled 608,504.54", days=1, investigation_id="inv3", question="q")]   # a total, not a move
    out = D.trends(cs, NOW)
    assert [t["title"] for t in out] == ["August 2026 Revenue Increased by 13.2% Driven by Search Traffic",
                                         "Inventory Sell-Through Rate Trend"]
    assert out[1]["text"] == "grew from about 7% to over 70%."
    assert out[0]["source"]["label"] == "Investigation · Why did Revenue change by +13% for August 2026?"


def test_a_column_holds_four_and_counts_the_rest():
    col = D._column([{"i": n} for n in range(6)])
    assert len(col["items"]) == 4 and col["more"] == 2


def test_a_store_that_cannot_be_read_is_said_and_the_other_columns_still_print(monkeypatch):
    from aughor.record import claims as C
    from aughor.record import inquiry as I
    from aughor.semantic import metrics as SM

    def boom(**_):
        raise RuntimeError("ledger locked")
    monkeypatch.setattr(C, "list_claims", boom)
    monkeypatch.setattr(I, "list_inquiries", lambda **_: [REVENUE_2025, PROPOSED])
    monkeypatch.setattr(SM, "list_metrics", lambda **_: METRICS)
    out = D.desk("c1", now=NOW)
    assert out["trends"] is None and out["unread"] == {"claims": "claims could not be read just now"}
    assert [g["kind"] for g in out["gaps"]["items"]] == ["disagree", "unmeasured"]
    assert [d["kind"] for d in out["decide"]["items"]] == ["proposed_run", "proposed_metric"]


def test_another_connections_metric_never_reaches_this_desk(monkeypatch):
    from aughor.record import claims as C
    from aughor.record import inquiry as I
    from aughor.semantic import metrics as SM
    monkeypatch.setattr(C, "list_claims", lambda **_: [])
    monkeypatch.setattr(I, "list_inquiries", lambda **_: [])
    monkeypatch.setattr(SM, "list_metrics", lambda **_: [M("global_x", "approved", sql="", connection="")])
    assert D.desk("c1", now=NOW)["gaps"]["items"] == []


@pytest.mark.parametrize("v,money,want", [(2098609.88, True, "$2.10M"), (608504.54, True, "$608.5K"),
                                          (10.1, False, "10.1"), (4.0, False, "4")])
def test_figures_are_said_humanised(v, money, want):
    assert D.human(v, money) == want


def test_approved_metrics_with_no_date_are_a_gap_said_once_with_their_names():
    """LuxExperience, 2026-10-12: four approved metrics read tables with no recognised date, so every
    period edition left them out while the Gaps column said nothing was missing."""
    ms = [M("aov", "approved", label="Average Order Value"),
          M("gm", "approved", label="Gross Margin %", time_column=""),
          M("rr", "approved", label="Item Return Rate", time_column=None),
          M("blank", "approved", sql="", label="No formula", time_column="")]       # said as unmeasured instead
    out = D.gaps([], ms, None)
    undated = [g for g in out if g["kind"] == "undated"]
    assert len(undated) == 1
    assert undated[0]["title"] == "2 approved metrics can't be measured for a period"
    assert undated[0]["text"].startswith("Gross Margin %, Item Return Rate: no date column is set")
    assert undated[0]["action"] == {"verb": "Set dates", "kind": "metric", "ref": "gm"}
    assert [g["kind"] for g in out] == ["unmeasured", "undated"]


def test_an_unlabelled_finding_that_mentions_a_trend_is_not_one():
    cs = [claim("finding", "Summed amount is highest for 2026-06-30 at 27441.73; should not be read as a performance trend.", days=1)]
    assert D.trends(cs, NOW) == []
