"""A statistical verdict must reach the page, not just the record.

Found 2026-09-18 in the user's own exported report (run 29c3c169). `stats.py` attached this
to the first finding:

    PARTIAL FINAL PERIOD: September 2026 holds 21 of 30 days (70%) — its total is not
    comparable to a full month; compare per-day rates, and do not read the smaller total
    as a drop or a correction. Per day: September 2026 16,301 vs previous month 8,664.

Not one phrase of it reached the PDF. What the reader got instead was "Gross margin has
trended upward significantly, reaching $342,313 in September 2026 … a latest
period-over-period increase of 27.4%" — a 70%-complete month quoted as a trend point,
exactly what the warning said not to do.

Two independent causes, both pinned here.

1. **The exporters never read the field.** `document.py` sets `tag=<stat_note>` on every
   FINDING block, and both `_flow` implementations render `block.tag` only in their PROSE
   branch. Measured over the stored corpus: 630 findings carry a stat_note and none of them
   could ever reach a PDF or a deck — every z-score, every significance verdict, every
   completeness warning, discarded at the last step.

2. **The prompt asked nicely.** The partial-period verdict is shown to the model alongside
   two siblings that each end in an imperative ("Do NOT call any value here significant…",
   "A PROPORTIONAL split is NOT a finding…"). It alone just stated a fact. Of the 7 stored
   investigations where it fired, 3 never told the reader (09-04, 09-15, 09-18) and 4 did —
   a coin flip on a correctness-critical caveat.
"""
import inspect
import re

import pytest

from aughor.export import document as DOC
from aughor.export import pdf as PDF
from aughor.export import slides as SLIDES
from aughor.agent import investigate as I


def _finding_branch(src: str) -> str:
    """The body of a renderer's `kind == "finding"` branch, up to the next branch."""
    start = src.find('kind == "finding"')
    assert start > 0, "the finding branch moved — re-pin this test"
    nxt = re.search(r'\n\s+elif\s+b(?:lock)?\.kind\s*==', src[start:])
    return src[start: start + (nxt.start() if nxt else len(src) - start)]


class TestTheExportersRenderIt:
    @pytest.mark.parametrize("mod", [PDF, SLIDES], ids=["pdf", "slides"])
    def test_the_finding_branch_reads_the_tag(self, mod):
        """`document.py` sets `tag` on a finding; a renderer that ignores it silently
        drops every statistical verdict the run produced."""
        assert ".tag" in _finding_branch(inspect.getsource(mod)), (
            "a finding's statistical verdict is discarded on export")

    @pytest.mark.parametrize("mod", [PDF, SLIDES], ids=["pdf", "slides"])
    def test_it_is_not_shouted(self, mod):
        """On a finding this field is a SENTENCE (200+ chars), not a prose block's short
        label ("Caveat"); upper-casing it shouts a paragraph at the reader.

        Comments are stripped first — the branch's own comment explains the rule and
        names the call, which a naive grep reads as the violation it warns against."""
        branch = _finding_branch(inspect.getsource(mod))
        code = "\n".join(l for l in branch.splitlines() if not l.lstrip().startswith("#"))
        assert ".upper()" not in code, "the verdict is a sentence, not a label"


class TestCompletenessIsNotSignificance:
    def test_the_note_is_not_gated_on_is_significant(self):
        """The two are orthogonal: `is_significant` says a CHANGE cleared a threshold; the
        note also says whether the DATA behind it is complete. Gating one on the other
        suppressed the partial-period warning on exactly the findings whose change was not
        significant — when a reader is most likely to read a short month as a decline.
        `web/components/brief/StatBadge.tsx` already states this rule for the same field."""
        src = inspect.getsource(DOC)
        m = re.search(r'tag=\(f\.get\("stat_note"\)[^\n]*', src)
        assert m, "the stat_note tag assignment moved — re-pin this test"
        assert "is_significant" not in m.group(0), (
            "a completeness warning is suppressed when the change is not significant")

    @pytest.mark.parametrize("significant", [True, False], ids=["significant", "not"])
    def test_the_warning_survives_either_way(self, significant):
        """End to end through the real builder: the run 29c3c169 shape, both ways round."""
        NOTE = "PARTIAL FINAL PERIOD: September 2026 holds 21 of 30 days (70%)."
        inv = {"question": "Where are we losing money since last 6 months?",
               "report": {"_report_type": "investigate",
                 "headline": "Margin rose 27.4%", "executive_summary": "It reached $342,313.",
                 "phases": [{"phase_name": "Baseline", "phase_id": "baseline",
                             "phase_icon": "", "status": "complete", "summary": "",
                             "findings": [{
                                 "finding_id": "b0", "title": "Monthly Gross Margin Baseline",
                                 "claim": "Margin rose 27.4%",
                                 "interpretation": "It reached $342,313 in September 2026.",
                                 "stat_note": NOTE, "is_significant": significant,
                                 "key_numbers": [], "rows": [], "columns": [],
                                 "sql": "", "row_count": 0, "error": None,
                             }]}]}}
        doc = DOC.build_export_doc(inv)
        tags = [b.tag or "" for b in doc.blocks if b.kind == "finding"]
        assert any(NOTE in t for t in tags), (
            f"the completeness warning never reached the document (is_significant={significant})")


