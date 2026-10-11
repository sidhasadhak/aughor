"""Arc AP-4 — the object door's `contains`: the objects whose text holds a reader's words, case aside — a search box's
condition (ROADMAP §3.57). The words carry no pattern of their own, so they mean the same in every dialect; a date or a
number holds no words and is refused; and empty words are refused rather than read as everything."""
from __future__ import annotations

import json

import pytest

from aughor.ontology.models import OntologyGraph
from aughor.semantic import object_query as oq
from tests.unit.test_object_bindings import GRAPH


@pytest.fixture
def graph() -> OntologyGraph:
    return OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


def _sql(graph, value, path="status", dialect="duckdb"):
    return oq.compile_object_query({"object_type": "Order", "measures": [{"name": "n", "agg": "count"}],
                                    "filters": [{"path": path, "op": "contains", "value": value}]}, graph, dialect=dialect).sql


def test_words_are_looked_for_case_aside(graph):
    sql = _sql(graph, "Ship")
    assert "LIKE '%ship%'" in sql and "LOWER(" in sql


def test_a_pattern_in_the_words_is_read_as_spaces_and_quotes_are_escaped(graph):
    assert "LIKE '%a b c%'" in _sql(graph, "a%b_c")
    assert "LIKE '%o''brien%'" in _sql(graph, "O'Brien")


def test_it_renders_for_bigquery_too(graph):
    sql = _sql(graph, "ship", dialect="bigquery")
    assert "LIKE '%ship%'" in sql and "STRING" in sql.upper()


@pytest.mark.parametrize("path", ["order_date", "total_amount"])
def test_a_date_or_a_number_holds_no_words(graph, path):
    with pytest.raises(oq.ObjectQueryRefused, match="holds no text"):
        _sql(graph, "x", path=path)


@pytest.mark.parametrize("value", ["", "   ", "%%", None, 7])
def test_empty_words_are_refused_rather_than_read_as_everything(graph, value):
    with pytest.raises(oq.ObjectQueryRefused, match="needs the words to look for"):
        _sql(graph, value)


def test_too_many_words_are_refused(graph):
    with pytest.raises(oq.ObjectQueryRefused, match="at most 120 characters"):
        _sql(graph, "x" * 121)
