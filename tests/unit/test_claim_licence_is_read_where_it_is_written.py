"""The claim licence must be read from where it is RECORDED, not from an optional field.

`claim_type_suggestion` is declared to the model as "Leave empty unless the question is
clearly weaker than the design allows". `_stamp_claim_type` writes the resolved type back
onto it — and by synthesis the dict reaching that node can carry it empty. Both consumers
then no-op on a falsy value:

  • `_claim_licence_section` returns "" — the synthesis prompt gets no admissible-verbs
    directive at all;
  • `check_claim_type` returns [] without looking at the prose — so the retry that exists
    to fix an overclaim never runs.

Measured on investigation 48865fcf (2026-09-19): the analysis recorded
`CLAIM LICENCE: descriptive`, the report shipped the headline
"…8.9% Increase Driven by Processing Order Volume", the report carried no claim-type
disclosure and MEDIUM confidence — and `check_claim_type("descriptive", prose)` fires on
that exact text. The check simply never ran with a licence. Law 5 caught it at the Slack
door instead: the right verdict, two stages too late, with a model call already spent.

The recorded line is the same fact `govern.departure_basis.analysis_claim_facts` reads off
the stored report. Reading it here is what makes the gate's verdict and the writer's
instruction come from one source.
"""
from aughor.agent.investigate import _claim_licence_section, _recorded_claim_licence

NOTES = ("CLAIM LICENCE: descriptive — this is a period-over-period description of "
         "observational data. Some other note.")


def test_the_recorded_licence_is_found_when_the_field_is_empty():
    """The case that shipped: the field blank, the verdict recorded anyway."""
    assert _recorded_claim_licence({"intake_notes": NOTES}) == "descriptive"


def test_an_explicit_field_still_wins():
    """`_stamp_claim_type` writes the resolved type onto the field; when it survives the
    trip it is the most direct answer and must not be second-guessed by parsing prose."""
    assert _recorded_claim_licence(
        {"claim_type_suggestion": "associational", "intake_notes": NOTES}) == "associational"


def test_nothing_recorded_is_still_nothing():
    """No licence means no licence — this must not invent `descriptive` and silence a
    check that should have run, nor invent `causal` and license an overclaim."""
    assert _recorded_claim_licence({}) == ""
    assert _recorded_claim_licence({"intake_notes": "no licence line here."}) == ""
    assert _recorded_claim_licence(None) == ""


def test_the_synthesis_directive_now_reaches_the_prompt():
    """The whole consequence: with the field empty this returned "", so the model was
    never told which verbs it may use."""
    section = _claim_licence_section({"intake_notes": NOTES}, [])
    assert section.strip(), "a recorded licence must produce a directive"
    assert "may NOT assert" in section, "the directive must name the forbidden verbs"
    assert "drives" in section or "drive" in section


def test_the_shipped_headline_would_now_be_caught():
    """End to end on the sentence that reached Slack: licence recovered from the record,
    fed to the check, check fires."""
    from aughor.agent.report_checks import check_claim_type
    prose = ("Revenue Analysis: September 10, 2026, Shows 8.9% Increase Driven by "
             "Processing Order Volume. The growth was primarily driven by a 2,031.64 "
             "increase in 'Processing' status revenue.")
    licence = _recorded_claim_licence({"intake_notes": NOTES})
    assert check_claim_type(licence, prose), (
        "with the licence recovered, the report check must flag the causal headline "
        "before synthesis returns — not leave it for the departure gate"
    )
