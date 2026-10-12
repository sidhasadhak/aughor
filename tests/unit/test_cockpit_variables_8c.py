"""Arc AP-8c — the rest of the variables (ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §9.2).

A value may now be yes or no, or a list; and it may come from a property summed over a set's objects, or from the first
value of a query of the person's own the cockpit places (every row's, for a list). A query binds yes or no as the
engine's boolean and a list one placeholder per item — `country IN ({{countries}})` — never pasted into its statement.
Before a spec is kept the server checks what only it knows: that a sum's property is one the object door can add up, and
that a value's query is a query of the person's own the cockpit places that does not read the value back.
"""
from __future__ import annotations

import pytest

from aughor.cockpit import queries as Q, variables
from tests.unit.test_cockpit_variables import ROWS, db, rows  # noqa: F401 — the fixtures, by name
from tests.unit.test_cockpit_wiring import _desk, _flags, _graph


def test_yes_or_no_binds_as_a_boolean_and_a_list_one_placeholder_per_item():
    sql, params = Q.bind("SELECT 1 WHERE {{late}} AND c IN ({{countries}}) AND d IN ({{countries}})",
                         {"late": {"kind": "yesno", "value": True}, "countries": {"kind": "list", "value": ["DE", "FR", 3.0]}})
    assert sql == ("SELECT 1 WHERE :v_late AND c IN (:v_countries_0, :v_countries_1, :v_countries_2) "
                   "AND d IN (:v_countries_0, :v_countries_1, :v_countries_2)")
    assert params == {"v_late": True, "v_countries_0": "DE", "v_countries_1": "FR", "v_countries_2": 3}
    assert isinstance(params["v_countries_2"], int)
    assert Q.bind("SELECT {{late}}", {"late": {"kind": "yesno", "value": False}})[1] == {"v_late": False}


def test_a_bound_list_returns_exactly_the_rows_it_names(db, rows):  # noqa: F811
    for countries in (["DE"], ["DE", "FR"], ["DE", "FR", "nowhere"]):
        sql, params = Q.bind(ROWS + " WHERE c.country IN ({{countries}})", {"countries": {"kind": "list", "value": countries}})
        assert all(f"'{c}'" not in sql for c in countries) and "{{" not in sql   # bound, never pasted in
        shown = Q.Shown.model_validate({"as": "table"})
        columns = Q.probe(db, sql, seconds=60, params=params)["columns"]
        ran = Q.run(db, sql, shown, columns, seconds=60, params=params)
        assert ran["error"] is None
        want = sorted(r["order_id"] for r in rows if r["country"] in countries)
        assert sorted(r[0] for r in ran["shown"]["rows"]) == want[:Q.TABLE_ROWS] and want


def test_yes_or_no_a_list_a_sum_and_a_query_are_variables_and_refused_while_off(monkeypatch):
    yes = _desk(**{"values.late": {"label": "Late only", "kind": "yesno", "value": True}})
    listed = _desk(**{"values.countries": {"label": "Countries", "kind": "list", "value": ["DE"]}})
    summed = _desk(**{"values.spend": {"label": "Spend", "kind": "number", "from": {"by": "sum", "set": "placed", "path": "total_amount"}}})
    queried = _desk(**{"values.top": {"label": "Top", "kind": "text", "from": {"by": "query", "card": "c1"}}})
    assert [variables.uses(s) for s in (yes, listed, summed, queried)] == [
        ["the value 'late'"], ["the value 'countries'"], ["the value 'spend'"], ["the value 'top'"]]
    _flags(monkeypatch, set())
    assert variables.refused_off(listed) and variables.refused_off(summed)
    _flags(monkeypatch, {variables.FLAG})
    assert variables.refused_off(listed) == []


def test_a_sum_adds_up_a_number_its_set_s_objects_have(monkeypatch):
    monkeypatch.setattr("aughor.cockpit.pieces.accepted_edits", lambda conn: [])
    read = {"values": {"spend": {"by": "sum", "set": "placed", "entity": "order", "path": "total_amount"},
                       "colours": {"by": "sum", "set": "placed", "entity": "order", "path": "colour"},
                       "words": {"by": "sum", "set": "placed", "entity": "order", "path": "status"},
                       "nowhere": {"by": "sum", "set": "x", "entity": "spaceship", "path": "fuel"}}}
    said = variables.not_resolved("c", {}, graph=_graph(), wiring=read)
    assert len(said) == 3, said
    assert said[0].startswith('The value "colours" sums colour over the set "placed": ')
    assert said[1].startswith('The value "words" sums status over the set "placed": ')
    assert said[2] == 'The value "nowhere" reads fuel of an object of spaceship, which this connection does not serve.'


@pytest.fixture
def cards(volumes):  # noqa: F811 — the card store, kept apart
    from aughor.dashboard.models import DashboardCard
    from aughor.dashboard.store import upsert_card
    made = {}
    for key, sql, render in (("mine", "SELECT country FROM orders ORDER BY 1 LIMIT 1", {"shown": {"as": "table"}}),
                             ("loose", "SELECT 1", {"shown": {"as": "figure"}}),
                             ("metric", "SELECT 2", {}),
                             ("self", "SELECT {{top}}", {"shown": {"as": "figure"}})):
        made[key] = upsert_card(DashboardCard(connection_id="c", scope="cockpit", scope_ref="desk", title=key, sql=sql,
                                              render=render)).id
    return made


from tests.unit.test_cockpit_canvas import volumes  # noqa: E402,F401 — the fixture, by name


def test_a_value_s_query_is_one_of_the_person_s_own_the_cockpit_places_and_never_reads_the_value_back(cards):
    def spec(card: str, *placed: str) -> dict:
        s = _desk(**{"values.top": {"label": "Top", "kind": "text", "from": {"by": "query", "card": card}}})
        s["elements"]["desk"]["children"] += [f"card-{i}" for i, _ in enumerate(placed)]
        s["elements"].update({f"card-{i}": {"type": "Card", "props": {"card": c}, "children": []} for i, c in enumerate(placed)})
        return s

    def said(s: dict) -> list[str]:
        return variables.not_resolved("c", s, graph=_graph(), wiring={"values": {"top": {"by": "query", "card": s["values"]["top"]["from"]["card"]}}})

    assert said(spec(cards["mine"], cards["mine"])) == []
    not_ours = ['The value "top" reads the first value of a query, and that is not a query of yours this cockpit places.']
    assert said(spec(cards["loose"], cards["mine"])) == not_ours                     # not placed
    assert said(spec(cards["metric"], cards["metric"])) == not_ours                  # placed, not a query of one's own
    assert said(spec("gone", "gone")) == not_ours                                     # no such card
    assert said(spec(cards["self"], cards["self"])) == [
        'The value "top" reads a query that reads {{top}} itself: it would wait on itself.']
