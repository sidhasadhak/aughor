"""Arc AP-8 — variables on a dashboard, as the server holds them (ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md
§9.2).

A value comes from its author, the reader on the page, a set's count or a property of the object a reader chose; a set
compares any value as its kind allows; a query of a person's own reads a value as ``{{name}}``, and the engine binds it —
it is never pasted into the statement. While ``cockpit.variables`` is off a spec that says any of it is refused, and a
query that reads a value is refused with why. Every figure a bound query returns is checked against the rows themselves,
filtered in Python.
"""
from __future__ import annotations

import datetime as dt
import shutil
import uuid

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.cockpit import pieces, queries as Q, validate as V, variables, versions, wiring
from aughor.cockpit.home import Home
from aughor.db.connection import open_connection
from aughor.demo.setup import _seed_ecommerce
from aughor.kernel.flags import flag_overrides
from tests.unit.test_cockpit_canvas import ME, volumes  # noqa: F401 — the fixture, by name
from tests.unit.test_cockpit_wiring import ALL, _desk, _flags, _graph

needs_rules = pytest.mark.skipif(shutil.which("node") is None or not V._BUNDLE.exists(),
                                 reason="the dashboard's rules need node + validate.bundle.mjs")
CONN = "variables-t"
ROWS = ("SELECT o.order_id, c.country, o.order_date, o.total_amount FROM ecommerce.orders o "
        "JOIN ecommerce.customers c ON c.customer_id = o.customer_id")
ASKED = (ROWS + " WHERE c.country = {{country}} AND o.order_date >= {{since}} AND o.total_amount >= {{least}}")
VALUES = {"country": {"kind": "text", "value": "DE"}, "since": {"kind": "date", "value": "2024-01-01"},
          "least": {"kind": "number", "value": 150}}


class _Borrowed:
    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("variables") / "sales.duckdb"
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.close()
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id=CONN)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def rows(db):
    """Every row, as Python reads them: the oracle a bound query is checked against."""
    out = Q.execute(db, ROWS, max_rows=10_000, seconds=60)
    assert out["error"] is None
    names = [c["name"] for c in out["columns"]]
    return [dict(zip(names, r)) for r in out["rows"]]


def _asked(rows, country, since, least):
    return sorted(r["order_id"] for r in rows if r["country"] == country
                  and dt.date.fromisoformat(str(r["order_date"])[:10]) >= since and float(r["total_amount"]) >= least)


# ── bound, never pasted in ────────────────────────────────────────────────────────────────────────────────────────────

def test_each_value_a_query_reads_becomes_the_sql_editor_s_own_placeholder_and_a_typed_bind_value():
    sql, params = Q.bind(ASKED, VALUES)
    assert "{{" not in sql and sql.endswith("c.country = :v_country AND o.order_date >= :v_since AND o.total_amount >= :v_least")
    assert params == {"v_country": "DE", "v_since": dt.date(2024, 1, 1), "v_least": 150}
    assert Q.params_of("SELECT {{a}}, {{ b }}, {{a}}") == ["a", "b"] and Q.engine_name("chosen-order") == "v_chosen_order"
    # days and a whole number bind as a whole number; a part as a part
    assert Q.bind("SELECT {{w}}", {"w": {"kind": "days", "value": 14.0}})[1] == {"v_w": 14}
    assert isinstance(Q.bind("SELECT {{w}}", {"w": {"kind": "days", "value": 14.0}})[1]["v_w"], int)
    assert Q.bind("SELECT {{n}}", {"n": {"kind": "number", "value": "2.5"}})[1] == {"v_n": 2.5}
    # the tables a query reads are read past its values
    assert Q.tables_of(ASKED, "duckdb") == ["orders", "customers"]


