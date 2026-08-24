"""VA-1 deliverable 4 — the model had no way to learn a pack existed.

The disclosure ladder had two rungs and both are TOOLS: `list_packs` to see the roster,
`read_pack` to fetch one body. Both require the model to already suspect a pack might help.

**Measured on the live ledger before building this:** 2,672 recorded tool calls across 72
converse turns, every one of them named. `run_sql` 55 · `propose_context_note` 1 ·
`list_tables` · `answer_question` — so platform tools ARE recorded when they fire.
`list_packs`: 0. `read_pack`: 0. Never, not rarely.

Rung 0 closes that: when an ACTIVE, in-scope pack matches the question, the system prompt
says so — as state, like VA-2's delegation roster, and absent when nothing matches.

Two properties this file exists to hold, because they pull against each other:

* it FIRES on the questions the pack answers — otherwise it changes nothing;
* it stays SILENT on ordinary analytical questions — otherwise it is prompt bloat on every
  turn, which the deliverable's own risk note names as a regression.
"""
from __future__ import annotations

import types

import pytest

from aughor.packs import disclosure
from aughor.packs.loader import PROSE_FIELD


def _pack(pack_id, name="P", domains=(), description="", tags=(), canonical=()):
    return types.SimpleNamespace(
        id=pack_id,
        manifest=types.SimpleNamespace(name=name, status="active", partial=True,
                                       domains=list(domains),
                                       scope={"connections": ["*"]}),
        questions=types.SimpleNamespace(intent_tags=list(tags), canonical=list(canonical),
                                        diagnostic=[], explorer_angles=[]),
        metrics=[], playbooks=[],
        **{PROSE_FIELD: f"# {name}\n\n{description}\n"},
    )


@pytest.fixture(scope="module")
def duck():
    """The REAL shipped pack, not a fake.

    A hand-made stand-in passes or fails on the tags the author of the test happened to
    write, which is not the question. What matters is whether `packs/duckdb-engine` routes
    on the questions it documents — and the first draft of this file proved the point by
    fizzling on a fake whose tag list was thinner than the pack's."""
    from pathlib import Path as _P

    from aughor.packs import load_pack

    return load_pack(_P(__file__).resolve().parents[2] / "packs" / "duckdb-engine")


@pytest.fixture()
def on_duckdb(monkeypatch):
    """Declare what engine `c1` is. Scope is checked BEFORE relevance, so without this the
    shipped pack — scoped to the DuckDB-speaking connectors — correctly matches nothing, and
    every assertion below would pass or fail for a reason that has nothing to do with
    routing. The first draft of this file did exactly that."""
    monkeypatch.setattr("aughor.packs.scope.conn_type_of", lambda _cid: "duckdb")


# ── it fires on what the pack answers ────────────────────────────────────────────

@pytest.mark.parametrize("question", [
    "why is my revenue column stored as a string?",
    "why did my ratio come out as a whole number?",
    "how many days between the order date and the ship date?",
])
def test_a_matching_question_names_the_pack(question, duck, on_duckdb):
    block = disclosure.disclosure_block(question, "c1", packs=[duck])

    assert "duckdb-engine" in block
    assert "read_pack" in block, "naming a pack without saying how to read it is half a rung"


# ── and stays quiet otherwise ────────────────────────────────────────────────────

@pytest.mark.parametrize("question", [
    "how many customers did we add last month?",
    "who are our top 10 customers by revenue?",
    "what is our churn rate this quarter?",
])
def test_an_ordinary_question_gets_no_block(question, duck, on_duckdb):
    """Prompt bloat is the named risk for this deliverable. A line that appears on every
    turn is a line the model learns to skip."""
    assert disclosure.disclosure_block(question, "c1", packs=[duck]) == ""


def test_a_pack_out_of_scope_is_never_named(monkeypatch):
    """Scope decides applicability before relevance does. A BigQuery pack matching a
    BigQuery-shaped question on a DuckDB connection is still the wrong pack."""
    bq = _pack("bq", "BigQuery", ("BigQuery",), "Partitioning and slots.",
               tags=("partition", "cast", "string"))
    bq.manifest.scope = {"connections": ["engine:bigquery"]}
    monkeypatch.setattr("aughor.packs.scope.conn_type_of", lambda _cid: "duckdb")

    assert disclosure.disclosure_block("why is this column a string?", "c1", packs=[bq]) == ""


