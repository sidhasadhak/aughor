"""PENDING 57, D-1 to D-3 — the decision loop turns honestly (docs/DECISION_LOOP_STUDY_2026-10-24.md).

Measured before building, 2026-10-24: the Record held 2 decisions, none with an expectation or an outcome; Home's
Decide sent the finding only as text in a note and "Not worth it" booked nothing; only a recommendation was ever
reviewed; and an outcome was judged against the metric's own history, which the Record's own calibration showed
missing above for revenue (5 of 8 windows) and units sold (7 of 8) — a do-nothing decision would be credited the trend.

What these hold, with the flag `record.decision_loop` on: a decision taken on a finding cites the finding's claim; not
acting is a decision; a recommendation keeps its report's other actions and says what was recommended, so an override
is countable; every due decision is reviewed once; a part of a metric that adds up is judged against the rest of its
group, so a trend the group shares is not credited (the placebo below); a whole metric whose own band drifts one way
says cannot tell; a review window with no rows says the data ended; another decision on the same metric in the same
weeks is named. And with it off, every door books exactly what it did.

The reviews run their SQL on a real DuckDB: a fake that returns a number would prove only the wording.
"""
from __future__ import annotations

import datetime as dt
import random
import statistics
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import duckdb
import pytest

from aughor.db.history import complete_investigation, create_investigation
from aughor.kernel.flags import flag_overrides
from aughor.playbook import outcomes as O
from aughor.record import byproducts as B
from aughor.record import decisions as D
from aughor.record import reviews as RV
from aughor.record import scenario as S
from aughor.record import writers as W
from aughor.routers import investigations as inv
from aughor.semantic.metric_time import adds_up
from aughor.semantic.metrics import MetricDefinition

DECIDED = dt.date(2026, 8, 1)
TODAY = dt.date(2026, 10, 15)
GROWTH = 0.03          # every category grows 3% a month together: the trend a do-nothing decision must not be credited
CATEGORIES = {"Jeans": 100.0, "Dresses": 160.0, "Outerwear": 120.0, "Shoes": 90.0}


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "_DEFAULT_PATH", tmp_path / "recommendation_outcomes.json")
    import aughor.settling.store as settling
    monkeypatch.setattr(settling, "learned_lag_days", lambda conn_id: 0)


@pytest.fixture
def on():
    with flag_overrides({"record.decision_loop": True}):
        yield


@pytest.fixture
def off():
    with flag_overrides({"record.decision_loop": False}):
        yield


def _conn() -> str:
    return "conn-" + uuid.uuid4().hex[:6]


def _shop(effect_on: str = "", effect: float = 0.0, ends: dt.date = dt.date(2026, 12, 31)):
    """A business whose categories all grow GROWTH a month; ``effect_on`` gets ``effect`` more after DECIDED."""
    con = duckdb.connect()
    con.execute("CREATE TABLE sales (day DATE, category VARCHAR, amount DOUBLE)")
    rows = []
    noise = random.Random(57)          # day-to-day noise, as real sales have: a band of zero width proves nothing
    day = dt.date(2025, 6, 1)
    while day <= ends:
        months = (day - dt.date(2025, 6, 1)).days / 30.4
        for cat, base in CATEGORIES.items():
            lift = 1 + effect if (cat == effect_on and day >= DECIDED) else 1
            rows.append((day, cat, round(base * (1 + GROWTH) ** months * lift * noise.uniform(0.9, 1.1), 4)))
        day += dt.timedelta(days=1)
    con.executemany("INSERT INTO sales VALUES (?, ?, ?)", rows)

    @contextmanager
    def runner(conn_id):
        def run_sql(sql):
            try:
                cur = con.execute(sql)
                return [d[0] for d in cur.description], cur.fetchall(), None
            except Exception as exc:  # noqa: BLE001
                return [], [], str(exc)
        yield run_sql, "duckdb"
    return runner


def _revenue(conn: str, **kw) -> MetricDefinition:
    fields = dict(name="revenue", connection=conn, label="Revenue", sql="SUM(amount)", tables=["sales"],
                  dimensions=["category"], status="approved", time_column="sales.day", time_kind="flow")
    fields.update(kw)
    return MetricDefinition(**fields)


@pytest.fixture
def metric(monkeypatch):
    holder = {}
    import aughor.semantic.metrics as M
    monkeypatch.setattr(M, "get_metric", lambda name, connection_id=None: holder.get(name))
    return holder


