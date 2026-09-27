"""A Briefing's figures are re-measured as they mature, and its comparison says its age
(Arc BR-6 deliverables 2 and 3)."""
from __future__ import annotations

import contextlib
from datetime import date, datetime, timezone

import pytest

from aughor.briefing import recall, versions


def _brief(**metrics) -> dict:
    """A built Briefing in its real shape: figures under `period.measured`, each with its SQL."""
    return {"narrative": "August's return rate improved.",
            "period": {"label": "Month",
                       "measured": [{"name": n, "current": v, "sql": f"SELECT {n}"}
                                    for n, v in metrics.items()]}}


def _warehouse(**answers):
    """A runner in `connection_runner`'s shape: a context manager yielding (run_sql, dialect)."""
    @contextlib.contextmanager
    def _runner():
        def run_sql(sql: str):
            name = sql.replace("SELECT ", "").strip()
            if name not in answers:
                return [], [], "no such metric"
            return ["v"], [[answers[name]]], ""
        yield run_sql, "duckdb"
    return _runner


KEY = {"scope_key": "s", "range_key": "2026-08-01..2026-08-31", "recipe": "month"}


# ── deliverable 2 · the recall ────────────────────────────────────────────────

def test_a_briefing_whose_figures_held_is_not_revised():
    versions.record("r1", _brief(return_rate=10.0), **KEY)
    art = versions.history("r1", **KEY)[0]

    out = recall.recall_one("r1", art, runner=_warehouse(return_rate=10.0))

    assert out["status"] == "unchanged"
    assert len(versions.history("r1", **KEY)) == 1


def test_a_figure_that_matured_becomes_a_new_version():
    """August's return rate, told as 10.0%, is 12.4% once its returns arrive."""
    versions.record("r2", _brief(return_rate=10.0), **KEY)
    art = versions.history("r2", **KEY)[0]

    out = recall.recall_one("r2", art, runner=_warehouse(return_rate=12.4),
                            now=datetime(2026, 10, 12, tzinfo=timezone.utc))

    assert out["status"] == "revised" and out["version"] == 2
    moved = [r for r in out["revisions"] if r["what"] == "moved"]
    assert moved and moved[0]["from"] == 10.0 and moved[0]["to"] == 12.4
    assert len(versions.history("r2", **KEY)) == 2


def test_a_connection_that_cannot_be_read_is_not_a_stable_briefing():
    """A TYPED verdict: "nothing moved" and "nothing could be measured" are different facts,
    and a caller that cannot tell them apart reports a dead warehouse as a steady figure."""
    versions.record("r3", _brief(return_rate=10.0), **KEY)
    art = versions.history("r3", **KEY)[0]

    out = recall.recall_one("r3", art, runner=_warehouse())   # answers nothing

    assert out["status"] == "unmeasured"      # NOT "unchanged"
    assert len(versions.history("r3", **KEY)) == 1


def test_the_narrative_is_kept_as_written():
    """It was true when it was written. A version that re-wrote the prose around new numbers
    would destroy the record BR-6 exists to keep."""
    rebuilt = recall._with_figures(_brief(return_rate=10.0), {"return_rate": 12.4})

    assert rebuilt["narrative"] == "August's return rate improved."
    assert versions.figures(rebuilt) == {"return_rate": 12.4}


def test_the_next_briefing_can_list_what_was_revised():
    versions.record("r4", _brief(return_rate=10.0), **KEY)
    art = versions.history("r4", **KEY)[0]
    recall.recall_one("r4", art, runner=_warehouse(return_rate=12.4))

    items = recall.revisions_since("r4", days=1)

    assert [i["name"] for i in items] == ["return_rate"]
    assert items[0]["range"] == KEY["range_key"]


def test_the_recall_reads_the_warehouse_not_the_cache():
    """§3.27's review caught law 1 checking a Briefing against itself. `connection_runner`'s
    `cached=False` is the only reader this loop uses."""
    import inspect
    src = inspect.getsource(recall.remeasure)
    assert "cached=False" in src
    assert "get_cached" not in src


