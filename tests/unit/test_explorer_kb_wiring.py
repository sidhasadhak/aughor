"""The autonomous Explorer consults the knowledge base before writing SQL.

The ADA path has called `retrieve_for_planning` on every plan since it shipped. The explorer —
the agent that writes the Briefing — never did, so the component generating the most SQL in the
system had no access to the library describing the mistakes it kept making.

That is not hypothetical. On the 2026-07-21 run, Phase 8 wrote the same fanned
`order_items ⋈ products` join five times and the guard rejected all five, while the KB held a
"Fan-out Detection and Prevention" entry prescribing exactly the pre-aggregate fix. The guards
were catching at the back of the pipeline what the KB could have prevented at the front.

These tests pin the WIRING (does retrieval reach the generator?), not the retriever itself —
`retrieve_for_planning` is stubbed throughout, so they are hermetic and need no Qdrant.
"""
from __future__ import annotations

import inspect

import pytest

from aughor.explorer.agent import SchemaExplorer


class TestKbContextHelper:
    def test_returns_the_retrieved_block(self, monkeypatch):
        import aughor.semantic.kb_retriever as kb
        monkeypatch.setattr(kb, "retrieve_for_planning", lambda q, top_k=3: "PATTERNS: pre-aggregate")
        out = SchemaExplorer._kb_context("why is return rate high")
        assert "pre-aggregate" in out
        assert out.endswith("\n\n"), "must be separable from the block it is prepended to"

    def test_empty_query_never_hits_the_retriever(self, monkeypatch):
        import aughor.semantic.kb_retriever as kb

        def _boom(*a, **k):
            raise AssertionError("must not retrieve on an empty query")

        monkeypatch.setattr(kb, "retrieve_for_planning", _boom)
        assert SchemaExplorer._kb_context("") == ""
        assert SchemaExplorer._kb_context("   ") == ""

    def test_no_hits_yields_empty_string(self, monkeypatch):
        import aughor.semantic.kb_retriever as kb
        monkeypatch.setattr(kb, "retrieve_for_planning", lambda q, top_k=3: "")
        assert SchemaExplorer._kb_context("anything") == ""

    def test_retriever_failure_never_breaks_generation(self, monkeypatch):
        """Fail-open: a background agent must lose the KB, not the run."""
        import aughor.semantic.kb_retriever as kb

        def _boom(*a, **k):
            raise RuntimeError("qdrant unreachable")

        monkeypatch.setattr(kb, "retrieve_for_planning", _boom)
        assert SchemaExplorer._kb_context("why is return rate high") == ""

    def test_query_is_bounded(self, monkeypatch):
        """An unbounded key would push a whole findings dump into the embedding call."""
        import aughor.semantic.kb_retriever as kb
        seen: list[str] = []
        monkeypatch.setattr(kb, "retrieve_for_planning",
                            lambda q, top_k=3: seen.append(q) or "X")
        SchemaExplorer._kb_context("word " * 500)
        assert len(seen[0]) <= 400


class TestEveryGenerationPathConsultsTheKb:
    """Three paths generate SQL, and they differ in what they can key retrieval on. A path that
    silently stops consulting the KB is invisible at runtime — the output just gets worse — so
    the wiring is pinned in source."""

    SRC = inspect.getsource(__import__("aughor.explorer.agent", fromlist=["x"]))

    def test_pinned_questions_retrieve_per_question(self):
        # _pin_context is built ONCE for all pinned questions, so retrieval must happen inside
        # the loop keyed on `q` — hoisting it out would key every question on the first one.
        assert "_pin_ctx_q = self._kb_context(q) + _pin_context" in self.SRC

    def test_phase8_keys_on_the_domain_because_the_question_does_not_exist_yet(self):
        # Phase 8 has the model INVENT the question and SQL in one call, so there is no question
        # to retrieve on — the domain and its tables are what is known before generation.
        assert "_kb_steer = self._kb_context(" in self.SRC
        assert "{_kb_steer}" in self.SRC, "the retrieved block must reach the steer prompt"

    def test_synthesis_retrieves_on_the_confirm_question(self):
        assert "_ctx = self._kb_context(plan.confirm_question) + _ctx" in self.SRC


class TestCuratedIndustryMetricsAlwaysSteer:
    def test_the_selected_vs_inferred_conditional_is_gone(self):
        """It used to steer ONLY when the user's selected industry differed from the inferred
        one — so the common case (they match) got no curated metrics at all, which is precisely
        when that curation is most trustworthy. The profile's metrics are INFERRED from column
        names; the KB's carry a human-authored formula, grain, sane range and anti-pattern."""
        src = TestEveryGenerationPathConsultsTheKb.SRC
        assert '(_eff_industry or "").strip().lower() != (_bp.industry or "").strip().lower()' not in src
        assert "_sel_kb = match_industry(_eff_industry)" in src

    def test_the_prompt_no_longer_claims_the_user_selected_it(self):
        """The old copy said "the user set this business's industry to X" — untrue now that the
        block also fires for an INFERRED industry the user never chose. A prompt that misstates
        provenance teaches the model to trust it more than it should."""
        src = TestEveryGenerationPathConsultsTheKb.SRC
        assert "the user set this business's industry to" not in src
        assert "CURATED " in src


@pytest.mark.parametrize("counter", ["explorer.kb_retrieved", "explorer.kb_retrieval_failed"])
def test_retrieval_is_measurable(counter, monkeypatch):
    """Whether this earns its keep has to be answerable from /dev/stats, not by grepping logs —
    the whole point of the exercise is that a capability nobody can measure gets left unwired."""
    src = TestEveryGenerationPathConsultsTheKb.SRC
    assert counter in src


class TestKbPathResolution:
    """The KB ships WITH the repo, so it must work on a fresh clone with no configuration.

    It didn't: the default was "", making `build_kb_index()` a silent no-op unless an operator
    knew to set AUGHOR_KB_PATH — and this install had drifted onto a path in a DIFFERENT repo
    that no longer existed. Retrieval kept working only because the Qdrant collection outlived
    its source directory, and 5 of the 63 KB files had therefore never been indexed at all.
    A store whose source is unreachable fails silently: it keeps answering, just never improves.
    """

    def test_default_points_at_the_repo_kb_and_it_exists(self):
        import os

        from aughor.semantic import kb_retriever
        assert os.path.isdir(kb_retriever.KB_PATH), (
            f"KB_PATH {kb_retriever.KB_PATH!r} is not a directory — build_kb_index() would "
            f"silently index nothing"
        )
        assert kb_retriever.KB_PATH.rstrip("/").endswith("data/kb")

    def test_the_repo_kb_actually_loads_entries(self):
        """Guards the path AND the parse: a directory that exists but yields zero entries is the
        same silent no-op."""
        from aughor.semantic.kb_loader import load_kb_entries
        from aughor.semantic.kb_retriever import KB_PATH
        entries = load_kb_entries(KB_PATH)
        assert len(entries) > 200, f"only {len(entries)} KB entries loadable from {KB_PATH}"

    def test_an_explicit_override_still_wins(self, monkeypatch, tmp_path):
        """Operators must keep the escape hatch — the default is a fallback, not a hard-code."""
        import importlib

        monkeypatch.setenv("AUGHOR_KB_PATH", str(tmp_path))
        from aughor.semantic import kb_retriever
        reloaded = importlib.reload(kb_retriever)
        try:
            assert reloaded.KB_PATH == str(tmp_path)
        finally:
            monkeypatch.delenv("AUGHOR_KB_PATH", raising=False)
            importlib.reload(kb_retriever)   # restore module state for the rest of the session