def _declare(conn: str, *, expectation=None, finding_id: str = "", decided: dt.date = DECIDED) -> D.Decision:
    did = B.declare_decision(question="Spend more on Jeans", chosen="spend more", options=["spend more", B.NOT_ACT],
                             connection_id=conn, decided_by="user:amit", decided_at=f"{decided.isoformat()}T09:00:00+00:00",
                             review_on=(decided + dt.timedelta(days=30)).isoformat(), expectation=expectation,
                             finding_id=finding_id)
    return D.get_decision(did)


def _finding(conn: str, fid: str = "synth__share__5", text: str = "Jeans run at a fifth of revenue",
             schema: str = "") -> str:
    out = W.book_explorer_finding(finding={"id": fid, "finding": text}, sql="SELECT 1", connection_id=conn,
                                  receipt_id="r-" + uuid.uuid4().hex[:6], schema_name=schema)
    assert out
    return out


# ── D-1 · booked in full where it is made ──────────────────────────────────────────────────

def test_a_decision_on_a_finding_cites_the_findings_claim(on):
    conn = _conn()
    cid = _finding(conn)
    d = _declare(conn, finding_id="synth__share__5")
    assert d.relied_on == [cid]
    assert [o.id for o in d.options] == ["spend more", B.NOT_ACT]
    assert d.extra["finding_id"] == "synth__share__5"
    # a finding the Record does not hold is said, never guessed at
    d2 = _declare(conn, finding_id="pinned__9")
    assert d2.relied_on == [] and "has no claim in the Record" in d2.extra["relied_on_note"]


def test_a_finding_id_two_schemas_share_is_said_and_never_picked(on):
    conn = _conn()
    _finding(conn, fid="pinned__0", schema="main")
    _finding(conn, fid="pinned__0", schema="olist")
    claim, why = W.explorer_finding_claim(conn, "pinned__0")
    assert claim is None and "names 2 findings in different schemas" in why
    claim, why = W.explorer_finding_claim(conn, "pinned__0", "olist")
    assert claim is not None and why == ""


def test_not_acting_on_a_finding_is_a_decision(on, monkeypatch):
    conn = _conn()
    cid = _finding(conn)
    import aughor.explorer.store as ES
    monkeypatch.setattr(ES, "dismiss_insight_conn",
                        lambda c, f, reason="": {"id": f, "finding": "Jeans run at a fifth of revenue"})
    from aughor.routers.exploration import DismissRequest, dismiss_connection_finding
    out = dismiss_connection_finding(conn, "synth__share__5", DismissRequest(reason="seasonal, it passes"), principal=None)
    d = D.get_decision(out["decision_id"])
    assert d.chosen == B.NOT_ACT and [o.id for o in d.options] == [B.ACT, B.NOT_ACT]
    assert d.relied_on == [cid] and d.extra["note"] == "seasonal, it passes"
    assert d.question == "Jeans run at a fifth of revenue"


def _deep(conn: str, actions: list[str]) -> str:
    inv_id = create_investigation("what should we do about returns?", conn)
    complete_investigation(inv_id, report={"headline": "Returns run high on outerwear", "recommended_actions": actions},
                           hypotheses=[], query_history=[], question="what should we do about returns?",
                           connection_id=conn, skip_index=True, cache=False)
    return inv_id


def test_a_recommendation_keeps_the_reports_other_actions_and_says_what_was_recommended(on):
    conn = _conn()
    inv_id = _deep(conn, ["Tighten the outerwear size guide", "Add fit photos", "Cut free returns on sale items"])
    inv.log_recommendation_outcome(inv_id, 0, inv.OutcomeRequest(rec_text="Tighten the outerwear size guide",
                                                                 status="accepted"), principal=None)
    accepted = D.latest_decision(D.Source(kind="recommendation", ref=f"{inv_id}_rec_0"))
    assert [o.id for o in accepted.options] == ["accept", "decline", "alt_1", "alt_2"]
    assert [o.description for o in accepted.options][2:] == ["Add fit photos", "Cut free returns on sale items"]
    assert accepted.extra["recommended"] == "accept" and B.overridden(accepted) is False
    inv.log_recommendation_outcome(inv_id, 2, inv.OutcomeRequest(rec_text="Cut free returns on sale items",
                                                                 status="rejected"), principal=None)
    declined = D.latest_decision(D.Source(kind="recommendation", ref=f"{inv_id}_rec_2"))
    assert [o.id for o in declined.options][2:] == ["alt_0", "alt_1"] and B.overridden(declined) is True


