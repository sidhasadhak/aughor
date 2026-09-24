"""PENDING item 22 — no number is shown before it is measured.

The quick path's SQL writer returns its headline WITH the SQL, before the query runs, and the headline streamed onto
the screen as the model typed it — numbers included ("orders fell 97.5%" before a row existed). Afterwards it was
replaced only on a flat contradiction with the rows. Now the words type in and the stream stops at the word holding
the first digit; the number arrives with the grounded headline, once the rows are in.

Driven through the REAL `_stream_chat` over a DuckDB connection with the faux model; the one liberty is that the faux
backend's streaming call types the scripted headline out through `on_text`, as a streaming backend does.
"""
from __future__ import annotations

import asyncio
import json
import re

import duckdb
import pytest

from aughor.routers import investigations as inv


def test_the_words_type_and_the_number_waits():
    f = inv._numberless_prefix
    assert f("Revenue in the last quarter was $1.2M") == "Revenue in the last quarter was"
    assert f("Revenue in Q3 2024 fell 12%") == "Revenue in"
    assert f("3 regions account for half") == ""
    assert f("No change in orders") == "No change in orders"


@pytest.fixture()
def shop(tmp_path):
    path = tmp_path / "shop.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE orders AS SELECT DATE '2026-09-20' - (i % 30)::INT AS order_date, "
                "(20 + i % 50)::DOUBLE AS amount FROM range(0, 600) t(i)")
    con.close()
    from aughor.db.registry import add_connection
    return add_connection("item22 shop", "duckdb", str(path))


def test_a_streamed_headline_never_shows_a_number_the_rows_have_not_given(shop, faux_llm, monkeypatch):
    predicted = "Orders fell 97.5% yesterday to 3 orders"
    faux_llm.set_responses([
        {"sql": "SELECT COUNT(*) AS orders FROM orders", "headline": predicted, "chart_type": "none",
         "intent": "count", "approach": ["count the orders"]},
        {"narrative": "There are 600 orders.", "anomalies": [], "trend": "", "confidence": "high",
         "follow_ups": []},
    ])
    from aughor.llm.provider import LLMProvider
    real_complete = LLMProvider.complete

    def typed(self, system, user, response_model, text_field, on_text, temperature=0.1):
        answer = real_complete(self, system, user, response_model, temperature=temperature)
        text = str(getattr(answer, text_field, "") or "")
        for n in range(1, len(text) + 1, 3):              # a few characters at a time, as a model types
            on_text(text[:n])
        return answer
    monkeypatch.setattr(LLMProvider, "complete_streaming", typed)

    async def _go():
        return [json.loads(c.split("data: ", 1)[1])
                async for c in inv._stream_chat("How many orders are there?", shop, [], session_id="s22")
                if c.startswith("data: ")]
    frames = asyncio.run(_go())

    streamed = [f["headline"] for f in frames if f.get("type") == "headline_delta"]
    assert streamed, "the headline did not stream at all"
    assert not any(re.search(r"\d", h) for h in streamed), streamed
    assert streamed[-1] == "Orders fell"
    final = [f["headline"] for f in frames if f.get("type") == "headline"]
    assert final and "97.5" not in final[-1], final         # the rows (600) contradicted the prediction
