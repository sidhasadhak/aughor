"""Actionable 'why is the Hub empty' note — see aughor/explorer/agent._ontology_skip_note.
Turns a silent ontology-build failure into a specific, retryable status message."""
from aughor.explorer.agent import _ontology_skip_note


def test_stage_and_error_is_specific():
    note = _ontology_skip_note({"ok": False, "stage": "enrichment", "error": "LLM 404"})
    assert "enrichment failed" in note and "LLM 404" in note


def test_stage_only():
    note = _ontology_skip_note({"ok": False, "stage": "ontology", "error": None})
    assert "ontology stage produced no object model" in note


def test_none_falls_back_to_generic():
    note = _ontology_skip_note(None)
    assert "Ontology unavailable" in note and "too sparse" in note


def test_empty_dict_falls_back():
    assert "Ontology unavailable" in _ontology_skip_note({})