def test_an_approval_says_approve_was_recommended(on):
    p = SimpleNamespace(id="p-" + uuid.uuid4().hex[:6], kind="declared_action", action_id="open_case", source="builder",
                        reasoning="order 2 is overdue", connection_id=_conn(), proposer="amit", trace_id="")
    d = D.get_decision(B.decision_from_proposal(p, chosen="decline", actor="amit"))
    assert d.extra["recommended"] == "approve" and B.overridden(d) is True


def test_with_the_flag_off_every_door_books_what_it_did(off, monkeypatch):
    conn = _conn()
    _finding(conn)
    d = _declare(conn, finding_id="synth__share__5")
    assert d.relied_on == [] and "finding_id" not in d.extra and "relied_on_note" not in d.extra
    inv_id = _deep(conn, ["a", "b"])
    inv.log_recommendation_outcome(inv_id, 0, inv.OutcomeRequest(rec_text="a", status="accepted"), principal=None)
    rec = D.latest_decision(D.Source(kind="recommendation", ref=f"{inv_id}_rec_0"))
    assert [o.id for o in rec.options] == ["accept", "decline"] and "recommended" not in rec.extra
    import aughor.explorer.store as ES
    monkeypatch.setattr(ES, "dismiss_insight_conn", lambda c, f, reason="": {"id": f, "finding": "x"})
    from aughor.routers.exploration import DismissRequest, dismiss_connection_finding
    assert dismiss_connection_finding(conn, "synth__share__5", DismissRequest(reason="r"), principal=None) == \
        {"insight_id": "synth__share__5", "dismissed": True}
    assert RV.review_due_decisions(now=dt.datetime(2026, 10, 15, tzinfo=dt.timezone.utc)) == []


# ── D-2 · every due decision is reviewed, once ─────────────────────────────────────────────

def test_a_decision_that_expected_nothing_is_said_once_to_have_nothing_to_score(on):
    conn = _conn()
    d = _declare(conn)
    now = dt.datetime(2026, 10, 15, tzinfo=dt.timezone.utc)
    mine = [x for x in RV.review_due_decisions(now=now) if D.outcome_by_id(x).of == d.id]
    assert len(mine) == 1
    o = D.get_outcome(d.id)
    assert o.verdict == "cannot_tell" and "nothing was expected" in o.why
    assert [x for x in RV.review_due_decisions(now=now) if D.outcome_by_id(x).of == d.id] == []


# ── D-3 · against what would have happened anyway ─────────────────────────────────────────

def test_the_placebo_a_trend_the_group_shares_is_not_credited_to_a_do_nothing_decision(on, metric):
    """The study's falsifier §5.1, on a business whose four categories grow together: a do-nothing decision on each
    category in each of nine months (36), reviewed against its group, is credited about nothing in the median — where
    each category's own history, on the very same windows, credits it the trend. An 80% band still misses about one
    window in five each way by design (the 2026-10-10 placebo on theLook: 14% below, 15% above), so the claim is the
    median over many, as that placebo's was, never one verdict."""
    conn = _conn()
    metric["revenue"] = _revenue(conn)
    shop = _shop()
    comparison, history, verdicts = [], [], []
    for cat in CATEGORIES:
        for month in range(1, 10):
            decided = dt.date(2026, month, 1)
            d = _declare(conn, decided=decided, expectation={"metric": "revenue", "direction": "up",
                                                             "segment_dimension": "category", "segment_value": cat})
            o = D.outcome_by_id(RV.review_decision(d, runner=shop, today=TODAY))
            assert o.effect.method == "comparison"
            comparison.append(o.effect.value / o.baseline)
            verdicts.append(o.verdict)
            own = S.history_of(_part_history(shop, decided, cat), days=30)
            history.append((o.actual - own.value) / own.value)
    assert abs(statistics.median(comparison)) < 0.01, sorted(comparison)
    assert statistics.median(history) > 0.05, sorted(history)          # the bias the comparison removes
    credited = verdicts.count("as_expected") + verdicts.count("better")
    assert credited <= len(verdicts) // 3, verdicts                    # never most of them


def _part_history(shop, decided: dt.date, cat: str = "Jeans") -> list[float]:
    with shop("any") as (run_sql, _):
        out = []
        for k in range(6, 0, -1):
            start = decided - dt.timedelta(days=30 * k)
            end = decided - dt.timedelta(days=30 * (k - 1))
            _, rows, _ = run_sql(f"SELECT SUM(amount) FROM sales WHERE category = '{cat}' AND day >= DATE '{start}' "
                                 f"AND day < DATE '{end}'")
            out.append(rows[0][0])
    return out


