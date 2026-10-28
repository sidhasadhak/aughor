"""Arc SH, SH-5 — a column a model writes, filled for the rows of a view a person picks (ROADMAP §3.64).

Run against the real stores, each at a temporary path, with a scripted model in place of a real one: no call leaves
the process. The laws under test are the arc's: 25 rows a call, at most 200 a fill, only the view's rows not filled
yet, the calls and the cost said before it runs, one change undone whole — and no figure ever counted from what a model
wrote.
"""
from __future__ import annotations

import re

import pytest


def _reviews(n: int) -> str:
    lines = ["review_id,order_id,review_score,review_comment_message"]
    for i in range(1, n + 1):
        score = 1 if i % 3 == 0 else 5
        text = "chegou atrasado e quebrado" if score == 1 else "otimo produto"
        lines.append(f"r{i:04d},o{i:04d},{score},{text} {i}")
    return "\n".join(lines) + "\n"


class Scripted:
    """A model that answers each row it is asked about with "topic <row>", except the rows it is told to leave empty;
    that also answers rows it was never asked about, when told to; and fails the calls it is told to fail."""
    backend, _model = "anthropic", "claude-fast-test"

    def __init__(self, empty=(), fail_calls=(), extra=()):
        self.calls: list[list[int]] = []
        self.empty, self.fail_calls, self.extra = set(empty), set(fail_calls), list(extra)

    def complete(self, *, system, user, response_model):
        rows = [int(r) for r in re.findall(r"^\[(\d+)\]", user, re.M)]
        self.calls.append(rows)
        if len(self.calls) in self.fail_calls:
            raise RuntimeError("the provider timed out")
        return response_model(rows=[{"row": r, "value": "" if r in self.empty else f"topic {r}"}
                                    for r in rows + self.extra])


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ana")
    from aughor.actions import overlay
    monkeypatch.setattr(overlay, "_DB_PATH", tmp_path / "overlay.db")
    from aughor.sheets import projection
    projection.reset()
    yield tmp_path
    projection.reset()


def _sheet(env, n=60):
    from aughor.sheets import files, service
    path = env / "olist_order_reviews_dataset.csv"
    path.write_text(_reviews(n))
    return service.create_from_file(files.stage(path, path.name), name="Olist reviews", by="user:ana",
                                    chosen={"review_score": "number"})


def _topic(env, n=60):
    from aughor.sheets import model, model_columns
    sheet = _sheet(env, n)
    msg = sheet.column("review_comment_message").id
    model_columns.add(sheet, name="Complaint topic", instruction="the complaint, in two or three words",
                      reads=[msg], by="user:ana")
    sheet = model.get(sheet.id)
    return sheet, sheet.column("Complaint topic")


LOW_JSON = [{"column": "c3", "op": "lte", "value": 2}]   # review_score is the third column


def _low():
    from aughor.sheets.model import Condition
    return [Condition(**c) for c in LOW_JSON]


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aughor.routers import sheets as sheets_router
    app = FastAPI()
    app.include_router(sheets_router.router)
    return TestClient(app)


# ── as it was ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_column_no_model_writes_is_stored_as_before(env):
    from aughor.kernel.ledger import Ledger
    from aughor.sheets import model
    sheet = _sheet(env)
    assert _client().post(f"/sheets/{sheet.id}/columns", json={"name": "Note"}).status_code == 200
    for art in Ledger.default().artifacts_of_kind(model.KIND, conn_id=model.SHEETS_CONNECTION, org_id="default"):
        assert all("model_writes" not in c for c in art["payload"]["_body"]["columns"])


# ── a column a model writes ──────────────────────────────────────────────────────────────────────────────────────────