@pytest.mark.parametrize("sql,values,says", [
    ("SELECT {{country}}", {}, "this dashboard holds no value of that name"),
    ("SELECT {{a}}, {{b}}", {}, "{{a}}, {{b}}, and this dashboard holds no value of those names"),
    ("SELECT {{w}}", {"w": {"kind": "days", "value": None}}, "which holds nothing yet"),
    ("SELECT {{w}}", {"w": {"kind": "text", "value": ""}}, "which holds nothing yet"),
    ("SELECT {{w}}", {"w": {"kind": "days", "value": 2.5}}, "as a whole number of days"),
    ("SELECT {{w}}", {"w": {"kind": "days", "value": 0}}, "as a whole number of days"),
    ("SELECT {{n}}", {"n": {"kind": "number", "value": True}}, "as a number"),
    ("SELECT {{n}}", {"n": {"kind": "number", "value": "many"}}, "as a number"),
    ("SELECT {{d}}", {"d": {"kind": "date", "value": "11/10/2026"}}, "a day, written 2026-10-11"),
    ("SELECT {{t}}", {"t": {"kind": "text", "value": "x" * 121}}, "at most 120 characters"),
    ("SELECT {{t}}", {"t": {"kind": "text", "value": 3}}, "at most 120 characters"),
    ("SELECT {{t}}", {"t": {"kind": "table", "value": "a"}}, "a value is days, a number, words, a day, yes or no, or a list"),
    # Arc AP-8c — yes or no is a boolean, never a word for one; a list holds 1 to 30 numbers or words
    ("SELECT {{y}}", {"y": {"kind": "yesno", "value": "yes"}}, "as yes or no"),
    ("SELECT {{y}}", {"y": {"kind": "yesno", "value": 1}}, "as yes or no"),
    ("SELECT {{l}}", {"l": {"kind": "list", "value": "a"}}, "as a list of 1 to 30 numbers or words"),
    ("SELECT {{l}}", {"l": {"kind": "list", "value": []}}, "which holds nothing yet"),
    ("SELECT {{l}}", {"l": {"kind": "list", "value": ["a"] * 31}}, "as a list of 1 to 30 numbers or words"),
    ("SELECT {{l}}", {"l": {"kind": "list", "value": ["a", True]}}, "as a list of 1 to 30 numbers or words"),
    ("SELECT {{l}}", {"l": {"kind": "list", "value": ["a", " "]}}, "as a list of 1 to 30 numbers or words"),
    ("SELECT {{l}}", {"l": {"kind": "list", "value": ["a", {"b": 1}]}}, "as a list of 1 to 30 numbers or words"),
    ("SELECT '{{t}}'", {"t": {"kind": "text", "value": "a"}}, "{{t}} is written inside quotes or a comment"),
    ("SELECT 1 -- {{t}}", {"t": {"kind": "text", "value": "a"}}, "inside quotes or a comment"),
    ("SELECT `{{t}}` FROM x", {"t": {"kind": "text", "value": "a"}}, "inside quotes or a comment"),
])
def test_a_value_the_query_cannot_bind_as_it_reads_it_is_refused_in_words(sql, values, says):
    # whatever stops it is a refusal in words — never an error a door would answer with a 500
    with pytest.raises(Exception) as e:
        Q.bind(sql, values)
    assert isinstance(e.value, Q.Refused) and says in str(e.value), repr(e.value)


def test_a_bound_query_returns_exactly_the_rows_its_values_ask_and_a_value_never_changes_the_statement(db, rows):
    sql, params = Q.bind(ASKED, VALUES)
    shown = Q.Shown.model_validate({"as": "table"})
    columns = Q.probe(db, sql, seconds=60, params=params)["columns"]
    ran = Q.run(db, sql, shown, columns, seconds=60, params=params)
    assert ran["error"] is None
    got = sorted(r[0] for r in ran["shown"]["rows"])
    want = _asked(rows, "DE", dt.date(2024, 1, 1), 150)
    assert got == want[:Q.TABLE_ROWS] and 0 < len(want)
    # summed around, the platform's figure is the oracle's
    fig = Q.Shown.model_validate({"as": "figure", "series": [{"column": "total_amount", "agg": "sum"}]})
    total = Q.run(db, sql, fig, columns, seconds=60, params=params)["shown"]["value"]
    assert total == pytest.approx(sum(float(r["total_amount"]) for r in rows if r["order_id"] in set(want)))
    # what would end the statement were it pasted in is a word the engine compares, and matches nothing
    evil, p = Q.bind(ASKED, {**VALUES, "country": {"kind": "text", "value": "x' OR '1'='1"}})
    assert Q.run(db, evil, shown, columns, seconds=60, params=p)["shown"]["rows"] == []


# ── over HTTP: preview, keep, run ─────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(db, monkeypatch):
    from aughor.api import app
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda conn, *a, **k: _Borrowed(db))
    monkeypatch.setattr("aughor.cockpit.pieces.served_graph", lambda conn: None)
    return TestClient(app)


@pytest.fixture
def on():
    with flag_overrides({"cockpit.composed": True, "cockpit.queries": True, "cockpit.variables": True}):
        yield


TABLE = {"as": "table"}


