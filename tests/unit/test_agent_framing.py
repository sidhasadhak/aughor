"""ON-10 — the investigation's half of framing: the served graph for the question's scope, a person's synonyms, and a
model's choice among the declared definitions a question fits equally — and only among them.

Hermetic: the store and the registry are replaced by the served Olist graph (`evals/ablation_olist_business_ontology
.json`), and the model by a stub that returns whatever it is told to, so a name that is not a candidate can be tried.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import aughor.agent.framing as AF
from aughor.ontology.framing import frame_question
from aughor.ontology.models import OntologyGraph

REPO = Path(__file__).resolve().parents[2]
OLIST = OntologyGraph.model_validate(json.loads((REPO / "evals" / "ablation_olist_business_ontology.json").read_text()))
AMBIGUOUS = "What was late last month?"


class _Model:
    def __init__(self, answer: str = "", fail: bool = False):
        self.answer, self.fail, self.calls = answer, fail, []

    def complete(self, *, system, user, response_model, temperature=None):
        self.calls.append(user)
        if self.fail:
            raise RuntimeError("provider down")
        return response_model(definition=self.answer)


@pytest.fixture
def served(monkeypatch):
    """The store holds the Olist graph under `baef6c3e/ecommerce`; the registry names `main` as the connection's schema."""
    import aughor.db.registry as registry
    import aughor.ontology.store as store
    held = {("baef6c3e", "ecommerce"): OLIST}
    monkeypatch.setattr(store, "load_latest_ontology", lambda conn, schema=None: held.get((conn, schema)))
    monkeypatch.setattr(store, "list_schemas", lambda conn: sorted(s for c, s in held if c == conn))
    monkeypatch.setattr(registry, "get_meta", lambda conn: {"schema_name": "main"})
    monkeypatch.setattr(AF, "person_synonyms", lambda conn: [])
    return held


def test_an_unambiguous_frame_costs_no_model_call(served):
    model = _Model("delivery_breach_rate")
    frame = AF.resolve_frame("What is causing a delay in warehouse dispatch?", "baef6c3e", "ecommerce", provider=model)
    assert frame.outcome.name == "dispatch_breach_rate" and frame.chosen_by == "names" and model.calls == []


def test_the_chooser_itself_never_asks_about_a_frame_that_is_not_ambiguous():
    model = _Model("delivery_breach_rate")
    settled = frame_question("What is causing a delay in warehouse dispatch?", OLIST)
    assert AF.choose_definition(settled, OLIST, provider=model) is settled and model.calls == []
    nothing = frame_question("How many sellers are there in each state?", OLIST)
    assert AF.choose_definition(nothing, OLIST, provider=model) is nothing and model.calls == []


def test_a_model_chooses_among_the_candidates_and_is_shown_only_them(served):
    model = _Model("delivery_breach_rate")
    frame = AF.resolve_frame(AMBIGUOUS, "baef6c3e", "ecommerce", provider=model)
    assert (frame.outcome.name, frame.chosen_by, frame.start["entity"]) == ("delivery_breach_rate", "model", "Order")
    [prompt] = model.calls
    assert "- dispatch_breach_rate:" in prompt and "- delivery_breach_rate:" in prompt and AMBIGUOUS in prompt


@pytest.mark.parametrize("model, note", [
    (_Model("revenue_at_risk"), "'revenue_at_risk' is not one of the declared definitions"),
    (_Model(""), "a model read none of the declared definitions"),
    (_Model(fail=True), ""),
])
def test_a_model_that_names_nothing_listed_or_fails_chooses_nothing(served, model, note):
    frame = AF.resolve_frame(AMBIGUOUS, "baef6c3e", "ecommerce", provider=model)
    assert frame.ambiguous and frame.chosen is None
    assert (note in " ".join(frame.notes)) if note else frame.notes == []


def test_only_a_person_s_synonyms_reach_the_frame(monkeypatch):
    import aughor.ontology.vocabulary as V
    rows = [V.Synonym("baef6c3e", "term", "order_to_delivery.dispatched", "handover", "human", ""),
            V.Synonym("baef6c3e", "term", "order_to_delivery.delivered", "arrival", "mined", ""),
            V.Synonym("baef6c3e", "term", "order_to_delivery.delivered", "drop", "llm_candidate", "")]
    monkeypatch.setattr(V, "synonyms_for", lambda conn, subject_kind=None: rows)
    assert [s.synonym for s in AF.person_synonyms("baef6c3e")] == ["handover"]


def test_the_scope_is_the_schema_named_else_the_connection_s_own_and_never_another_schema_s_graph(served):
    assert AF.served_graph("baef6c3e", "ecommerce") is OLIST
    assert AF.served_graph("baef6c3e", None) is OLIST                  # `main` names nothing built; one schema is built
    served[("baef6c3e", "main")] = OntologyGraph(connection_id="baef6c3e", schema_name="main", schema_fingerprint="f")
    assert AF.served_graph("baef6c3e", "sales") is None                # two built, neither named: no substitution
    assert AF.served_graph("baef6c3e", None).schema_name == "main"
    assert AF.resolve_frame("anything", "nope", None) is None


def test_a_carried_unambiguous_frame_is_read_back_without_reading_the_store(served, monkeypatch):
    question = "What is causing a delay in warehouse dispatch?"
    monkeypatch.setattr(AF, "served_graph", lambda *_a, **_k: pytest.fail("an unambiguous carried frame reads nothing"))
    state = {"question": question, "connection_id": "baef6c3e", "scope_schema": "ecommerce",
             "ontology_frame": frame_question(question, OLIST).model_dump(mode="json")}
    assert AF.frame_from_state(state).outcome.name == "dispatch_breach_rate"


def test_a_carried_ambiguous_frame_is_completed_with_a_choice_and_a_frame_of_another_question_is_not_read(served):
    ambiguous = {"question": AMBIGUOUS, "connection_id": "baef6c3e", "scope_schema": "ecommerce",
                 "ontology_frame": frame_question(AMBIGUOUS, OLIST).model_dump(mode="json")}
    chosen = AF.frame_from_state(ambiguous, provider=_Model("dispatch_breach_rate"))
    assert (chosen.outcome.name, chosen.chosen_by) == ("dispatch_breach_rate", "model")
    stale = {**ambiguous, "question": "What is causing a delay in warehouse dispatch?"}
    assert AF.frame_from_state(stale).outcome.name == "dispatch_breach_rate"