def test_a_real_effect_on_the_part_is_measured_against_its_group(on, metric):
    conn = _conn()
    metric["revenue"] = _revenue(conn)
    d = _declare(conn, expectation={"metric": "revenue", "direction": "up", "segment_dimension": "category",
                                    "segment_value": "Jeans"})
    o = D.outcome_by_id(RV.review_decision(d, runner=_shop(effect_on="Jeans", effect=0.20), today=TODAY))
    assert o.effect.method == "comparison"
    assert 0.17 < o.effect.value / o.baseline < 0.23, o.why        # the +20% read as about +20%
    assert o.verdict == "as_expected"


def test_a_statement_metric_is_judged_against_its_group_too(on, metric):
    """The Lux run of 2026-10-25: the metrics door accepts only whole SELECT statements now, and the review could cut
    only an expression by a segment — so every decision's review on a metric defined today said cannot tell. The
    same decision on the same business, with revenue written as a statement, reads the same comparison."""
    conn = _conn()
    metric["revenue"] = _revenue(conn, sql="SELECT SUM(amount) AS revenue FROM sales")
    d = _declare(conn, expectation={"metric": "revenue", "direction": "up", "segment_dimension": "category",
                                    "segment_value": "Jeans"})
    o = D.outcome_by_id(RV.review_decision(d, runner=_shop(effect_on="Jeans", effect=0.20), today=TODAY))
    assert o.effect.method == "comparison", o.why
    assert 0.17 < o.effect.value / o.baseline < 0.23, o.why        # the +20% read as about +20%
    assert o.verdict == "as_expected"
    assert o.extra["segment"] == {"dimension": "category", "value": "Jeans"}


def test_a_whole_metric_whose_band_drifts_one_way_says_cannot_tell(on, metric, monkeypatch):
    conn = _conn()
    metric["revenue"] = _revenue(conn)
    d = _declare(conn, expectation={"metric": "revenue", "direction": "up"})
    # without the guard the history verdict credits the trend: "as expected", the wanted way
    monkeypatch.setattr(S, "calibration", lambda conn_id=None: [])
    unguarded = B.verdict_against_baseline(actual=1.3, baseline=1.0, low=0.95, high=1.05, direction="up",
                                           against="no expectation", history_note="")
    assert unguarded[0] == "as_expected"
    # the Record's own calibration of revenue's history band: missed above 5 of 8 times (theLook, 2026-10-24)
    monkeypatch.setattr(S, "calibration", lambda conn_id=None: [
        {"method": "history", "metric": "revenue", "author": "system", "n": 8, "inside": 3, "above": 5, "below": 0,
         "cannot_tell": 0, "coverage_observed": 0.375, "coverage_stated": 0.8, "signed_error": 0.625}])
    o = D.outcome_by_id(RV.review_decision(d, runner=_shop(), today=TODAY))
    assert o.effect.method == "history" and o.effect.value > 0
    assert o.verdict == "cannot_tell"
    assert "revenue's own history band has missed above in 5 of 8 scored windows" in o.why
    assert o.extra["drift"].startswith("revenue's own history band")


def test_a_band_that_holds_or_misses_both_ways_names_no_drift(monkeypatch):
    rows = [{"method": "history", "metric": "aov", "author": "system", "inside": 5, "above": 1, "below": 2,
             "coverage_stated": 0.8},
            {"method": "history", "metric": "margin", "author": "system", "inside": 8, "above": 0, "below": 0,
             "coverage_stated": 0.8},
            {"method": "history", "metric": "repeat", "author": "system", "inside": 5, "above": 3, "below": 0,
             "coverage_stated": 0.8}]
    monkeypatch.setattr(S, "calibration", lambda conn_id=None: rows)
    assert S.drift_words("c", "aov") == "" and S.drift_words("c", "margin") == ""
    assert "missed above in 3 of 8" in S.drift_words("c", "repeat")


def test_a_review_window_with_no_rows_says_the_data_ended(on, metric):
    conn = _conn()
    metric["revenue"] = _revenue(conn)
    d = _declare(conn, expectation={"metric": "revenue", "direction": "up"})
    o = D.outcome_by_id(RV.review_decision(d, runner=_shop(ends=dt.date(2026, 7, 20)), today=TODAY))
    assert o.verdict == "cannot_tell" and "hold no rows of Revenue" in o.why and "the data ended" in o.why


