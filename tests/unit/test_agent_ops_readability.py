"""W4 — the Agent Ops surface stays readable, as a ratchet rather than a style note.

Measured on the tokens this product actually ships (WCAG 2.1 contrast, dark ground
`--bg-0` #0D1117):

    --t1  14.88:1   values
    --t2   6.68:1   labels, captions          ← the floor for text
    --t3   4.23:1   FAILS AA normal (4.5)
    --t4   2.76:1   FAILS AA large (3.0)

The old surface put labels on `--t3` and captions on `--t4`, so the two things a reader
needs in order to know what a number MEANS were the two least legible things on the page.
Nothing was wrong with the palette — every ramp's `4`/`5` step and `--t1`/`--t2` clear AA
comfortably — the panels simply reached for the faint ones.

Guards key on the file, not on a word: this counts colour assignments and font sizes in the
Agent Ops components, which is a structural fact. Every vocabulary-keyed guard in this
repo's history false-positived within two runs.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"

#: The surface. A file added here is a file that must obey the rule.
SURFACE = [
    "components/FleetOverviewPanel.tsx",
    "components/NeedsHumanPanel.tsx",
    "components/ActivityStreamPanel.tsx",
    "components/AgenticActivityPanel.tsx",
    "components/AgenticOpsWorkspace.tsx",
    "components/RunGraphsPanel.tsx",
    "components/AgenticAgentsPanel.tsx",
    "components/TraceExplorerPanel.tsx",
    "components/agentops/ActivityChart.tsx",
    "components/agentops/ProvenanceDrawer.tsx",
    "components/agentops/RangePicker.tsx",
    "components/agentops/RunTimeline.tsx",
    "components/agentops/UsagePanel.tsx",
]


def _sources() -> list[tuple[str, str]]:
    out = []
    for rel in SURFACE:
        p = WEB / rel
        if p.exists():
            out.append((rel, p.read_text()))
    return out


def test_the_surface_files_all_exist():
    """A guard whose files moved is a guard reading nothing — the failure mode this repo
    has shipped twice (a matching key that stopped matching, silently)."""
    missing = [rel for rel in SURFACE if not (WEB / rel).exists()]
    assert not missing, f"the readability ratchet is scanning files that no longer exist: {missing}"


@pytest.mark.parametrize("rel,src", _sources(), ids=[r for r, _ in _sources()])
def test_t4_is_never_a_text_colour(rel: str, src: str):
    """`--t4` is 2.76:1 — below AA even for large text. It is a BORDER/disabled tone."""
    hits = re.findall(r'color:\s*"var\(--t4\)"', src)
    assert not hits, (
        f"{rel} sets text to --t4 ({len(hits)}×), which is 2.76:1 on --bg-0. "
        "Use --t2 (6.68:1) for labels and captions.")


@pytest.mark.parametrize("rel,src", _sources(), ids=[r for r, _ in _sources()])
def test_no_text_below_twelve_pixels(rel: str, src: str):
    """The root font-size here is 13px, and the scale's floor is 11px — but 11px is for
    dense tabular mono, not prose. Captions that explain a number sit at 12."""
    hits = re.findall(r"fontSize:\s*(?:11(?:\.\d+)?|10(?:\.\d+)?|[0-9])\b", src)
    assert not hits, (
        f"{rel} sets {len(hits)} font size(s) below 12px. Use the scale "
        "(`aug-fs-xs` / `aug-fs-sm`) or 12.")


@pytest.mark.parametrize("rel,src", _sources(), ids=[r for r, _ in _sources()])
def test_semantic_colour_uses_the_text_grade_step(rel: str, src: str):
    """`--red3`/`--vio3` are 3.34:1 and 2.63:1 as TEXT and both fail AA. The `4` step of
    each ramp is the text-grade one (`--red4` 4.85:1, `--vio4` 4.57:1); the `3` step is
    the base for fills and borders, where contrast is not a reading requirement."""
    hits = re.findall(r'color:\s*"var\(--(?:red|vio|grn|blue|amb|cyn)3\)"', src)
    assert not hits, (
        f"{rel} uses a ramp's `3` step as a text colour ({len(hits)}×). "
        "Use the `4` step for text; `3` is for fills and borders.")


def test_the_shared_sparkline_draws_in_tokens_not_hexes():
    """`Sparkline` is the one trend primitive the whole platform draws through, and it
    hardcoded #818cf8 / #34d399 / #f87171 — so it was also the only one that did not flip
    in light mode. A theme-aware surface with a theme-blind chart in it is not one."""
    src = (WEB / "components/brief/Sparkline.tsx").read_text()
    hexes = re.findall(r"#[0-9a-fA-F]{6}", src)
    assert not hexes, f"Sparkline still hardcodes {hexes} — use var(--chart-*)/var(--grn4)."
