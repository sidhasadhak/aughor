"""Follow-up suggestions: the user's voice, grounded in the answer artifact (2.1).

Two things are pinned here. The **voice**, because a chip is typed into the composer
verbatim when clicked and a model asked for "follow-up investigation questions" writes
*about* the user instead. And the **artifact**, because the deep paths held the
executed SQL, its columns and its tables at the emission site and were sending only a
question and a headline — the one advantage this system has over a generic chat
assistant, unused.
"""
from __future__ import annotations

import pytest

from aughor.agent.followups import (
    artifact_from_history,
    followup_system,
    followup_user,
)


class _Rec:
    """The shape the deep paths carry in `query_history`."""

    def __init__(self, sql="", columns=None, row_count=0, error=None):
        self.sql = sql
        self.columns = columns or []
        self.row_count = row_count
        self.error = error


# ── the voice ────────────────────────────────────────────────────────────────

def test_the_system_prompt_demands_the_users_own_words():
    s = followup_system()
    assert "AS THE USER" in s
    assert "Never write about the user" in s


def test_the_system_prompt_demands_operations_on_this_result():
    s = followup_system()
    assert "never invent a column" in s
    for lever in ("grouping", "time window", "segment", "mover"):
        assert lever in s


def test_an_unanswered_question_gets_a_different_ask():
    """With no result there is nothing to operate on — suggestions should look for
    solid ground instead of pretending to slice an answer that does not exist."""
    s = followup_system(answered=False)
    assert "could NOT be answered" in s
    assert "AS THE USER" in s
    assert s != followup_system()


def test_the_quick_paths_clause_carries_the_same_voice():
    """The quick path merges narrative + follow-ups into ONE narrator call, so its ask
    rides inside the narrative prompt rather than using followup_system(). The voice
    instruction must still be there or the two paths drift."""
    from aughor.routers.investigations import _FOLLOWUP_CLAUSE

    assert "AS THE USER" in _FOLLOWUP_CLAUSE
    assert "Never write about the user" in _FOLLOWUP_CLAUSE


# ── the artifact ─────────────────────────────────────────────────────────────

def test_user_block_carries_the_whole_artifact():
    out = followup_user("why did sales drop", headline="Sales fell 12%",
                        sql="SELECT region, SUM(amount) FROM orders GROUP BY region",
                        tables=["orders"], columns=["region", "amount"], row_count=5)
    assert "Question: why did sales drop" in out
    assert "Answer: Sales fell 12%" in out
    assert "Rows returned: 5" in out
    assert "Tables used: orders" in out
    assert "Columns available: region, amount" in out
    assert "SELECT region" in out


def test_absent_fields_are_omitted_not_sent_empty():
    """A labelled empty is worse than an absence: it tells the model the artifact
    exists and is blank."""
    out = followup_user("q")
    assert out == "Question: q"
    for label in ("Answer:", "Tables used:", "Columns available:", "SQL"):
        assert label not in out


def test_artifact_takes_the_last_query_that_actually_returned_columns():
    """The report's headline is about the final result; earlier queries are the
    working-out, and a suggestion grounded in an intermediate probe reads like a non
    sequitur."""
    art = artifact_from_history([
        _Rec(sql="SELECT 1", columns=["a"], row_count=1),
        _Rec(sql="SELECT region, SUM(amount) FROM orders GROUP BY region",
             columns=["region", "sum"], row_count=4),
    ])
    assert "GROUP BY region" in art["sql"]
    assert art["columns"] == ["region", "sum"]
    assert art["row_count"] == 4


def test_artifact_skips_failed_queries():
    art = artifact_from_history([
        _Rec(sql="SELECT good FROM orders", columns=["good"], row_count=2),
        _Rec(sql="SELECT broken FROM nope", columns=["x"], error="no such table"),
    ])
    assert art["sql"] == "SELECT good FROM orders"


def test_artifact_extracts_real_tables_excluding_ctes():
    art = artifact_from_history([
        _Rec(sql="WITH recent AS (SELECT * FROM orders) SELECT * FROM recent",
             columns=["id"], row_count=1),
    ])
    assert "orders" in art.get("tables", [])
    assert "recent" not in art.get("tables", []), "a CTE is not a table the user can ask about"


def test_artifact_accepts_dict_records_too():
    art = artifact_from_history([
        {"sql": "SELECT a FROM t", "columns": ["a"], "row_count": 3, "error": None},
    ])
    assert art["sql"] == "SELECT a FROM t" and art["row_count"] == 3


@pytest.mark.parametrize("bad", [None, [], "not-a-list", [object()], [_Rec()]])
def test_artifact_never_raises(bad):
    """It runs inside a best-effort block on the answer path; a shape it does not
    recognise must degrade to the old question-and-headline prompt, not an exception."""
    assert isinstance(artifact_from_history(bad), dict)


def test_artifact_result_is_directly_splattable_into_the_user_block():
    """The call sites do `followup_user(q, headline=…, **artifact_from_history(qh))`,
    so every key this returns must be a parameter that accepts."""
    art = artifact_from_history([_Rec(sql="SELECT a FROM t", columns=["a"], row_count=1)])
    followup_user("q", headline="h", **art)   # must not TypeError