def test_another_decision_on_the_same_metric_in_the_same_weeks_is_named(on, metric):
    conn = _conn()
    metric["revenue"] = _revenue(conn)
    exp = {"metric": "revenue", "direction": "up", "segment_dimension": "category", "segment_value": "Jeans"}
    first = _declare(conn, expectation=exp)
    second = _declare(conn, expectation=exp, decided=DECIDED + dt.timedelta(days=10))
    o = D.outcome_by_id(RV.review_decision(first, runner=_shop(), today=TODAY))
    assert o.extra["shared_with"] == [second.id] and "is not split" in o.why


def test_the_recommendation_review_carries_the_same_guard(on, monkeypatch):
    conn = _conn()
    inv_id = _deep(conn, ["Raise prices"])
    inv.log_recommendation_outcome(inv_id, 0, inv.OutcomeRequest(
        rec_text="Raise prices", status="accepted", metric_name="revenue",
        expectation={"metric": "revenue", "direction": "up"}), principal=None)
    rec = next(r for r in O.load_outcomes_for_inv(inv_id) if r.rec_index == 0)
    rec = rec.model_copy(update={"review_value": 130.0, "history_value": 100.0, "history_low": 95.0,
                                 "history_high": 105.0, "reviewed_at": "2026-10-15T00:00:00+00:00"})
    monkeypatch.setattr(S, "drift_words", lambda conn_id, metric: f"{metric}'s own history band has missed above")
    o = D.outcome_by_id(B.outcome_from_review(rec))
    assert o.verdict == "cannot_tell" and o.why.startswith("revenue's own history band has missed above")


def test_what_adds_up_across_parts():
    assert adds_up({"sql": "SUM(sale_price)"}) and adds_up({"sql": "COUNT(*)"}) and adds_up({"sql": "100 * SUM(x)"})
    assert adds_up({"sql": "SELECT SUM(oi.price) AS gmv FROM items oi JOIN orders o ON o.id = oi.order_id"})
    assert not adds_up({"sql": "COUNT(DISTINCT order_id)"}) and not adds_up({"sql": "AVG(price)"})
    assert not adds_up({"sql": "SAFE_DIVIDE(SUM(sale_price), COUNT(DISTINCT order_id))"})
    assert not adds_up({"sql": "SUM(CASE WHEN sold_at IS NOT NULL THEN 1 ELSE 0 END) * 1.0 / NULLIF(COUNT(*), 0)"})


# ── the decision-framework run of 2026-10-25/26: a hold, and the band's reference (defects 5 and 8) ──────────────

HOLD3 = (-3.0, 3.0, "%")


def test_a_hold_that_moved_outside_its_band_is_missed_never_better_or_worse():
    """Scenario 3 on Lux: Mytheresa read +10% against the other shops under "hold within 3%", beyond the noise, and
    the review said cannot tell because a hold names no wanted direction. It missed — and says it is neither side."""
    v, why, e = B.verdict_against_baseline(actual=110.0, baseline=100.0, low=95.0, high=105.0, direction="hold",
                                           against="above", history_note="", band=HOLD3)
    assert v == "missed" and "above the ±3% its hold allowed" in why and "neither better nor worse" in why, why
    v, why, _ = B.verdict_against_baseline(actual=90.0, baseline=100.0, low=95.0, high=105.0, direction="hold",
                                           against="below", history_note="", band=HOLD3)
    assert v == "missed" and "below" in why


def test_a_hold_that_moved_inside_its_band_or_whose_noise_fits_it_held():
    v, why, _ = B.verdict_against_baseline(actual=101.0, baseline=100.0, low=99.5, high=100.5, direction="hold",
                                           against="inside", history_note="", band=HOLD3)
    assert v == "as_expected" and "inside the ±3%" in why, why
    v, why, _ = B.verdict_against_baseline(actual=100.5, baseline=100.0, low=98.0, high=102.0, direction="hold",
                                           against="inside", history_note="", band=HOLD3)
    assert v == "as_expected" and why.startswith("held:"), why


def test_a_hold_inside_a_noise_wider_than_its_band_cannot_tell():
    v, why, _ = B.verdict_against_baseline(actual=100.5, baseline=100.0, low=90.0, high=110.0, direction="hold",
                                           against="inside", history_note="", band=HOLD3)
    assert v == "cannot_tell" and "wider than the ±3% its hold allowed" in why, why