def test_off_a_query_that_reads_a_value_is_refused_and_one_that_reads_none_runs_as_before(client):
    conn = f"v{uuid.uuid4().hex[:6]}"
    with flag_overrides({"cockpit.composed": True, "cockpit.queries": True, "cockpit.variables": False}):
        r = client.post("/cockpits/queries/preview", params={"connection_id": conn},
                        json={"sql": ASKED, "shown": TABLE, "values": VALUES})
        assert r.json()["refused"] == ["The query reads {{country}}, {{since}}, {{least}} — the dashboard's values — and "
                                       "variables are off on this install."]
        r = client.post("/cockpits/queries", params={"connection_id": conn}, json={"sql": ASKED, "values": VALUES})
        assert r.status_code == 422 and "variables are off" in r.json()["detail"]["refused"][0]
        plain = client.post("/cockpits/queries/preview", params={"connection_id": conn}, json={"sql": ROWS, "shown": TABLE}).json()
        assert plain["refused"] == [] and plain["reads"] == []


def test_a_preview_binds_the_values_it_is_sent_and_says_which_it_reads(client, on, rows):
    conn = f"v{uuid.uuid4().hex[:6]}"
    body = client.post("/cockpits/queries/preview", params={"connection_id": conn},
                       json={"sql": ASKED, "shown": TABLE, "values": VALUES}).json()
    assert body["refused"] == [] and body["reads"] == ["country", "since", "least"]
    assert body["tables"] == ["orders", "customers"]
    want = _asked(rows, "DE", dt.date(2024, 1, 1), 150)
    assert sorted(r[0] for r in body["shown"]["rows"]) == want[:Q.TABLE_ROWS]
    missing = client.post("/cockpits/queries/preview", params={"connection_id": conn},
                          json={"sql": ASKED, "shown": TABLE, "values": {"country": VALUES["country"]}}).json()
    assert missing["refused"] == ["The query reads {{since}}, {{least}}, and this dashboard holds no value of those names."]


def test_a_kept_query_keeps_its_values_by_name_and_each_run_binds_the_page_s_own(client, on, rows):
    from aughor.dashboard.store import get_card
    conn = f"v{uuid.uuid4().hex[:6]}"
    fig = {"as": "figure", "series": [{"column": "total_amount", "agg": "sum"}]}
    r = client.post("/cockpits/queries", params={"connection_id": conn}, json={"sql": ASKED, "shown": fig, "values": VALUES})
    assert r.status_code == 201, r.text
    card = r.json()["card"]
    assert card["sql"] == ASKED                                               # the statement, never a value
    for country in ("DE", "BR"):
        run = client.post(f"/cards/{card['id']}/run", json={"values": {**VALUES, "country": {"kind": "text", "value": country}}}).json()
        want = _asked(rows, country, dt.date(2024, 1, 1), 150)
        assert run["error"] is None
        assert run["shown"]["value"] == pytest.approx(sum(float(x["total_amount"]) for x in rows if x["order_id"] in set(want)))
    # a figure read for one reader's values is theirs: the card's standing value is not moved by it
    assert get_card(card["id"]).refresh.last_value is None
    bare = client.post(f"/cards/{card['id']}/run").json()
    assert bare["shown"] is None and bare["error"] == ("The query reads {{country}}, {{since}}, {{least}}, and this dashboard "
                                                       "holds no value of those names.")
    with flag_overrides({"cockpit.variables": False}):
        off = client.post(f"/cards/{card['id']}/run", json={"values": VALUES}).json()
        assert off["shown"] is None and "variables are off on this install" in off["error"]


def test_a_query_reading_values_is_read_as_it_says_for_a_range_and_says_why(client, on, monkeypatch):
    from aughor.briefing.ranges import RangeSpec
    conn = f"v{uuid.uuid4().hex[:6]}"
    card = client.post("/cockpits/queries", params={"connection_id": conn},
                       json={"sql": ASKED, "shown": TABLE, "values": VALUES}).json()["card"]
    d = dt.date(2024, 6, 1)
    spec = RangeSpec(preset="last_7_days", start=d, end=d + dt.timedelta(days=7), previous_start=d - dt.timedelta(days=7),
                     previous_end=d, last_year_start=None, last_year_end=None, as_of=d, lag_days=0, lag_source="test")
    monkeypatch.setattr("aughor.routers.dashboard._card_range", lambda *a, **k: spec)
    run = client.post(f"/cards/{card['id']}/run", params={"preset": "last_7_days"}, json={"values": VALUES}).json()
    assert run["error"] is None and run["scoped"]["standing"] is True
    assert run["scoped"]["why"] == "It reads the dashboard's own values, so it is read as its query says, not cut to the range."


