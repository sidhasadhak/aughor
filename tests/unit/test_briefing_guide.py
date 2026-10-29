"""Arc BG-1 (ROADMAP §3.66) — the Briefing guide.

A guide is judgement kept as versions: the Explorer's draft, a person's edit, a published version
that a later draft never replaces. Its checks are measured once before they are kept — one that
cannot be measured is kept out WITH why. A redraft keeps the readers a person already has and only
proposes the rest.
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
def con():
    """Returns arriving every day: 6 a day refunding 50 each, two reasons, two categories."""
    c = duckdb.connect()
    c.execute("""CREATE TABLE returns AS
        SELECT d::DATE AS return_date, 50.0 AS refund_eur,
               CASE WHEN i % 2 = 0 THEN 'size_fit' ELSE 'changed_mind' END AS reason,
               CASE WHEN i % 3 = 0 THEN 'womenswear' ELSE 'shoes' END AS category
        FROM range(DATE '2026-08-01', DATE '2026-10-29', INTERVAL 1 DAY) t(d), range(6) k(i)""")
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


def _week():
    spec, why = ranges.resolve_range("last_week", today=OCT29, lag_days=1, lag_source="learned")
    assert spec is not None, why
    return spec


def _guide(**kw) -> G.BriefingGuide:
    return G.BriefingGuide(**{"business": "A shop.", **kw})


def test_a_version_needs_who_wrote_it():
    with pytest.raises(ValueError):
        G.save("c1", None, _guide(), by="")


def test_a_published_version_stays_what_editions_read_after_a_later_draft():
    G.save("c1", "s", _guide(business="first draft"), by="explorer")
    used, rev = G.current("c1", "s")
    assert used.business == "first draft" and rev.state == "draft"      # a draft is read until one is published

    G.publish("c1", "s", by="user:amit")
    G.save("c1", "s", _guide(business="the explorer's redraft"), by="explorer")

    used, rev = G.current("c1", "s")
    assert used.business == "first draft" and rev.state == "published" and rev.by == "user:amit"
    working, wrev = G.working_copy("c1", "s")
    assert working.business == "the explorer's redraft" and wrev.state == "draft"
    assert [r.version for r in G.versions("c1", "s")] == sorted(
        (r.version for r in G.versions("c1", "s")), reverse=True)        # every version kept, newest first
    assert len(G.versions("c1", "s")) == 3


def test_a_check_that_cannot_be_measured_is_kept_out_with_why(con):
    spec = _week()
    checks = [
        G.Check(id="refunds", label="Refunds paid", sql="SUM(refund_eur)", tables=["returns"],
                time_column="returns.return_date", dimensions=["reason"]),
        G.Check(id="aov", label="Average order", metric="average_order_value"),
        G.Check(id="undated", label="Undated", sql="COUNT(*)", tables=["returns"]),
        G.Check(id="broken", label="Broken", sql="SUM(no_such_column)", tables=["returns"],
                time_column="returns.return_date"),
        G.Check(id="empty", label="Nothing", sql="COUNT(*)", tables=["returns"], filters=["reason = 'none'"],
                time_column="returns.return_date"),
    ]
    kept, dropped = G.verify_checks(checks, metrics_by_name={}, run_sql=_run(con), dialect="duckdb",
                                    windows=spec.windows()[:2])
    assert [c.id for c in kept] == ["refunds"]
    why = {d.id: d.reason for d in dropped}
    assert "no approved metric" in why["aov"]
    assert "no date" in why["undated"]
    assert "query failed" in why["broken"]
    assert "no rows" in why["empty"]


class _LLM:
    def __init__(self, draft):
        self.draft, self.calls = draft, 0

    def complete(self, *, system, user, response_model, temperature):
        self.calls += 1
        assert response_model is G._Draft
        return self.draft


def test_a_redraft_keeps_a_persons_readers_and_proposes_the_rest(con, monkeypatch):
    monkeypatch.setattr(G, "_context", lambda conn_id, schema, today: "context")
    monkeypatch.setattr(G, "_function_groups", lambda: [{"id": "finance", "name": "Finance", "description": ""},
                                                        {"id": "product", "name": "Product", "description": ""}])
    monkeypatch.setattr(ranges, "resolve_for", lambda *a, **k: (_week(), ""))
    monkeypatch.setattr(ranges, "governed_metrics", lambda *a, **k: [])
    # a person already added Finance, watching one check
    G.save("c2", None, _guide(readers=[G.Reader(group_id="finance", name="Finance", watches="cash",
                                                check_ids=["refunds"])]), by="user:amit", publish=True)
    draft = G._Draft(
        business="A returns-heavy shop.", ranges=G.RangeNotes(week="steer"),
        checks=[G.Check(id="Refunds", label="Refunds paid", sql="SUM(refund_eur)", tables=["returns"],
                        time_column="returns.return_date"),
                G.Check(id="ghost", label="Ghost", metric="nope")],
        readers=[G.Reader(group_id="finance", name="Finance", watches="the model's words", check_ids=["ghost"]),
                 G.Reader(group_id="product", name="Product", watches="pages", check_ids=["refunds", "ghost"]),
                 G.Reader(group_id="buying", name="Buying", watches="categories")])
    llm = _LLM(draft)
    rev = G.draft_guide("c2", None, today=OCT29, llm=llm,
                        runner=lambda: contextlib.nullcontext((_run(con), "duckdb")))

    assert llm.calls == 1 and rev.state == "draft" and rev.by == "explorer"
    body = G.BriefingGuide.model_validate(rev.body)
    assert [c.id for c in body.checks] == ["refunds"]                       # slugged, measured
    assert [d.id for d in body.dropped] == ["ghost"]                         # said, not silent
    by_group = {r.group_id: r for r in body.readers}
    assert by_group["finance"].watches == "cash"                             # the person's reader kept as it was
    assert by_group["product"].check_ids == ["refunds"]                      # an existing group: a reader
    assert [r.name for r in body.proposed_readers] == ["Buying"]             # no such group: a proposal
    used, used_rev = G.current("c2", None)
    assert used_rev.state == "published" and used.readers[0].watches == "cash"   # the redraft replaces nothing


def test_the_generic_lifecycle_doors_refuse_to_write_a_guide():
    from aughor.routers.lifecycle import _own_doors
    assert G.KIND in _own_doors()


def test_the_briefer_runs_the_guide_job():
    from aughor.kernel.agents import charter_for_kind
    assert charter_for_kind(G.JOB_KIND).id == "briefer"
