"""The intake's decisions are a typed record; the prose carries the reader's sentence.

Until 2026-10-15 nine writers prepended ALL-CAPS tags to `intake_notes` — ``CLAIM LICENCE:
descriptive — …``, ``ROUTING: this is a temporal-change question …``, ``TEMPORAL AXIS RECOVERED:
…``, ``MEASURE WARNING: …``, ``NOT OFFERED AS DIMENSIONS: …`` — and the code parsed its own tags
back out of that prose (the licence readers, the coverage reframe, the departure gate), while the
spec card, the PDF and the analyst read the tags as text. Each decision is now recorded once as a
typed entry (`_record_intake_note`) and read from there (`_intake_record`); the notes carry the
sentence a reader would write. Older specs still parse: every reader falls back to the line.
"""
from types import SimpleNamespace

from aughor.agent import investigate as I
from aughor.agent.prompts_investigate import IntakeAsk, IntakeOutput
from aughor.govern import departure_basis


def _intake(notes="original notes"):
    return SimpleNamespace(intake_notes=notes)


def test_a_decision_is_recorded_once_and_the_notes_carry_the_readers_sentence():
    it = _intake()
    I._record_intake_note(it, "routing", "Read as a change over time.", route="temporal_change", why="")
    I._record_intake_note(it, "routing", "Read as a change over time.", route="temporal_change", why="")
    assert it.record == [{"tag": "routing", "route": "temporal_change"}]      # empty facts dropped, no dup
    assert it.intake_notes == "Read as a change over time. original notes"
    I._record_intake_note(it, "feasibility", "Margin needs a cost column.", where="back", gap="x")
    assert it.intake_notes.endswith("original notes Margin needs a cost column.")
    assert [r["tag"] for r in it.record] == ["routing", "feasibility"]


def test_the_licence_is_read_from_the_record_before_the_prose():
    data = {"record": [{"tag": "claim_licence", "type": "associational", "why": "a scan of two columns"}],
            "intake_notes": "CLAIM LICENCE: descriptive — an older line that must lose."}
    assert I._recorded_claim_licence(data) == "associational"
    assert "a scan of two columns" in I._claim_licence_section(data, [])
    # the field still wins, the prose still serves an older spec
    assert I._recorded_claim_licence({**data, "claim_type_suggestion": "predictive"}) == "predictive"
    assert I._recorded_claim_licence({"intake_notes": "CLAIM LICENCE: descriptive — old."}) == "descriptive"


def test_the_intake_phase_carries_the_record_and_the_readers_find_it_there():
    phase = I._phase_result("intake", "Question Intake", "", "complete", "s", [],
                            record=[{"tag": "claim_licence", "type": "descriptive", "why": "a period comparison"}])
    assert phase["record"] == [{"tag": "claim_licence", "type": "descriptive", "why": "a period comparison"}]
    # the intake dict reaching synthesis can be lossy; the phase is the copy that survives
    assert I._recorded_claim_licence({}, [phase]) == "descriptive"
    assert "a period comparison" in I._claim_licence_section({}, [phase])
    assert "record" not in I._phase_result("baseline", "b", "", "complete", "s", [])


def test_the_coverage_reframe_reads_the_typed_flag():
    synth = SimpleNamespace(executive_summary="Revenue fell 40% between the windows.", attribution_waterfall=[{"x": 1}],
                            data_gaps=[])
    assert I._reframe_on_pop_duration_mismatch(synth, {"record": [{"tag": "coverage", "duration_mismatch": True}]})
    assert synth.attribution_waterfall == []
    assert not I._reframe_on_pop_duration_mismatch(
        SimpleNamespace(executive_summary="x", attribution_waterfall=[], data_gaps=[]),
        {"record": [{"tag": "coverage", "duration_mismatch": False}], "intake_notes": "fine"})


def test_the_departure_gate_reads_the_record_before_the_prose(monkeypatch):
    stored = {"phases": [{"phase_id": "intake", "record": [{"tag": "claim_licence", "type": "associational"}],
                          "findings": [{"interpretation": "Associational by design: a scan."}]}],
              "causal_checks": {"licence": "associational", "refutation": {"status": "not_run"}}}
    monkeypatch.setattr(departure_basis, "_analysis_record", lambda inv: {"report": stored})
    assert departure_basis.analysis_claim_facts("inv1") == ("associational", False)
    older = {"intake_notes": "CLAIM LICENCE: causal — an intervention.", "causal_checks": {"refutation": {"status": "refuted"}}}
    monkeypatch.setattr(departure_basis, "_analysis_record", lambda inv: {"report": older})
    assert departure_basis.analysis_claim_facts("inv2") == ("causal", True)


def test_the_record_is_set_by_code_and_never_asked_of_the_model():
    assert "record" in IntakeOutput.model_fields and "record" not in IntakeAsk.model_fields
    assert IntakeOutput(metric_label="m", metric_sql="SUM(x)", date_column="t.d", metric_table="t",
                        dimensions=[], intake_notes="").record == []


def test_no_writer_puts_a_tag_in_the_prose():
    """The nine writers, by their sentences: none of the retired tags survives in the source as a
    string written into `intake_notes`."""
    import inspect
    src = inspect.getsource(I)
    for tag in ("CLAIM LICENCE: {", "ROUTING: this is", "TEMPORAL AXIS RECOVERED: the", "MEASURE WARNING: the",
                "NOT OFFERED AS DIMENSIONS: {", "DRIVER CONTRAST DROPPED: {", "SPEC STILL INVALID AFTER", " FEASIBILITY: {"):
        assert tag not in src, tag
