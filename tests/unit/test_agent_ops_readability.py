"""The Agent Ops surface obeys the platform's design system, and draws in tokens.

**This file used to enforce a local type and colour rule, and that was a mistake.** W4
measured the palette and concluded that `--t2` should be the floor for text and 12px the
floor for prose, then pinned it on thirteen Agent Ops files. The platform re-skin (#365,
#367) subsequently made a different, deliberate choice, and it is the one that governs:
across `components/` and `app/`, `--t4` is used as a text colour 357 times in 64 files, a
ramp's `3` step 35 times, and `fontSize: 11` 653 times in 60 files. A rule that binds
thirteen files against the house style of sixty does not make those thirteen more
readable — it makes them look like a different product.

The contrast measurement itself still stands and is not thrown away:

    --t1  14.88:1   --t2  6.68:1   --t3  4.23:1 (fails AA normal)   --t4  2.76:1 (fails AA large)

If those tones are genuinely too faint for text, the fix belongs in the token layer, where
lifting `--t3`/`--t4` repairs all 392 sites at once and the whole product stays coherent.
It does not belong in a per-surface ratchet that quietly forks the design. That question is
open and deliberately not decided here.

What survives is the rule that is about correctness rather than taste: a chart that
hardcodes hexes is theme-blind, and no amount of design direction makes it flip in light
mode.
"""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"

#: The surface. Kept so the guard below cannot silently start reading nothing.
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


def test_the_surface_files_all_exist():
    """A guard whose files moved is a guard reading nothing — the failure mode this repo
    has shipped twice (a matching key that stopped matching, silently)."""
    missing = [rel for rel in SURFACE if not (WEB / rel).exists()]
    assert not missing, f"the Agent Ops guard is scanning files that no longer exist: {missing}"


def test_t4_is_never_a_text_colour_on_this_surface():
    """The ONE type rule this surface keeps, chosen by the user 2026-08-22: content off the
    faint end, everything else follows the platform.

    `--t4` is **2.76:1** on `--bg-0` — below AA for large text, let alone body. A `color:`
    is by definition text, so there is no legitimate use of it here; borders and fills name
    their own properties and are untouched. This is deliberately NARROWER than the rule that
    used to live in this file: font sizes, spacing and every other token follow the re-skin
    exactly, and `--t3` (4.23:1, which clears AA-large) is left alone outside `aug-label`.

    The platform-wide question — whether `--t3`/`--t4` should be lifted in the token layer,
    repairing all ~392 sites at once — is open and NOT decided by this test.
    """
    offenders = {rel: src.count('color: "var(--t4)"')
                 for rel, src in ((r, (WEB / r).read_text()) for r in SURFACE if (WEB / r).exists())}
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, (
        f"--t4 is 2.76:1 and is used as a text colour in {offenders}. "
        "Use --t2 (6.68:1) for content; keep the re-skin's sizes and every other token.")


def test_the_shared_sparkline_draws_in_tokens_not_hexes():
    """`Sparkline` is the one trend primitive the whole platform draws through, and it
    hardcoded #818cf8 / #34d399 / #f87171 — so it was also the only one that did not flip
    in light mode. A theme-aware surface with a theme-blind chart in it is not one. This
    is orthogonal to any re-skin: whatever the palette becomes, a literal hex ignores it.
    """
    src = (WEB / "components/brief/Sparkline.tsx").read_text()
    hexes = re.findall(r"#[0-9a-fA-F]{6}", src)
    assert not hexes, f"Sparkline still hardcodes {hexes} — use var(--chart-*)/var(--grn4)."
