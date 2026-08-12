"""The knowledge base has two registers, and the reader never gets the prompt one.

CI-0 finding 4: eleven stored turns carry "RELEVANT SQL AND DOMAIN PATTERNS (apply
when writing queries): …" verbatim as their user-facing HEADLINE — the definitional
chat path answered with `retrieve_for_planning`, a prompt-injection block whose first
line is an instruction to a model. The fix is a register split: same retrieval,
reader-facing rendering, and empty-on-failure so the caller still falls through to
the live-SQL path.
"""
from __future__ import annotations

from aughor.semantic import kb_retriever

_TIER2_HIT = {
    "title": "Average Transit Time",
    "difficulty": "intermediate",
    "tier": 2,
    "business_definition": "The average elapsed time between dispatch and delivery.",
    "metric_nature": {"common_misconception": "Averaging per-order times weights small orders equally."},
    "diagnostic_questions": ["Which service level drives the average?"],
    "sql_example": "SELECT service_level, AVG(delivered_at - shipped_at) FROM shipments GROUP BY 1",
}


def test_reader_register_carries_no_prompt_scaffolding():
    text = kb_retriever._format_for_reader([_TIER2_HIT])
    assert "RELEVANT SQL AND DOMAIN PATTERNS" not in text, \
        "the prompt heading is an instruction to a model — never part of an answer"
    assert "──" not in text
    assert "The average elapsed time between dispatch and delivery." in text
    assert "Common misconception:" in text
    assert "```sql" in text, "SQL arrives as a fenced example, not a bare template"


def test_planning_register_is_unchanged():
    text = kb_retriever._format_for_planning([_TIER2_HIT])
    assert text.startswith("RELEVANT SQL AND DOMAIN PATTERNS"), \
        "the planner still gets its injection block — the split is additive"


def test_retrieve_for_reader_falls_through_empty_on_failure(monkeypatch):
    """'' is the contract that keeps the definitional path safe: a falsy answer sends
    the turn down the normal live-SQL path instead of emitting garbage."""
    monkeypatch.setattr(kb_retriever, "_ensure_indexed", lambda: (_ for _ in ()).throw(RuntimeError))
    assert kb_retriever.retrieve_for_reader("anything") == ""


def test_connection_kb_registers_split(monkeypatch):
    from types import SimpleNamespace

    from aughor.semantic import connection_kb

    entries = [SimpleNamespace(render=lambda: "net_revenue: GMV minus returns and cancellations.")]
    monkeypatch.setattr(connection_kb, "_relevant_entries", lambda q, c, top_k=4: entries)

    prompt = connection_kb.retrieve_for_question("what is net revenue?", "conn-x")
    reader = connection_kb.retrieve_for_reader("what is net revenue?", "conn-x")
    assert prompt.startswith("DOMAIN KNOWLEDGE (use these definitions exactly when writing SQL):")
    assert "use these definitions exactly" not in reader, \
        "an answer never carries an instruction addressed to a model"
    assert "net_revenue: GMV minus returns" in reader
