"""Wave L7 (V3b) — canvas, dashboard-card and eval-suite artifacts on the V3 lifecycle.

`savedquery` was V3's wired proof; these are the same three-line call site each, deferred at
V3 and landed here. Same contract throughout: the store row stays the live record and reads
are untouched; a DESTRUCTIVE write additionally records a versioned draft; flag off ⇒
byte-identical behaviour and no history.

What each wiring protects:
* **canvas** — a scope edit silently redefines what every investigation on that canvas can
  see; before this the prior scope was simply gone.
* **dashboard card** — the upsert's ``ON CONFLICT DO UPDATE`` overwrites SQL, thresholds and
  render spec on the artifact a cockpit shows daily. The create is not a revision (the
  savedquery precedent: the UPDATE is what creates the first revision).
* **eval suite** — the corpus IS the artifact, and it is edited destructively while the
  suite's run history still cites the deleted case_ids. Revisions are recorded after each
  corpus mutation, so the pre-delete corpus is always the previous revision.
"""
from __future__ import annotations

import importlib

import pytest

from aughor.kernel.lifecycle import history


@pytest.fixture
def _on(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))


# ── canvas ────────────────────────────────────────────────────────────────────

def _canvas_store(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_CANVAS_DB", str(tmp_path / "canvas.db"))
    from aughor.canvas import store as cv
    importlib.reload(cv)
    return cv


def test_canvas_update_records_a_revision(_on, monkeypatch, tmp_path):
    cv = _canvas_store(monkeypatch, tmp_path)
    from aughor.canvas.models import CanvasScope

    c = cv.create_canvas("v1", [CanvasScope(connection_id="c1", tables=["t1"])])
    cv.update_canvas(c.id, name="v2", scopes=[CanvasScope(connection_id="c1", tables=["t2"])])

    revs = history("canvas", f"canvas:{c.id}")
    assert len(revs) == 1, "the UPDATE is what creates the first revision"
    assert revs[0].body["name"] == "v2"
    assert revs[0].body["scopes"][0]["tables"] == ["t2"], \
        "the revision must carry the scope — a scope edit is the destructive change"
    assert revs[0].state == "draft"


def _dash_store(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_DASHBOARD_DB", str(tmp_path / "dash.db"))
    from aughor.dashboard import store as ds
    importlib.reload(ds)
    return ds


def test_card_update_records_a_revision_but_create_does_not(_on, monkeypatch, tmp_path):
    ds = _dash_store(monkeypatch, tmp_path)
    from aughor.dashboard.models import DashboardCard

    card = ds.upsert_card(DashboardCard(connection_id="c1", title="v1", sql="SELECT 1"))
    assert history("dashboard", f"dashboard:{card.id}") == [], \
        "a create is readable as the live row; the UPDATE is what creates the first revision"

    ds.upsert_card(card.model_copy(update={"title": "v2", "sql": "SELECT 2"}))
    revs = history("dashboard", f"dashboard:{card.id}")
    assert len(revs) == 1
    assert revs[0].body["sql"] == "SELECT 2"
    assert revs[0].state == "draft"


def _evals_store(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_EVALS_DB", str(tmp_path / "evals.db"))
    from aughor.evals import store as ev
    importlib.reload(ev)
    return ev


def test_corpus_mutations_record_revisions_and_predelete_state_survives(_on, monkeypatch, tmp_path):
    ev = _evals_store(monkeypatch, tmp_path)

    suite = ev.create_suite("s")
    sid = suite["id"]
    assert history("evalsuite", f"evalsuite:{sid}") == [], \
        "an empty suite has no corpus to version yet"

    ev.add_cases(sid, [{"question": "q1"}, {"question": "q2"}])
    kept, doomed = ev.list_cases(sid)
    ev.delete_case(doomed["id"])

    revs = history("evalsuite", f"evalsuite:{sid}")   # newest first
    assert len(revs) == 2, "one revision per corpus mutation (add_cases, delete_case)"
    assert revs[0].body["case_count"] == 1, "the latest revision is the post-delete corpus"
    # The point of the wiring: the corpus as it stood BEFORE the delete is the previous
    # revision — the deleted case's question is still recoverable.
    assert revs[1].body["case_count"] == 2
    assert {cs["question"] for cs in revs[1].body["cases"]} == {"q1", "q2"}
    assert doomed["id"] in {cs["id"] for cs in revs[1].body["cases"]}


