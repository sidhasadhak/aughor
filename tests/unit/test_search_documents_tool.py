"""The knowledge plane was running, and the conversation could not reach it.

`build_external_context_section` injects document passages into DEEP ANALYSIS and
investigations — scoped per agent through `agent_doc_ids()`, fail-closed. Chat had neither
that injection nor a tool: measured on the live roster, **16 tools and not one of them
reached a document**. `search_graph` is the knowledge GRAPH — entities and relationships —
not the document store. So on the surface a person actually talks to, an indexed corpus of
92 chunks across 11 documents did not exist.

⚠️ The ledger shows zero calls to any document tool, and that number proves less than it
looks: retrieval in investigations is an auto-injection, never a tool call, so it could not
have appeared there whether it ran or not. What the zero establishes is that no document
TOOL existed — which is the gap this closes, and the reason the count is not cited as
evidence that retrieval never happened.
"""
from __future__ import annotations

import pytest

from aughor.agent import platform_tools as pt


def _hit(doc_id, text, score=0.5, title=None):
    return {"doc_id": doc_id, "text": text, "score": score, "title": title or doc_id}


@pytest.fixture()
def index(monkeypatch):
    """Install a fake corpus and report what the tool asked it for."""
    asked = {}

    def _install(hits, allowed=None):
        def _search(query, top_k=4):
            asked["query"], asked["top_k"] = query, top_k
            return list(hits)
        monkeypatch.setattr("aughor.knowledge.indexer.search_documents", _search)
        monkeypatch.setattr("aughor.custom_agents.context.agent_doc_ids", lambda: allowed)
        return asked
    return _install


# ── it is on the roster the conversation actually gets ───────────────────────────

def test_the_conversation_can_reach_documents():
    """The whole defect, in one assertion. Built-and-not-wired is this repo's most repeated
    failure and the knowledge plane had it in its purest form: a retrieval path, an
    endpoint, per-agent scoping — and no way for a chat turn to call any of it."""
    from aughor.agent.converse_tools import converse_tools

    names = [t.name for t in converse_tools("workspace")]

    assert "search_documents" in names
    assert "search_graph" in names, (
        "search_graph is the knowledge GRAPH and is NOT a substitute — if it ever goes "
        "away, the reasoning in this file's docstring needs rewriting, not deleting")


# ── de-duplication, which is what makes the result worth its slots ───────────────

def test_one_passage_indexed_twice_takes_one_slot(index):
    """Measured on the live index: a connection documented as both `main` and `default`
    produces two doctrees carrying identical prose, and 8 raw hits for one question held
    only 6 distinct passages. Capped at five, that spent two of the model's five slots
    repeating itself."""
    index([_hit("doctree::fixture::main", "DailyRevenue is the revenue log.", 0.70),
           _hit("doctree::fixture::default", "DailyRevenue is the revenue log.", 0.70),
           _hit("doctree::other::main", "Customer is the master list.", 0.60)])

    out = pt.search_documents("c1", {"query": "revenue"})

    assert out["count"] == 2
    assert [h["text"] for h in out["hits"]] == ["DailyRevenue is the revenue log.",
                                                "Customer is the master list."]


def test_the_duplicate_source_is_reported_not_dropped(index):
    """The same text in two documents is a fact about the corpus. Silently keeping one is a
    second small lie on top of the de-duplication."""
    index([_hit("doctree::a", "Same prose.", 0.7), _hit("doctree::b", "Same prose.", 0.7)])

    hit = pt.search_documents("c1", {"query": "prose"})["hits"][0]

    assert hit["doc_id"] == "doctree::a" and hit["also_in"] == ["doctree::b"]


def test_whitespace_alone_does_not_make_two_passages(index):
    index([_hit("a", "One   passage\n\nhere."), _hit("b", "One passage here.")])

    assert pt.search_documents("c1", {"query": "x"})["count"] == 1


def test_it_over_fetches_so_the_cap_is_filled_after_dedup(index):
    """Fetching exactly the cap hands back three passages where five were asked for."""
    asked = index([_hit(f"d{i}", f"passage {i}") for i in range(30)])

    out = pt.search_documents("c1", {"query": "anything"})

    assert asked["top_k"] >= pt._MAX_DOC_HITS * 4
    assert out["count"] == pt._MAX_DOC_HITS


# ── scoping, the same rule the injection already honours ─────────────────────────

def test_an_agent_sees_only_the_documents_bound_to_it(index):
    index([_hit("mine", "bound"), _hit("theirs", "not bound")], allowed={"mine"})

    out = pt.search_documents("c1", {"query": "x"})

    assert [h["doc_id"] for h in out["hits"]] == ["mine"]


def test_an_agent_bound_to_nothing_searches_nothing_and_says_so(index):
    """Fail closed, and be legible about it: "no matches" and "you are allowed none" call
    for opposite fixes, and returning the first for the second sends the reader hunting an
    empty index that is fine."""
    index([_hit("d", "text")], allowed=set())

    out = pt.search_documents("c1", {"query": "x"})

    assert out["count"] == 0 and "bound to no documents" in out["why"]


def test_no_agent_means_the_whole_corpus(index):
    """`agent_doc_ids()` returning None is "no user agent active", not "allowed nothing"."""
    index([_hit("a", "one"), _hit("b", "two")], allowed=None)

    assert pt.search_documents("c1", {"query": "x"})["count"] == 2


# ── it degrades rather than breaking a turn ──────────────────────────────────────

def test_a_failing_index_answers_empty(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("qdrant is down")
    monkeypatch.setattr("aughor.knowledge.indexer.search_documents", _boom)
    monkeypatch.setattr("aughor.custom_agents.context.agent_doc_ids", lambda: None)

    out = pt.search_documents("c1", {"query": "x"})

    assert out["count"] == 0 and "could not be searched" in out["why"]


def test_an_empty_query_is_refused(index):
    index([_hit("a", "one")])

    assert pt.search_documents("c1", {"query": "   "})["error"]


# ── the result stays affordable ──────────────────────────────────────────────────

def test_a_long_passage_is_bounded(index):
    """A tool result that eats the window it was fetched into is the VA-5 failure again —
    `GET /traces/{id}` was 1.2 MB before someone measured it."""
    index([_hit("a", "x" * 50_000)])

    hit = pt.search_documents("c1", {"query": "x"})["hits"][0]

    assert len(hit["text"]) == pt._MAX_DOC_SNIPPET


def test_the_result_says_a_passage_is_not_a_number(index):
    """The one thing this tool must not become: a source of figures. Documentation says
    what a column MEANS; what it currently holds comes from a query."""
    index([_hit("a", "Revenue is recognised on success.")])

    assert "NUMBER" in pt.search_documents("c1", {"query": "revenue"})["note"]