def test_a_model_column_says_what_it_writes_from_what(env):
    from aughor.sheets import model, model_columns, service
    sheet = _sheet(env)
    with pytest.raises(service.Refused, match="say what the model writes"):
        model_columns.add(sheet, name="Topic", instruction="  ", reads=["c4"], by="user:ana")
    with pytest.raises(service.Refused, match="no column 'nope' to read"):
        model_columns.add(sheet, name="Topic", instruction="the topic", reads=["nope"], by="user:ana")
    with pytest.raises(service.Refused, match="at least one column"):
        model_columns.add(sheet, name="Topic", instruction="the topic", reads=[], by="user:ana")
    sheet, topic = _topic(env)
    assert topic.model_writes.instruction == "the complaint, in two or three words"
    assert topic.description.startswith("written by a model: ")
    with pytest.raises(service.Refused, match="a model column reads what people and files wrote"):
        model_columns.add(model.get(sheet.id), name="Topic of topic", instruction="x", reads=[topic.id], by="user:ana")


def test_a_fill_is_said_before_it_runs_rows_calls_and_cost(env, monkeypatch):
    from aughor.obs import usage
    from aughor.sheets import model_columns
    sheet, topic = _topic(env, n=600)                 # 200 low scores: rows 3, 6, …, 600
    plan = model_columns.plan(sheet, topic.id, conditions=_low(), sort=[], provider=Scripted())
    assert (plan["rows"], plan["unfilled"], plan["of"], plan["calls"]) == (200, 200, 200, 8)
    assert plan["cost_usd"] is None and plan["cost"] == "the price of claude-fast-test is not set here, so the fill's cost is not said"
    monkeypatch.setattr(usage, "price_for", lambda b, m: usage.Price(input_per_1m=1.0, output_per_1m=5.0, as_of="2026-10-28"))
    whole = model_columns.plan(sheet, topic.id, conditions=[], sort=[], provider=Scripted())
    assert (whole["rows"], whole["unfilled"], whole["calls"]) == (200, 600, 8)      # never more than 200 a fill
    assert whole["cost_usd"] > 0 and whole["cost"].startswith("about $") and whole["cost"].endswith("claude-fast-test")
    assert "the first 200 of the 600 not filled" in whole["said"]


def test_a_fill_writes_the_views_rows_25_a_call_as_one_change_undone_whole(env):
    from aughor.actions import overlay
    from aughor.sheets import model, model_columns, projection, service
    sheet, topic = _topic(env)
    model_ = Scripted(empty={9}, extra=[4])          # row 4 was never asked about
    out = model_columns.fill(sheet, topic.id, conditions=_low(), sort=[], by="user:ana", provider=model_)
    assert [len(c) for c in model_.calls] == [20] and model_.calls[0][:3] == [3, 6, 9]
    assert (out["filled"], out["calls"], out["asked"], out["left_empty"]) == (19, 1, 20, 1)
    assert projection.read_row(sheet, 3)[topic.id] == "topic 3"
    assert projection.read_row(sheet, 9)[topic.id] is None              # the model said nothing: not filled
    assert projection.read_row(sheet, 4)[topic.id] is None              # outside the view, and never asked
    edits = [e for e in overlay.sheet_values(sheet.id) if e.column == topic.id]
    assert {e.origin for e in edits} == {next(iter({e.origin for e in edits}))} and edits[0].origin.startswith("model:")
    assert {e.actor for e in edits} == {"user:ana"}
    # one change, undone whole
    service.undo(model.get(sheet.id), by="user:ana")
    assert projection.read_row(sheet, 3)[topic.id] is None
    assert not [e for e in overlay.sheet_values(sheet.id) if e.column == topic.id]


def test_a_failed_call_leaves_its_rows_unfilled_and_says_so_and_the_next_fill_takes_only_the_rest(env):
    from aughor.sheets import model, model_columns
    sheet, topic = _topic(env, n=150)                 # 50 low scores
    out = model_columns.fill(sheet, topic.id, conditions=_low(), sort=[], by="user:ana", provider=Scripted(fail_calls={1}))
    assert (out["filled"], out["failed"], out["calls"]) == (25, 25, 2)
    assert out["notes"] == ["rows 3–75 were not filled: the call failed (the provider timed out)"]
    again = Scripted()
    out = model_columns.fill(model.get(sheet.id), topic.id, conditions=_low(), sort=[], by="user:ana", provider=again)
    assert out["filled"] == 25 and again.calls[0][0] == 3 and len(again.calls) == 1