# ── what the server checks before a cockpit is kept ───────────────────────────────────────────────────────────────────

def _valued(**values) -> dict:
    """The dispatch desk, its values as given."""
    return _desk(**{"values": values})


def test_only_what_variables_say_is_refused_off_and_a_desk_of_the_author_s_days_never_is(monkeypatch):
    reader = _valued(window={"label": "Window", "kind": "days", "value": 14, "from": {"by": "reader", "options": [7, 14]}})
    day = _valued(window={"label": "Window", "kind": "days", "value": 14}, since={"label": "Since", "kind": "date", "value": "2024-01-01"})
    compares = _desk(**{"values.least": {"label": "Least", "kind": "number", "value": 100},
                        "sets.big": {"label": "Big", "entity": "order", "where": [{"path": "total_amount", "op": ">=", "value_from": "least"}]}})
    assert variables.uses(reader) == ["the value 'window'"]
    assert variables.uses(day) == ["the value 'since'"]
    assert variables.uses(compares) == ["the set 'big'"]
    assert variables.uses(_desk()) == []                                      # days the author set, counted back: as before
    _flags(monkeypatch, set())
    assert variables.refused_off(_desk()) == []
    said = variables.refused_off(reader)
    assert said == ["The dashboard reads variables — the value 'window' come from the reader, a count or a chosen object, "
                    "compare a value in a set, or read a set's linked objects or another set whole — and variables are "
                    "off on this install."]
    # Arc AP-8b — a set's linked objects, and a set combined with another, are variables' too
    traversed = _desk(**{"sets.theirs": {"label": "Their customers", "from": "active", "traverse": {"link": "customer", "entity": "customer"}}})
    combined = _desk(**{"sets.lone": {"label": "Lone", "from": "placed", "combine": {"op": "but_not", "set": "active"}}})
    assert variables.uses(traversed) == ["the set 'theirs'"] and variables.uses(combined) == ["the set 'lone'"]
    _flags(monkeypatch, {variables.FLAG})
    assert variables.refused_off(reader) == []


def test_a_value_read_off_a_chosen_object_names_a_property_its_entity_has(monkeypatch):
    graph = _graph()
    read = {"values": {"country": {"by": "chosen", "choice": "chosen-order", "entity": "order", "path": "status"},
                       "nowhere": {"by": "chosen", "choice": "chosen-order", "entity": "order", "path": "colour"},
                       "elsewhere": {"by": "chosen", "choice": "x", "entity": "spaceship", "path": "status"},
                       "counted": {"by": "count", "set": "placed"}}}
    said = variables.not_resolved("c", {}, graph=graph, wiring=read)
    assert said == ['The value "nowhere" reads colour of the chosen Order, and Order has no property colour.',
                    'The value "elsewhere" reads status of an object of spaceship, which this connection does not serve.']
    assert variables.not_resolved("c", {}, graph=None, wiring={"values": {}}) == []


@needs_rules
def test_the_server_reads_each_value_as_the_web_does_and_a_set_reading_a_count_compiles_with_a_stand_in(monkeypatch):
    spec = _desk(**{
        "values.waiting-count": {"label": "Waiting count", "kind": "number", "from": {"by": "count", "set": "active"}},
        "values.status": {"label": "Its status", "kind": "text", "from": {"by": "chosen", "choice": "chosen-order", "path": "status"}},
        "values.least": {"label": "Least", "kind": "number", "value": 100, "from": {"by": "reader"}},
        "sets.big": {"label": "Big", "entity": "order", "where": [
            {"path": "item_count", "op": ">=", "value_from": "waiting-count"},
            {"path": "status", "op": "=", "value_from": "status"},
            {"path": "total_amount", "op": ">=", "value_from": "least"}]},
    })
    read = wiring.read(spec)
    assert read["values"] == {"waiting-count": {"by": "count", "set": "active"},
                              "status": {"by": "chosen", "choice": "chosen-order", "path": "status", "entity": "order"},
                              "least": {"by": "reader"}}
    # the reader's value is the one it starts from; a count and a chosen object's stand in by a value of their kind
    assert read["sets"]["big"]["filters"] == [{"path": "item_count", "op": ">=", "value": 1},
                                              {"path": "status", "op": "=", "value": "probe"},
                                              {"path": "total_amount", "op": ">=", "value": 100}]