def test_a_hold_in_the_metrics_own_unit_is_where_the_level_may_land():
    v, why, _ = B.verdict_against_baseline(actual=0.36, baseline=0.32, low=0.31, high=0.33, direction="hold",
                                           against="above", history_note="", band=(0.30, 0.34, ""))
    assert v == "missed" and "the 0.3 to 0.34 its hold allowed" in why, why


def test_a_hold_with_no_band_says_so_and_a_comparison_names_its_baseline():
    v, why, _ = B.verdict_against_baseline(actual=110.0, baseline=100.0, low=95.0, high=105.0, direction="hold",
                                           against="no expectation", history_note="", band=None)
    assert v == "cannot_tell" and "named no band" in why
    v, why, _ = B.verdict_against_baseline(actual=110.0, baseline=100.0, low=95.0, high=105.0, direction="hold",
                                           against="above", history_note="", band=HOLD3, method="comparison")
    assert v == "missed" and "against its comparison group" in why and "own history" not in why, why


def test_a_hold_on_a_part_that_moved_is_missed_live_through_the_review(on, metric):
    conn = _conn()
    metric["revenue"] = _revenue(conn)
    d = _declare(conn, expectation={"metric": "revenue", "direction": "hold", "low": -3.0, "mid": 0.0, "high": 3.0,
                                    "unit": "%", "segment_dimension": "category", "segment_value": "Jeans"})
    o = D.outcome_by_id(RV.review_decision(d, runner=_shop(effect_on="Jeans", effect=0.20), today=TODAY))
    assert o.effect.method == "comparison"
    assert o.verdict == "missed" and o.against_expectation == "above", o.why
    assert o.extra["band_read_against"] == "baseline"


def test_a_relative_band_is_read_against_the_baseline_not_the_window_before(on, metric, monkeypatch):
    """Defect 8: "hold within 3% of the other shops" was read against the part's own prior window, so a business
    growing 10% a month put every do-nothing part above its band while the verdict, against the group, read nothing.
    Both now read the same baseline."""
    monkeypatch.setitem(globals(), "GROWTH", 0.10)
    conn = _conn()
    metric["revenue"] = _revenue(conn)
    d = _declare(conn, expectation={"metric": "revenue", "direction": "hold", "low": -3.0, "mid": 0.0, "high": 3.0,
                                    "unit": "%", "segment_dimension": "category", "segment_value": "Jeans"})
    o = D.outcome_by_id(RV.review_decision(d, runner=_shop(), today=TODAY))
    assert o.extra["after"] / o.extra["before"] > 1.04, o.extra          # read against it, above a 3% band
    assert o.against_expectation == "inside", (o.against_expectation, o.why)
    assert o.verdict != "missed", o.why
    claim = S._claims.latest(D.get_decision(o.of).expectation_claim and
                             S._claims.get(D.get_decision(o.of).expectation_claim).key)
    assert claim.extra["scored_against"] == "inside"


# ── defect 6: a metric dated by the month, between two thirty-day windows ─────────────────────────────────────────

def _month_ends(first: dt.date = dt.date(2025, 1, 1), last: dt.date = dt.date(2026, 12, 1)) -> list[dt.date]:
    out, k = [], first
    while k <= last:
        nxt = dt.date(k.year + (k.month == 12), k.month % 12 + 1, 1)
        out.append(nxt - dt.timedelta(days=1))
        k = nxt
    return out


def _snapshots(lift_from: dt.date = dt.date(2099, 1, 1)):
    """Inventory dated on the last day of each month, as Lux's is: Bologna's cover 16 weeks, the others 12."""
    con = duckdb.connect()
    con.execute("CREATE TABLE snaps (snapshot_date DATE, warehouse VARCHAR, cover DOUBLE)")
    for day in _month_ends():
        con.execute("INSERT INTO snaps VALUES (?, 'Bologna', ?)", [day, 16.0 + (4.0 if day >= lift_from else 0.0)])
        con.execute("INSERT INTO snaps VALUES (?, 'Venlo', 12.0)", [day])

    @contextmanager
    def runner(conn_id):
        def run_sql(sql):
            try:
                cur = con.execute(sql)
                return [d[0] for d in cur.description], cur.fetchall(), None
            except Exception as exc:  # noqa: BLE001
                return [], [], str(exc)
        yield run_sql, "duckdb"
    return runner


