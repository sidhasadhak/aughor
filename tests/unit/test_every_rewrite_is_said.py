"""PENDING item 23 — every rewrite of the quick path's query is said, and so is kept as a pair.

The quick path ran two rewrites in silence: the preflight repair (the shared executor has always said it, the quick
path dropped its receipt) and the repair adopted after a failed or suspicious first run. The query shown changed with
no word of why, and the before-and-after — a query that went wrong and the one that ran clean — was kept nowhere,
though it is the one labelled pair the product makes on every answer it repairs. A receipt is what the answer's
envelope files, and what `export_repair_pairs` reads.

Driven through the REAL `_stream_chat` over a DuckDB connection with the faux model.
"""
from __future__ import annotations

import asyncio
import json

import duckdb
import pytest

from aughor.routers import investigations as inv

_NARRATION = {"narrative": "Listed.", "anomalies": [], "trend": "", "confidence": "high", "follow_ups": []}


@pytest.fixture()
def shop(tmp_path):
    path = tmp_path / "shop.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE orders AS SELECT DATE '2026-09-20' - (i % 30)::INT AS order_date, "
                "(20 + i % 50)::DOUBLE AS amount FROM range(0, 600) t(i)")
    con.close()
    from aughor.db.registry import add_connection
    return add_connection("item23 shop", "duckdb", str(path))


def _receipts(question: str, conn: str) -> list[dict]:
    async def _go():
        return [json.loads(c.split("data: ", 1)[1])
                async for c in inv._stream_chat(question, conn, [], session_id="s23")
                if c.startswith("data: ")]
    return [f for f in asyncio.run(_go()) if f.get("type") == "guard_receipt"]


def _answer(sql: str) -> dict:
    return {"sql": sql, "headline": "The orders", "chart_type": "none", "intent": "list",
            "approach": ["list the orders"]}


def test_a_preflight_rewrite_is_said(shop, faux_llm):
    """Two output columns under one name: the preflight pass renames the later one, deterministically."""
    before = "SELECT amount AS x, amount * 2 AS x FROM orders LIMIT 5"
    faux_llm.set_responses([_answer(before), _NARRATION])
    (pre,) = [r for r in _receipts("List some order amounts", shop) if r["guard"] == "preflight_repair"]
    assert pre["action"] == "repaired_sql" and "aliases_uniquified" in pre["detail"]
    assert pre["before"] == before and pre["after"] != before


def test_a_repair_adopted_after_the_first_run_is_said(shop, faux_llm):
    """A CAST-to-date filter that returns nothing is a suspicious empty result; the repair that returns rows is
    adopted — and now says so, with both queries."""
    before = "SELECT order_date FROM orders WHERE CAST(order_date AS DATE) > DATE '2030-01-01'"
    after = "SELECT order_date FROM orders ORDER BY order_date DESC LIMIT 5"
    faux_llm.set_responses([_answer(before), {"corrected_sql": after, "explanation": "the filter excluded all"},
                            _NARRATION])
    (fix,) = [r for r in _receipts("Which order dates are after 2030?", shop) if r["guard"] == "sql_repair"]
    assert fix["action"] == "repaired_sql" and fix["detail"] == "the query returned no rows"
    assert (fix["before"], fix["after"]) == (before, after)


def test_a_query_nothing_rewrote_carries_no_rewrite_receipt(shop, faux_llm):
    faux_llm.set_responses([_answer("SELECT order_date, amount FROM orders LIMIT 5"), _NARRATION])
    assert not [r for r in _receipts("List some orders", shop) if r["action"] == "repaired_sql"]
