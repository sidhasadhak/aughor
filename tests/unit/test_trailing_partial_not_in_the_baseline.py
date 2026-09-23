"""A mean labelled "full weeks" must be computed over full weeks.

From a real report, 2026-09-23. Its key-numbers line read:

    Full-week mean (Oct 1–Dec 24): ~1253.00 · Full-week range: 1442.00 (+189.0 pts vs avg)
    · Final week (Dec 31): 196 (-86.4% vs prior week) · Weeks observed: 14 (13 full + 1 partial)

Three things are wrong with 1253.00 and they all have the same cause:

* it is BELOW the 1,278 minimum the same report states two lines above it, which is
  arithmetically impossible for a mean of those values;
* the report's own prose computes ~1,334 for the same window;
* 13 full weeks at 1,334 plus the partial week's 196, over 14, is **1252.71**.

So the label said full weeks and the arithmetic used all of them, including the bucket
covering a single day because the query ended mid-week. `+189.0 pts vs avg` inherited it.

The rule applied is the house's own — `tools/profiler._period_density` flags a trailing
partial at `< 0.5 * median` — moved onto the rows so the two cannot disagree about what
"complete" means. And the aggregate's LABEL is restated to the window actually used,
because the defect was half a labelling one: `_set_period` already rewrote the period for
peak and trough, while the average branch replaced the value and left the model's
parenthetical untouched.
"""
from __future__ import annotations

import pytest

from aughor.agent import investigate as I

# The report's own series: 13 full weeks, then a bucket covering one day.
FULL = [1290, 1331, 1353, 1338, 1301, 1318, 1322, 1316, 1329, 1318, 1368, 1305, 1442]
PARTIAL = 196
WEEKS = [f"2023-{m:02d}-{d:02d}" for m, d in
         [(10, 1), (10, 8), (10, 15), (10, 22), (10, 29), (11, 5), (11, 12), (11, 19),
          (11, 26), (12, 3), (12, 10), (12, 17), (12, 24), (12, 31)]]


def _finding(values):
    return {"columns": ["week", "items"],
            "rows": [[w, v] for w, v in zip(WEEKS, values)],
            "key_numbers": [{"label": "Full-week mean (Oct 1 – Dec 24)", "value": "0"},
                            {"label": "Peak week (Oct 1)", "value": "0"}]}


def _recompute(finding):
    """Call the key-number recompute by whichever name it carries."""
    fn = next((getattr(I, n) for n in dir(I)
               if n.startswith("_") and "key_number" in n and callable(getattr(I, n))), None)
    assert fn is not None, "the key-number recompute could not be located"
    fn(finding, is_pct=False)
    return {kn.get("label"): kn.get("value") for kn in finding["key_numbers"]}


def test_the_partial_final_week_is_out_of_the_mean():
    """The defect, as a test. Including it gives 1252.71 — below the series' own minimum."""
    got = _recompute(_finding(FULL + [PARTIAL]))
    mean = float(next(v for k, v in got.items() if "mean" in k.lower()).lstrip("~"))
    assert mean == pytest.approx(sum(FULL) / len(FULL), abs=0.51), got
    assert mean > min(FULL), "a mean below the minimum is arithmetically impossible"


def test_the_label_states_the_window_actually_used():
    """Half the defect was labelling: the value was replaced and the model's parenthetical
    left alone, so a mean over fourteen weeks kept a label that said thirteen."""
    finding = _finding(FULL + [PARTIAL])
    _recompute(finding)
    label = next(kn["label"] for kn in finding["key_numbers"] if "mean" in kn["label"].lower())
    assert "12-31" not in label and "Dec 31" not in label, label


def test_a_series_with_NO_partial_is_untouched():
    """The guard against over-correcting: every week complete, nothing dropped."""
    got = _recompute(_finding(FULL + [1360]))
    mean = float(next(v for k, v in got.items() if "mean" in k.lower()).lstrip("~"))
    assert mean == pytest.approx(sum(FULL + [1360]) / 14, abs=0.51)


def test_an_ordinary_low_final_week_stays_IN_the_baseline():
    """The threshold is deliberately extreme. A genuinely weak final week — down a third,
    not down 85% — is a real observation about the business and must not be explained away
    as an artefact."""
    weak = int(min(FULL) * 0.67)
    got = _recompute(_finding(FULL + [weak]))
    mean = float(next(v for k, v in got.items() if "mean" in k.lower()).lstrip("~"))
    assert mean == pytest.approx(sum(FULL + [weak]) / 14, abs=0.51), "0.67x is not a partial period"


def test_peak_and_trough_still_describe_the_CHART():
    """The narrowing that keeps this honest. The partial week IS the visible minimum, and
    this function exists so the key numbers cannot disagree with the plot — so the trough
    stays 196 even though the mean excludes it. The artefact is named, never hidden."""
    finding = _finding(FULL + [PARTIAL])
    _recompute(finding)
    lows = [kn for kn in finding["key_numbers"] if "peak" in kn["label"].lower()]
    assert lows and float(lows[0]["value"]) == pytest.approx(1442.0, abs=0.51)


def test_a_short_series_is_never_trimmed():
    """Two points give no median to judge a third against, and trimming one of three would
    throw away a third of the evidence on a guess."""
    got = _recompute({"columns": ["week", "items"],
                      "rows": [["2023-10-01", 1000], ["2023-10-08", 100]],
                      "key_numbers": [{"label": "Mean (Oct)", "value": "0"}]})
    mean = float(next(v for k, v in got.items() if "mean" in k.lower()).lstrip("~"))
    assert mean == pytest.approx(550.0, abs=0.51)