def test_the_description_alone_is_a_thin_signal(duck, on_duckdb):
    """The measurement that changed the design. Scored on its DESCRIPTION only, the pack
    whose entire subject is casting surprises returns 0.0 for the question a person actually
    asks about one — so a first cut that read descriptions alone fired on nothing. Tags are
    the words a USER types; a description is the words we chose. Both are read, and this is
    the receipt for why."""
    from aughor.agent.platform_tools import pack_description
    from aughor.packs.routing import score_text

    question = "why is my revenue column stored as a string?"

    assert score_text(question, pack_description(duck)) == 0.0
    assert disclosure.matching_packs(question, "c1", packs=[duck]) == [duck]


# ── cost ─────────────────────────────────────────────────────────────────────────

def test_the_block_names_the_pack_and_does_not_paste_it(duck, on_duckdb):
    """The deliverable's risk note: "a skill that adds 800 tokens and changes nothing is a
    regression". The real pack's prose is ~1,500 tokens; a pointer is ~140. Pasting bodies
    into every matching turn would spend exactly the budget the two-rung ladder protects."""
    from aughor.packs.loader import PROSE_FIELD

    prose = getattr(duck, PROSE_FIELD, "")
    block = disclosure.disclosure_block("why did my cast lose the decimals?", "c1",
                                        packs=[duck])

    assert block, "the real pack did not match a question it documents"
    assert len(block) < len(prose) / 5, "the block is pasting the body, not naming it"
    assert "TRY_CAST" not in block, "a body fragment reached the prompt"


def test_at_most_two_packs_are_named():
    """The cap is the cost control: a roster that grows with the library turns a fixed
    prompt into a variable one."""
    many = [_pack(f"p{i}", f"P{i}", ("duckdb",), "casting and division and dates",
                  tags=("cast", "string", "ratio")) for i in range(5)]

    named = disclosure.matching_packs("why is this cast turning a string into a ratio?",
                                      "c1", packs=many)

    assert len(named) == disclosure.MAX_NAMED == 2


def test_the_ordering_is_stable_when_scores_tie():
    """Two packs with identical scores must not swap between turns — a prompt that changes
    without the question changing defeats caching and makes a regression unbisectable."""
    a = _pack("aaa", "A", ("duckdb",), "casting", tags=("cast", "string"))
    b = _pack("bbb", "B", ("duckdb",), "casting", tags=("cast", "string"))

    for _ in range(3):
        assert [p.id for p in disclosure.matching_packs("cast string", "c1", packs=[b, a])] \
            == ["aaa", "bbb"]


# ── the wiring ───────────────────────────────────────────────────────────────────

def test_the_system_prompt_carries_the_block(monkeypatch):
    """Built and not wired is this repo's most repeated failure, and the one the whole
    skills plane already suffered once."""
    from aughor.agent import converse_tools

    monkeypatch.setattr("aughor.packs.disclosure.disclosure_block",
                        lambda q, cid, packs=None: "PACK-BLOCK-MARKER" if q else "")

    with_q = converse_tools.converse_system_prompt("c1", question="anything")
    without = converse_tools.converse_system_prompt("c1")

    assert "PACK-BLOCK-MARKER" in with_q
    assert "PACK-BLOCK-MARKER" not in without, "a promptless assembly must not fabricate one"


def test_a_broken_disclosure_never_breaks_the_conversation(monkeypatch):
    """Additive by construction. The roster block next to it follows the same rule."""
    from aughor.agent import converse_tools

    def _boom(*_a, **_k):
        raise RuntimeError("pack store is gone")
    monkeypatch.setattr("aughor.packs.disclosure.disclosure_block", _boom)

    prompt = converse_tools.converse_system_prompt("c1", question="anything")

    assert "Aughor's analyst" in prompt
