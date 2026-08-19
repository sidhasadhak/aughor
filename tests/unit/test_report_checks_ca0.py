"""The report checks after CA-0 — derivation credit, figures-not-sentences, the reader
disclosure, and the headline as its own sentence.

Specimen: investigation cb37be54 (2026-08-19). Evidence rows were
  2026-06-01 → 29903 · 2026-07-01 → 37925 · 2026-08-01 → 32912
and the summary said "reached 37,925 visits in July 2026, representing a 26.8% increase
compared to the 29,903 visits recorded in June 2026". Check #36 flagged the sentence because
26.8 (= (37925 − 29903) / 29903 · 100) appears in no cell, then presented the two correct
quoted figures beside it as fabrications; check #15 quoted the report's TITLE as an
over-claiming sentence because the headline fused with the first summary sentence; and the
repair instruction for the model was concatenated into the customer-facing
confidence_justification.
"""
from __future__ import annotations

from aughor.agent.report_checks import (
    Violation,
    check_claim_type,
    check_grounding,
    reader_disclosure,
    run_report_checks,
)

EVIDENCE = (
    "Monthly Traffic Baseline (Direkteingabe)\n"
    "period | total_traffic\n"
    "2026-06-01 00:00:00 | 29903\n2026-07-01 00:00:00 | 37925\n2026-08-01 00:00:00 | 32912\n"
)
SUMMARY = ("Traffic in the 'Direkteingabe' channel reached 37,925 visits in July 2026, "
           "representing a 26.8% increase compared to the 29,903 visits recorded in June 2026.")


class _Synth:
    def __init__(self, headline, summary, closing="", conf="MEDIUM", just=""):
        self.headline = headline
        self.executive_summary = summary
        self.closing_summary = closing
        self.attribution_waterfall = []
        self.data_gaps = []
        self.confidence = conf
        self.confidence_justification = just


# ── #36: derivation credit ───────────────────────────────────────────────────

def test_a_percent_change_of_two_evidence_values_is_grounded():
    assert check_grounding(SUMMARY, EVIDENCE) == []


def test_a_share_and_a_delta_are_grounded_too():
    assert check_grounding("July was 126.8% of June.", EVIDENCE) == []          # b/a·100
    assert check_grounding("July added 8,022 visits over June.", EVIDENCE) == []  # b−a
    assert check_grounding("August fell 13.2% from July.", EVIDENCE) == []      # |b−a|/a·100 (13.2)


def test_a_figure_no_arithmetic_reaches_is_still_flagged_and_named_as_a_figure():
    v = check_grounding("Traffic reached 41,500 visits in July 2026, up 26.8% on June.", EVIDENCE)
    assert len(v) == 1
    assert "41,500" in v[0], v[0]
    assert "26.8" not in v[0].split("(in")[0], "the grounded figure must not be listed as missing"
    # the reader sentence names the figure, not the instruction
    assert isinstance(v[0], Violation)
    assert "41,500" in v[0].disclosure and "replace" not in v[0].disclosure


# ── #15: the headline is its own sentence; change verbs are descriptive ───────

def test_descriptive_licence_allows_the_verbs_of_change():
    prose = ("Investigation into July 2026 Traffic Peak in Direkteingabe Channel. " + SUMMARY +
             " Decomposition analysis across device classes and browser types shows no significant "
             "variation, with every segment recording a comparable increase.")
    assert check_claim_type("descriptive", prose) == []


def test_descriptive_licence_still_refuses_an_agent_changing_a_thing():
    v = check_claim_type("descriptive", "The August newsletter increased direct traffic.")
    assert v and "#15" in v[0]
    assert isinstance(v[0], Violation) and "#15" in v[0].disclosure


def test_the_headline_does_not_fuse_with_the_summary():
    # The headline alone is descriptive; the summary alone is descriptive. Joined without a
    # period they used to read as one sentence containing the summary's "increase" with the
    # headline quoted as the culprit.
    synth = _Synth("Investigation into July 2026 Traffic Peak in Direkteingabe Channel", SUMMARY)
    assert run_report_checks(synth, "Why is traffic going up?", EVIDENCE, [], "descriptive") == []


# ── the leak: reader disclosure, never the instruction ───────────────────────

def test_reader_disclosure_carries_no_imperative():
    synth = _Synth("Traffic peaked at 41,500", "Up 26.8% on June.")
    violations = run_report_checks(synth, "Why?", EVIDENCE, [], "descriptive")
    assert violations
    text = reader_disclosure(violations)
    assert text.startswith("Deterministic checks after the repair attempt:")
    assert "41,500" in text and "(#36)" in text
    for forbidden in ("replace each", "Restate", "FULL EVIDENCE", "change nothing"):
        assert forbidden not in text, forbidden
    # the repair instruction is still the string value (what the model retry sees)
    assert "replace each with the evidence's own value" in violations[0]


def test_reader_disclosure_falls_back_to_the_pitfall_number_for_plain_strings():
    assert reader_disclosure(["#36 (x): some legacy instruction — do this"]) == \
        "Deterministic checks after the repair attempt: a deterministic check flagged the summary (#36)."
    assert reader_disclosure([]) == ""


def test_a_change_noun_followed_by_a_verb_is_not_a_transitive_claim():
    # live false positives from the first receipt run: "Traffic Increase Halted by…",
    # "the traffic increase could not be completed"
    for sentence in (
        "Investigation into Direkteingabe Traffic Increase Halted by Database Access Errors.",
        "The investigation into the January 2026 Direkteingabe traffic increase could not be completed.",
        "The increase was broad across segments.",
    ):
        assert check_claim_type("descriptive", sentence) == [], sentence