@needs_rules
def test_the_keep_door_refuses_variables_while_off_a_property_the_entity_lacks_and_a_query_whose_value_is_gone(
        volumes, monkeypatch):  # noqa: F811
    from aughor.cockpit import cards
    from aughor.dashboard.models import DashboardCard
    monkeypatch.setattr(pieces, "accepted_edits", lambda conn: [])
    tag = uuid.uuid4().hex[:6]
    home = Home(f"vars{tag}", ME, f"desk-{tag}")
    graph = _graph()
    monkeypatch.setattr(pieces, "served_graph", lambda conn: graph)

    def keep(s):
        return versions.keep(home, s, approved_by="user:amit", source="a person's own hand", written_by_model=False)
    status = {"label": "Its status", "kind": "text", "from": {"by": "chosen", "choice": "chosen-order", "path": "status"}}
    spec = _desk(**{"values.status": status})
    _flags(monkeypatch, ALL)
    off = keep(spec)
    assert off.status == "refused" and "variables are off on this install" in " ".join(off.sentences), off.sentences
    assert versions.latest(home) is None
    _flags(monkeypatch, ALL | {variables.FLAG})
    wrong = keep(_desk(**{"values.status": {**status, "from": {**status["from"], "path": "colour"}}}))
    assert not wrong.kept and "Order has no property colour" in " ".join(wrong.sentences), wrong.sentences
    kept = keep(spec)
    assert kept.kept, kept.sentences
    # a query of the person's own placed on the cockpit reads {{country}}; the cockpit must hold a value of that name
    card = cards.place(home, DashboardCard(connection_id=home.connection_id, source="authored", title="By country",
                                           sql="SELECT 1 WHERE 'a' = {{country}}", render={"shown": {"as": "table"}}))
    placed = _desk(**{"values.status": status})
    placed["elements"]["desk"]["children"].append("q")
    placed["elements"]["q"] = {"type": "Card", "props": {"card": card.id}, "children": []}
    gone = keep(placed)
    assert not gone.kept and 'The card "By country" reads {{country}}, and this dashboard holds no value of that name.' \
        in gone.sentences, gone.sentences
    placed["values"]["country"] = {"label": "Country", "kind": "text", "value": "China", "from": {"by": "reader"}}
    assert keep(placed).kept



# ── Arc AP-8b — a set read whole ──────────────────────────────────────────────────────────────────────────────────

@needs_rules
def test_a_set_s_linked_objects_and_a_combined_set_are_read_as_the_web_reads_them_and_compiled_before_a_keep(
        volumes, monkeypatch):  # noqa: F811
    monkeypatch.setattr(pieces, "accepted_edits", lambda conn: [])
    graph = _graph()
    monkeypatch.setattr(pieces, "served_graph", lambda conn: graph)
    spec = _desk(**{"sets.theirs": {"label": "Their customers", "from": "active", "traverse": {"link": "customer", "entity": "customer"}},
                    "sets.lone": {"label": "Placed, not active", "from": "placed", "combine": {"op": "but_not", "set": "active"}}})
    read = wiring.read(spec)
    window = {"path": "order_date", "op": "in_last", "value": 14}
    assert read["sets"]["theirs"] == {"entity": "customer", "segment": "", "filters": [
        {"path": "", "op": "in_set", "sets": [{"entity": "order", "segment": "active_orders", "filters": [window], "via": "customer"}]}]}
    assert read["sets"]["lone"] == {"entity": "order", "segment": "", "filters": [
        window, {"path": "", "op": "not_in_set", "sets": [{"entity": "order", "segment": "active_orders", "filters": [window]}]}]}
    assert wiring.not_resolved("c", spec, graph=graph, wiring=read) == []
    # a link that reaches other objects than the set says it holds is refused by the door, in its words
    wrong = _desk(**{"sets.theirs": {"label": "Their lines", "from": "active", "traverse": {"link": "customer", "entity": "order_item"}}})
    said = " ".join(wiring.not_resolved("c", wrong, graph=graph))
    assert "reaches Customer" in said and "not OrderItem" in said, said
    tag = uuid.uuid4().hex[:6]
    home = Home(f"whole{tag}", ME, f"desk-{tag}")

    def keep(s):
        return versions.keep(home, s, approved_by="user:amit", source="a person's own hand", written_by_model=False)
    _flags(monkeypatch, ALL)
    off = keep(spec)
    assert not off.kept and "read a set's linked objects or another set whole" in " ".join(off.sentences)
    _flags(monkeypatch, ALL | {variables.FLAG})
    assert keep(spec).kept