def _cover(conn: str) -> MetricDefinition:
    return MetricDefinition(name="cover", connection=conn, label="Weeks of cover",
                            sql="SELECT AVG(cover) AS cover FROM snaps", tables=["snaps"], status="approved",
                            time_column="snaps.snapshot_date", time_kind="flow")


def test_a_monthly_snapshot_between_two_thirty_day_windows_is_read_by_the_month(on, metric):
    """Scenario 6 on Lux: decided on 1 March, the thirty days ran to the 30th and the snapshot is dated the 31st —
    "no rows", every time. Read by the month the metric is reported by, March holds its snapshot."""
    conn = _conn()
    metric["cover"] = _cover(conn)
    decided = dt.date(2026, 3, 1)
    d = _declare(conn, decided=decided, expectation={"metric": "cover", "direction": "up", "low": 18.0, "high": 22.0,
                                                     "segment_dimension": "warehouse", "segment_value": "Bologna"})
    o = D.outcome_by_id(RV.review_decision(d, runner=_snapshots(lift_from=decided), today=TODAY))
    assert o.extra["review_by"] == "month" and o.extra["review_window"] == "2026-03-01 → 2026-03-31", o.why
    assert o.extra["thirty_days_held_none"] == "2026-03-01 → 2026-03-30"
    assert o.actual == 20.0 and o.extra["before"] == 16.0, (o.actual, o.extra)


def test_a_month_that_has_not_ended_moves_the_review_date_and_says_why(on, metric):
    conn = _conn()
    metric["cover"] = _cover(conn)
    d = _declare(conn, decided=dt.date(2026, 3, 1), expectation={"metric": "cover", "direction": "up"})
    assert RV.review_decision(d, runner=_snapshots(), today=dt.date(2026, 3, 31)) is None
    moved = D.latest_decision(d.source)
    assert moved.id != d.id and moved.review_on == "2026-04-01" and not moved.outcome
    assert moved.extra["review_by"] == "month" and "dated by the month" in moved.extra["review_on_why"]
    o = D.outcome_by_id(RV.review_decision(moved, runner=_snapshots(), today=dt.date(2026, 4, 2)))
    assert o.extra["review_by"] == "month" and o.actual == 14.0, o.why


def test_a_month_with_no_rows_either_says_both_were_read(on, metric):
    conn = _conn()
    metric["cover"] = _cover(conn)
    d = _declare(conn, decided=dt.date(2027, 3, 1), expectation={"metric": "cover", "direction": "up"})
    o = D.outcome_by_id(RV.review_decision(d, runner=_snapshots(), today=dt.date(2027, 6, 1)))
    assert o.verdict == "cannot_tell" and "nor does the whole month after it" in o.why, o.why


# ── the intake doors (the decision-framework study §3.2, §8 step 3) ───────────────────────────────────────────────

def _run_with_answer(conn: str, run: str = "") -> tuple[str, str]:
    from aughor.kernel.ledger import DEEP_REPORT_KIND
    run = run or "inv-" + uuid.uuid4().hex[:6]
    out = W.book_from_receipt(kind=DEEP_REPORT_KIND, natural_key=f"ada:{conn}:{run}", receipt_id="rcpt-" + run,
                              connection_id=conn, question="What did paid social bring?",
                              headline="Paid social brought 132 of 923 orders", sql="SELECT 1",
                              payload_extra={"investigation_id": run})
    return run, out["observation"]


def test_a_decision_on_a_runs_answer_cites_what_its_receipt_booked(on):
    """A dashboard Question's answer or a chat answer is a run: the decision taken on it cites the claims the run's
    receipt booked, chosen by the server — a run that booked none is said, never guessed at."""
    conn = _conn()
    run, observation = _run_with_answer(conn)
    did = B.declare_decision(question="Pause paid social?", chosen="pause it", options=["pause it", B.NOT_ACT],
                             connection_id=conn, decided_by="user:amit", run_id=run)
    d = D.get_decision(did)
    assert d.relied_on == [observation] and d.extra["run_id"] == run
    did = B.declare_decision(question="Pause paid social?", chosen="pause it", connection_id=conn,
                             decided_by="user:amit", run_id="inv-none")
    d = D.get_decision(did)
    assert d.relied_on == [] and "booked no claim" in d.extra["relied_on_note"]


