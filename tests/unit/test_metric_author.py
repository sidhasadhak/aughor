"""The model writes a metric's statement from the editor's fields (2026-09-26).

Pinned: the framing carries the metric in question (name, label, definition, filters, tables,
dimensions, wrong readings) and the rules of a metric's statement; what comes back is checked
and never rewritten — grouped, limited or multi-column is refused with the reason, an
expression is wrapped over the definition's table exactly as the value path runs it, and an
expression with no table is refused; the door spends one call, binds a trace, and says why
when nothing usable came back.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from aughor.api import app
from aughor.semantic import metric_author as ma

client = TestClient(app)

BRIEF = ma.MetricBrief(
    name="return_rate", label="Return rate", definition="The share of sold lines that the customer sent back.",
    unit="ratio", tables=["order_items"], filters=["status <> 'Cancelled'"], dimensions=["country"],
    wrong_usage=["Reading it over a population that still contains cancelled lines"],
)


class _Writer:
    def __init__(self, sql: str):
        self.sql, self.calls = sql, []

    def write(self, question: str, extra_context: str = "") -> str:
        self.calls.append((question, extra_context))
        return self.sql


class _Db:
    dialect = "duckdb"

    def close(self):
        pass


def test_the_framing_carries_the_metric_in_question_and_the_rules():
    question, context = ma.framing(BRIEF)
    assert question == "The value of the metric 'Return rate': The share of sold lines that the customer sent back."
    for needle in ("METRIC: Return rate (column name: return_rate) — unit: ratio",
                   "DEFINITION: The share of sold lines that the customer sent back.",
                   "FILTERS THAT ARE PART OF THE DEFINITION (apply every one): status <> 'Cancelled'",
                   "TABLES THE DEFINITION NAMES: order_items",
                   "DIMENSIONS IT MAY LATER BE SLICED BY (do NOT group by them): country",
                   "READINGS THAT ARE WRONG (the statement must not compute these): Reading it over",
                   "ONE row with ONE column named return_rate",
                   "No GROUP BY, no ORDER BY, no LIMIT, and no date or time filter"):
        assert needle in context, needle
    _, bare = ma.framing(ma.MetricBrief(name="n"))
    assert "DEFINITION: (none written — read the label)" in bare and "none — choose from the SCHEMA" in bare
    assert "DIMENSIONS" not in bare and "READINGS THAT ARE WRONG" not in bare


def test_what_the_model_wrote_is_checked_not_rewritten():
    ok, why = ma.check("SELECT SUM(x) / NULLIF(COUNT(*), 0) AS return_rate FROM order_items;", "return_rate")
    assert ok == "SELECT SUM(x) / NULLIF(COUNT(*), 0) AS return_rate FROM order_items" and why == ""
    cted, _ = ma.check("WITH r AS (SELECT 1 AS v) SELECT SUM(v) AS n FROM r", "n")
    assert cted is not None
    assert ma.check("", "n") == (None, "the model returned no SQL")
    assert ma.check("SUM(x)", "n") == (None, "the model wrote an expression, not a statement")
    assert ma.check("SELECT country, SUM(x) AS n FROM t GROUP BY country", "n")[1] == "it groups rows — a metric's statement returns one row"
    assert ma.check("SELECT SUM(x) AS n FROM t LIMIT 10", "n")[1].startswith("it limits rows")
    assert ma.check("SELECT SUM(x) AS n, COUNT(*) AS c FROM t", "n")[1] == "it selects 2 columns — one column, n, is the metric's value"
    assert ma.check("SELECT FROM WHERE", "n")[1].startswith("the model's statement does not parse as duckdb: ")
    # BigQuery's backticks parse under BigQuery, not under DuckDB — the connection's dialect is the reader.
    bq = "WITH s AS (SELECT session_id FROM `events`) SELECT COUNT(*) AS n FROM s"
    assert ma.check(bq, "n", "bigquery")[1] == ""
    assert ma.check(bq, "n", "duckdb")[1].startswith("the model's statement does not parse as duckdb")


def test_write_statement_spends_the_writer_once_and_wraps_only_an_expression_with_a_table(monkeypatch):
    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role: type("P", (), {"model": "coder-x"})())
    w = _Writer("SELECT SUM(CASE WHEN returned_at IS NOT NULL THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0) AS return_rate FROM order_items")
    out = ma.write_statement(BRIEF, _Db(), writer=w)
    assert out["sql"].startswith("SELECT SUM(CASE") and out["refused"] == "" and out["note"] == "" and out["model"] == "coder-x"
    assert len(w.calls) == 1 and "DEFINITION: The share of sold lines" in w.calls[0][1]
    # An expression over a declared table: wrapped as the value path runs it, and said.
    out = ma.write_statement(BRIEF, _Db(), writer=_Writer("SUM(CASE WHEN returned_at IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*)"))
    assert out["sql"] == ("SELECT (SUM(CASE WHEN returned_at IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*)) AS return_rate "
                          "FROM order_items WHERE status <> 'Cancelled'")
    assert out["note"].startswith("the model wrote an expression; wrapped over order_items")
    # An expression with no table to wrap over: the text is handed back WITH the finding.
    out = ma.write_statement(ma.MetricBrief(name="n"), _Db(), writer=_Writer("COUNT(*)"))
    assert out["sql"] == "COUNT(*)" and out["refused"] == "the model wrote an expression, not a statement"
    # A grouped query: shown as written, the verdict beside it — never hidden, never rewritten.
    out = ma.write_statement(BRIEF, _Db(), writer=_Writer("SELECT country, SUM(x) AS return_rate FROM order_items GROUP BY country;"))
    assert out["sql"] == "SELECT country, SUM(x) AS return_rate FROM order_items GROUP BY country"
    assert out["refused"] == "it groups rows — a metric's statement returns one row"
    # Nothing at all: empty, said.
    out = ma.write_statement(BRIEF, _Db(), writer=_Writer("   "))
    assert out["sql"] == "" and out["refused"] == "the model returned no SQL"


def test_the_door_writes_once_binds_a_trace_and_says_why_not(monkeypatch):
    seen: dict = {}

    class FakeWriter:
        def __init__(self, db):
            seen["db"] = db

        def write(self, question, extra_context=""):
            from aughor.telemetry import current_trace_id
            seen["trace"] = current_trace_id()
            seen["context"] = extra_context
            return seen["answer"]

    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: _Db() if cid == "c1" else (_ for _ in ()).throw(KeyError(cid)))
    monkeypatch.setattr("aughor.sql.writer.SqlWriter", FakeWriter)
    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role: type("P", (), {"model": "coder-x"})())
    body = {"connection": "c1", "name": "return_rate", "label": "Return rate",
            "definition": "The share of sold lines sent back.", "tables": ["order_items"]}
    seen["answer"] = "SELECT SUM(r) / NULLIF(COUNT(*), 0) AS return_rate FROM order_items"
    r = client.post("/metrics/generate-sql", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["sql"] == seen["answer"] and r.json()["model"] == "coder-x"
    assert r.json()["trace_id"] == seen["trace"] and len(seen["trace"]) == 32
    assert "DEFINITION: The share of sold lines sent back." in seen["context"]
    assert r.json()["refused"] == ""
    seen["answer"] = "SELECT country, SUM(r) AS return_rate FROM order_items GROUP BY country"
    r = client.post("/metrics/generate-sql", json=body)
    assert r.status_code == 200
    assert r.json()["sql"] == seen["answer"]
    assert r.json()["refused"] == "it groups rows — a metric's statement returns one row"
    seen["answer"] = ""
    r = client.post("/metrics/generate-sql", json=body)
    assert r.status_code == 422 and r.json()["detail"] == "No statement written: the model returned no SQL."
    assert client.post("/metrics/generate-sql", json={**body, "name": " "}).status_code == 422
    assert client.post("/metrics/generate-sql", json={**body, "connection": "nope"}).status_code == 404