# ── never a figure ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_nothing_is_counted_from_what_a_model_wrote(env):
    from aughor.sheets import chat, combine, dashboard, model, model_columns, projection, service, views
    from aughor.sheets.model import Condition, Rule, View
    sheet, topic = _topic(env)
    model_columns.fill(sheet, topic.id, conditions=_low(), sort=[], by="user:ana", provider=Scripted())
    sheet = model.get(sheet.id)
    page = projection.read_rows(sheet)
    assert page["totals"][topic.id] == {"filled": 20}                    # how many filled — and nothing of its values
    with pytest.raises(views.ViewRefused, match="written by a model, and nothing is counted"):
        views.groups(sheet, conditions=[], group=topic.id)
    with pytest.raises(views.ViewRefused, match="a grouping by it is not made"):
        views.check_view(sheet, View(name="By topic", group=topic.id))
    with pytest.raises(service.Refused, match="a rule by it is not made"):
        service.save_rule(sheet, Rule(name="Broken", conditions=[Condition(column=topic.id, op="contains",
                                                                           value="topic")]), by="user:ana")
    from aughor.sheets import files
    path = env / "topics.csv"
    path.write_text("topic,owner\ntopic 3,ops\n")
    other = service.create_from_file(files.stage(path, path.name), name="Topics", by="user:ana")
    with pytest.raises(service.Refused, match="a link by it is not made"):
        combine.link_preview(sheet, topic.id, other.id, other.column("topic").id)
    assert all(topic.id not in str(card) for card in dashboard.propose(sheet, None).get("cards", []))
    line = next(c for c in chat.explain_sheet(sheet.id)["columns"] if c["name"] == "Complaint topic")
    assert "never count by it" in line["written_by_a_model"]


# ── the routes ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_routes_add_preview_and_fill_and_the_cell_says_a_model_wrote_it(env, monkeypatch):
    import aughor.llm.provider as provider_mod
    sheet = _sheet(env)
    scripted = Scripted()
    monkeypatch.setattr(provider_mod, "get_provider", lambda role="coder", **_: scripted)
    client = _client()
    made = client.post(f"/sheets/{sheet.id}/columns", json={"name": "Complaint topic", "model": {
        "instruction": "the complaint, in two or three words", "reads": ["review_comment_message"]}}).json()
    topic = next(c for c in made["columns"] if c["name"] == "Complaint topic")
    assert topic["model_writes"]["reads"] == ["c4"]
    body = {"filter": LOW_JSON}
    preview = client.post(f"/sheets/{sheet.id}/columns/{topic['id']}/fill/preview", json=body).json()
    assert (preview["rows"], preview["calls"]) == (20, 1) and scripted.calls == []          # previewing calls nothing
    out = client.post(f"/sheets/{sheet.id}/columns/{topic['id']}/fill", json=body).json()
    assert out["filled"] == 20 and len(scripted.calls) == 1
    page = client.get(f"/sheets/{sheet.id}/rows?limit=5").json()
    assert page["changed"]["3"][topic["id"]]["origin"].startswith("model:")


def test_with_no_model_set_up_the_plan_says_so_and_a_fill_is_refused(env, monkeypatch):
    import aughor.llm.provider as provider_mod
    from aughor.sheets import model_columns, service

    def no_model(role="coder", **_):
        raise RuntimeError("no backend is configured")
    monkeypatch.setattr(provider_mod, "get_provider", no_model)
    sheet, topic = _topic(env)
    plan = model_columns.plan(sheet, topic.id, conditions=_low(), sort=[])
    assert plan["model"] == "" and plan["cost"] == "no model is set up here, so nothing can be filled"
    with pytest.raises(service.Refused, match="no model is set up here, so nothing can be filled"):
        model_columns.fill(sheet, topic.id, conditions=_low(), sort=[], by="user:ana")
