"""IP — the questions an industry package DECLARES reach the runtime.

Measured before this wave, on `1a8a3a88`: `questions.yaml` (canonical, diagnostic, explorer_angles,
intent_tags) had three readers and none of them was the runtime for an industry package.
`routing.score_pack` reads canonical + intent_tags over the STEERING pool, which excludes every
knowledge layer by construction (`PackManifest.steers`); `inject.build_injection` copies diagnostic +
explorer_angles into a `PackInjection` field no renderer reads; the agent template projects canonical +
diagnostic into suggested goldens. So airline's six questions and two angles reached no prompt and no
person — #534 named the plays and the recipes and left the questions for this wave.

Three readers now name them, each through one seam (`metric_kb.package_questions`, gated like the
recipes: `knowledge_index()` carries only active packages, reached by the curated industry id):
the explorer's QUESTIONS THAT MATTER block (declared first, marked), the explorer's angle checklist
(declared angles first) and the `/suggestions` door (declared questions lead the model's six, each
with its own route: canonical → ask, diagnostic → investigate). These tests pin the properties that
make the seam honest: the questions arrive, declared ones come first so truncation cannot drop them,
they carry their route and their source, the population is the knowledge index and nothing else, and
a connection with no active package gets a byte-identical payload.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.business_profile.metric_kb import declared_key_questions, package_questions
from aughor.starters import PACKAGE_SUGGESTIONS_CAP, package_suggestions

AIRLINE_CANONICAL = "What was our on-time arrival rate last month?"
AIRLINE_DIAGNOSTIC = "Which delay causes account for the fall in on-time arrivals?"
AIRLINE_ANGLE = "On-time arrival rate by carrier network and by departure airport"


class TestTheDeclaredQuestionsArrive:
    def test_airlines_questions_are_read_by_industry_id(self):
        pq = package_questions("airline")
        assert pq["packs"] == ["airline"]
        assert AIRLINE_CANONICAL in pq["canonical"]
        assert AIRLINE_DIAGNOSTIC in pq["diagnostic"]
        assert AIRLINE_ANGLE in pq["explorer_angles"]
        assert "OTP" in pq["intent_tags"]

    def test_the_industry_text_resolves_the_way_the_recipes_do(self):
        """The profile says "Commercial Aviation"; the package is reached by its curated id."""
        assert package_questions("Commercial Aviation")["packs"] == ["airline"]

    def test_nothing_is_not_the_word_none(self):
        for industry in ("", "nonsense", "banking"):      # banking ships `status: draft` (gate 6)
            pq = package_questions(industry)
            assert pq == {"canonical": [], "diagnostic": [], "explorer_angles": [], "intent_tags": [],
                          "packs": []}, (industry, pq)

    def test_another_industrys_package_does_not_leak_in(self):
        pq = package_questions("retail")
        assert AIRLINE_CANONICAL not in pq["canonical"] and AIRLINE_ANGLE not in pq["explorer_angles"]

    def test_a_package_that_declared_nothing_is_not_named_as_a_source(self):
        """`packs/retail` has no questions.yaml: it contributes nothing and is not "where they came from"."""
        assert package_questions("retail")["packs"] == []

    def test_the_population_is_the_knowledge_index_not_the_disk(self, monkeypatch):
        """Gate 6 by construction: the seam reads what `knowledge_index()` carries. An index without
        airline (what a draft or a deactivated package looks like there) yields nothing, though the
        files are on disk."""
        from aughor.packs import knowledge
        real = knowledge.knowledge_index()
        # The fake keeps the curated industries (so "airline" still resolves to its id) and carries
        # no package — complete the fake, never loosen the reader.
        monkeypatch.setattr(knowledge, "knowledge_index",
                            lambda: SimpleNamespace(packages=(), industries=real.industries))
        assert package_questions("airline")["packs"] == []


class TestDeclaredQuestionsComeFirst:
    def test_declared_lead_and_inferred_follow(self):
        rows = declared_key_questions("airline", ["Which routes lose money?", "Where are we late?"])
        declared = [q for q, d in rows if d]
        inferred = [q for q, d in rows if not d]
        assert declared[0] == AIRLINE_CANONICAL and AIRLINE_DIAGNOSTIC in declared
        assert inferred == ["Which routes lose money?", "Where are we late?"]
        assert rows.index((AIRLINE_DIAGNOSTIC, True)) < rows.index(("Which routes lose money?", False))

    def test_an_inferred_repeat_of_a_declared_question_is_dropped(self):
        rows = declared_key_questions("airline", [AIRLINE_CANONICAL.upper(), "  " + AIRLINE_CANONICAL + " "])
        assert [q for q, d in rows if not d] == []

    def test_the_caps_hold_on_both_sides(self):
        rows = declared_key_questions("airline", [f"q{i}" for i in range(20)], declared_cap=2, inferred_cap=3)
        assert [d for _q, d in rows] == [True, True, False, False, False]

    def test_no_package_means_the_inferred_list_as_it_was(self):
        rows = declared_key_questions("nonsense", ["a", "b"])
        assert rows == [("a", False), ("b", False)]


class TestTheSuggestionsCarryTheirRoute:
    def test_canonical_asks_and_diagnostic_investigates_canonical_first(self):
        chips = package_suggestions("c", industry="airline")
        assert len(chips) == PACKAGE_SUGGESTIONS_CAP == 4
        assert [c["mode"] for c in chips] == ["ask", "ask", "ask", "investigate"]
        assert chips[0]["text"] == AIRLINE_CANONICAL and chips[3]["text"] == AIRLINE_DIAGNOSTIC
        assert all(c["source"] == "package" and c["pack"] == "airline" and c["purpose"] == "package_question"
                   for c in chips)

    def test_no_industry_or_no_declaring_package_is_empty(self):
        assert package_suggestions("c", industry="") == []
        assert package_suggestions("c", industry="retail") == []

    def test_the_connections_industry_is_resolved_when_none_is_given(self, monkeypatch):
        import aughor.starters as S
        monkeypatch.setattr(S, "connection_industry", lambda cid, schema="": "airline")
        assert package_suggestions("c")[0]["text"] == AIRLINE_CANONICAL
        monkeypatch.setattr(S, "connection_industry", lambda cid, schema="": "")
        assert package_suggestions("c") == []


class TestTheDoorLeadsWithThePackage:
    @pytest.fixture(autouse=True)
    def _cached(self, monkeypatch):
        monkeypatch.setattr("aughor.semantic.suggestions_cache.get_cached",
                            lambda cid, fp: [{"text": "Which carriers cancel the most flights?", "mode": "investigate"},
                                             {"text": "model q", "mode": "ask"}])

    def test_declared_questions_lead_and_a_repeat_is_dropped(self, client, monkeypatch):
        import aughor.starters as S
        monkeypatch.setattr(S, "connection_industry", lambda cid, schema="": "airline")
        body = client.get("/suggestions", params={"connection_id": "fixture"}).json()
        texts = [s["text"] for s in body["suggestions"]]
        assert texts[0] == AIRLINE_CANONICAL
        assert texts.count("Which carriers cancel the most flights?") == 1      # the model's repeat went
        assert body["suggestions"][1]["source"] == "package"                    # and the package's stayed, with its route
        assert body["suggestions"][1]["mode"] == "ask"
        assert texts[-1] == "model q"

    def test_no_package_leaves_the_payload_byte_identical(self, client, monkeypatch):
        import aughor.starters as S
        monkeypatch.setattr(S, "connection_industry", lambda cid, schema="": "")
        body = client.get("/suggestions", params={"connection_id": "fixture"}).json()
        assert body["suggestions"] == [{"text": "Which carriers cancel the most flights?", "mode": "investigate"},
                                       {"text": "model q", "mode": "ask"}]