# ── deliverable 3 · comparisons at equal age ──────────────────────────────────

def test_every_comparison_window_is_read_at_the_same_age():
    """BR-9 already gives each comparison its own as-of; BR-6 depends on it, so it is pinned
    here. August read on 15 September is 14 days old, so July is read at 14 days too."""
    from aughor.briefing.ranges import RangeSpec

    spec = RangeSpec(preset="custom", start=date(2026, 8, 1), end=date(2026, 9, 1),
                     previous_start=date(2026, 7, 1), previous_end=date(2026, 8, 1),
                     last_year_start=date(2025, 8, 1), last_year_end=date(2025, 9, 1),
                     as_of=date(2026, 9, 15), lag_days=8, lag_source="learned",
                     still_moving=[], period="month")

    ages = {(w.as_of - w.end).days for w in spec.windows()}
    assert ages == {14}, "a young cohort against a matured one always reads as an improvement"


class _Metric:
    def __init__(self, kind, label="Return Rate"):
        self.time_kind, self.label, self.name = kind, label, "return_rate"


@pytest.mark.parametrize("kind,status", [("flow", "final"), ("cohort", "provisional"),
                                         ("cohort", "to_date"), ("stock", "final")])
def test_a_comparison_that_is_at_equal_age_says_nothing(kind, status):
    from aughor.briefing.ranges import equal_age
    out = equal_age(_Metric(kind), status)
    assert out["equal"] is True and out["why"] == ""


@pytest.mark.parametrize("status", ["provisional", "to_date"])
def test_a_provisional_flow_figure_says_it_is_not_at_equal_age(status):
    """Its rows arrive late with no outcome date, so there is nothing to bound — the honest
    comparison needs BR-8's daily readings, and until then the page SAYS so."""
    from aughor.briefing.ranges import equal_age
    out = equal_age(_Metric("flow"), status)

    assert out["equal"] is False
    assert "Return Rate" in out["why"]
    assert "same age" in out["why"]


# ── a metric the cap cut says the cap cut it ──────────────────────────────────

def test_an_over_cap_metric_is_not_reported_as_undefined(monkeypatch):
    """Measured live 2026-09-27: theLook had ten approved definitions against a cap of eight,
    and the two it dropped fell through to the north-star loop, which reports "no approved
    definition; approve one in the Semantic Layer" — about metrics approved there minutes
    earlier. A reader following that instruction finds the work already done.

    Drives the real `measure_range`, so it fails if the reporting regresses."""
    from datetime import date

    from aughor.briefing import ranges
    from aughor.semantic import metric_time as mt

    class _M:
        def __init__(self, n):
            self.name, self.label, self.status, self.connection = n, n.title(), "approved", "c"
            self.time_kind, self.tables, self.unit = "flow", [], ""
            self.time_source, self.time_confirmed_by = "rule", None

    governed = [_M(f"m{i}") for i in range(ranges.MAX_METRICS + 2)]
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda **k: governed)
    monkeypatch.setattr(mt, "ensure_dates", lambda *a, **k: {})
    monkeypatch.setattr(mt, "declared", lambda m: True)
    monkeypatch.setattr(mt, "run_measure", lambda *a, **k: ([], "measured elsewhere"))

    spec = ranges.RangeSpec(preset="custom", start=date(2026, 8, 1), end=date(2026, 9, 1),
                            previous_start=date(2026, 7, 1), previous_end=date(2026, 8, 1),
                            last_year_start=None, last_year_end=None, as_of=date(2026, 9, 15),
                            lag_days=8, lag_source="learned", still_moving=[], period="month")
    out = ranges.measure_range("c", spec, run_sql=lambda s: ([], [], ""), dialect="duckdb",
                               north_stars=[{"name": m.label} for m in governed])

    reasons = {u["name"]: u["reason"] for u in out["unmeasured"]}
    cut = [m.label for m in governed[ranges.MAX_METRICS:]]
    for name in cut:
        assert "cap" in reasons.get(name, ""), f"{name} was cut by the cap and must say so"
        assert "no approved definition" not in reasons.get(name, "")