class TestThePromptObliges:
    def test_the_partial_verdict_carries_an_imperative(self):
        """Its two siblings each end in one. Stating a fact and hoping produced a 4-of-7
        hit rate on telling the reader at all."""
        src = inspect.getsource(I._results_text_with_verdicts)
        i = src.find("_partial_terminal_period_note")
        assert i > 0
        tail = src[i:]
        assert "MUST" in tail, "the partial-period verdict still only states a fact"
        assert "OVERRIDES" in tail, "it does not outrank the rows the model is reading"

    def test_all_three_verdicts_are_obligations(self):
        """A reader cannot tell which caveat was optional, so none of them may be."""
        src = inspect.getsource(I._results_text_with_verdicts)
        assert src.count("OVERRIDES what the") >= 3


# ── The web is the third surface ──────────────────────────────────────────────
# Found by the producer→surface ratchet on 2026-09-18, AFTER the PDF and the deck were
# fixed: `stat_note` was declared on the web's finding interface and read nowhere under
# `web/`, and `SignificanceBadge` — written to display it — was imported by nothing. So the
# warning was missing from all THREE surfaces, and the fix that "restored it for the
# reader" had restored it for two.
#
# The web's clean-output policy ("the significance verdict + stat note are VERIFICATION
# machinery — they live in the Trust Receipt / Details, never in the body") is right about
# HALF of a stat note and wrong about the other half, which is why the note is split rather
# than the policy overruled: the verdict rides the verification row, the warning sits with
# the number it qualifies.

import pathlib
import re as _re

_WEB_REPORT = pathlib.Path(__file__).resolve().parents[2] / "web" / "components" / "InvestigationReport.tsx"


def _web_markers() -> list[str]:
    src = _WEB_REPORT.read_text()
    m = _re.search(r"const STAT_WARNING_MARKERS = \[(.*?)\]", src, _re.S)
    assert m, "the web mirror is gone — the split cannot work without it"
    return _re.findall(r'"([^"]+)"', m.group(1))


class TestTheMarkersCannotDrift:
    def test_python_and_the_web_agree(self):
        """The same arrangement `chart_vocab.JOB_TO_FORM` has with chartTypeInference.ts.
        A marker reworded on one side silently stops splitting on the other: the warning
        would then render as part of the z-score, in muted mono, on the Details row."""
        from aughor.agent.investigate import READER_FACING_STAT_MARKERS
        assert list(READER_FACING_STAT_MARKERS) == _web_markers()

    def test_each_marker_is_actually_emitted(self):
        """A marker nothing writes is a split that never fires. Both are interpolated into
        the producers, so this reads the source rather than trusting the constant."""
        import inspect

        from aughor.agent import investigate as I
        src = inspect.getsource(I)
        for name in ("PARTIAL_PERIOD_MARKER", "EXPOSURE_CHECK_MARKER"):
            assert src.count(f"{{{name}}}") >= 1, (
                f"{name} is declared but never interpolated into a note")


class TestTheWebShowsBothHalves:
    def test_the_badge_is_imported(self):
        """It existed for this and was imported by nothing for months."""
        assert "SignificanceBadge" in _WEB_REPORT.read_text()

    def test_the_warning_renders_in_the_body(self):
        src = _WEB_REPORT.read_text()
        assert "{warning && (" in src, "the completeness warning is not rendered"
        assert "{verdict && (" in src, "the significance verdict is not rendered"

    def test_the_split_is_declared_not_sniffed(self):
        """A capitals scan would split on 'THE OUTNET' — a retailer's name quoted out of
        the data, which is 9 of the 630 stored notes."""
        src = _WEB_REPORT.read_text()
        assert "STAT_WARNING_MARKERS" in src
        assert "A-Z]{3,}" not in src, "the split sniffs for capitals instead of declaring"