def test_a_decision_on_a_briefing_figure_books_the_reading_it_relied_on(on, metric, monkeypatch):
    """The Briefing figure is measured for the edition's days by the metric's own compiler and booked as a reading
    with its own receipt — the page's number is never taken on trust — and the decision cites it."""
    conn = _conn()
    metric["revenue"] = _revenue(conn)
    import aughor.knowledge.period_brief as PB
    import aughor.routers.investigations as INV
    monkeypatch.setattr(PB, "connection_runner", _shop())
    receipts = []
    monkeypatch.setattr(INV, "write_answer_receipt", lambda **kw: receipts.append(kw) or {"receipt_id": "rcpt-fig"})
    did = B.declare_decision(question="The week: 3 to 9 August", chosen="cut Jeans' discount", connection_id=conn,
                             decided_by="user:amit", figure={"metric": "revenue", "start": "2026-08-03",
                                                             "end": "2026-08-10"})
    d = D.get_decision(did)
    assert len(d.relied_on) == 1 and d.extra["figure"]["metric"] == "revenue"
    reading = S._claims.get(d.relied_on[0])
    assert reading.kind == "reading" and reading.tier == "measured" and reading.statement.metric == "revenue"
    assert reading.statement.range_start == "2026-08-03" and reading.statement.range_end == "2026-08-10"
    assert reading.statement.value and reading.warrants[0].ref == "rcpt-fig" and reading.status == "Final"
    assert receipts[0]["sqls"][0] and "2026-08-03 to 2026-08-09" in receipts[0]["question"]
    # a figure with no rows, or no such metric, is said and nothing is cited
    did = B.declare_decision(question="2030", chosen="x", connection_id=conn, decided_by="user:amit",
                             figure={"metric": "revenue", "start": "2030-01-01", "end": "2030-01-08"})
    assert D.get_decision(did).relied_on == [] and "holds no rows" in D.get_decision(did).extra["relied_on_note"]
    did = B.declare_decision(question="?", chosen="x", connection_id=conn, decided_by="user:amit",
                             figure={"metric": "nope", "start": "2026-08-03", "end": "2026-08-10"})
    assert "not a metric on this connection" in D.get_decision(did).extra["relied_on_note"]


def test_with_the_loop_off_a_run_or_figure_is_not_cited(off):
    conn = _conn()
    run, _obs = _run_with_answer(conn)
    did = B.declare_decision(question="Pause?", chosen="pause it", connection_id=conn, decided_by="user:amit",
                             run_id=run, figure={"metric": "revenue", "start": "2026-08-03", "end": "2026-08-10"})
    d = D.get_decision(did)
    assert d.relied_on == [] and "run_id" not in d.extra and "figure" not in d.extra


def test_a_decision_said_in_slack_cites_the_threads_answer_and_its_card_books_approvals(on):
    from fastapi import HTTPException

    from aughor.routers import arrivals as A
    conn = _conn()
    run, observation = _run_with_answer(conn)
    out = A.slack_decision(A.SlackDecision(
        channel="C1", thread_ts="1712.001", text="pause paid social on Mytheresa for September",
        question="What did paid social bring?", investigation_id=run, connection_id=conn, author="Amit",
        author_ref="slack:U9", approver_refs=["slack:U2", "slack:U3", "mailto:x"]))
    d = D.get_decision(out["decision_id"])
    assert out["cited"] == 1 and d.relied_on == [observation]
    assert d.decided_by == "person:Amit" and d.approvers == ["slack:U2", "slack:U3"] and d.chosen.startswith("pause")
    assert "Slack thread C1:1712.001" in d.extra["note"]
    got = A.slack_decision_approval(out["decision_id"], A.SlackApproval(verdict="approve", author="Ana", author_ref="slack:U2"))
    assert got["booked"] and got["why"] == "approved by Ana"
    again = A.slack_decision_approval(out["decision_id"], A.SlackApproval(verdict="approve", author="Ana", author_ref="slack:U2"))
    assert not again["booked"]
    A.slack_decision_approval(out["decision_id"], A.SlackApproval(verdict="dissent", author="Eve", author_ref="slack:U5"))
    now = D.latest_decision(d.source)
    assert now.extra["approvals"][0]["by"] == "person:Ana" and now.extra["approvals"][0]["named"] is True
    assert now.dissent[-1].who == "person:Eve" and "decision card" in now.dissent[-1].why
    with pytest.raises(HTTPException) as e:
        A.slack_decision_approval("no-such", A.SlackApproval())
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        A.slack_decision(A.SlackDecision(channel="C1", thread_ts="1.2", text="   "))
    assert e.value.status_code == 422
