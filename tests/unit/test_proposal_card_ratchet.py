"""SP-9's one-way door: no proposal renderer prints raw params.

The measured break (§3.11, second movement): the approval rows printed
``JSON.stringify(p.params)``, and Attention offered Accept and Reject with no view of
what either creates. The fix is the ONE ProposalCard; this ratchet keeps the fix from
regressing the way one-off cleanups do — a new surface that dumps a proposal's params
object as JSON fails here, by name, before it ships.

Scoped to ``web/`` source (components, app, lib), the same population the vocabulary
ratchet reads. The ban is the WHOLE-OBJECT dump — ``JSON.stringify(<x>.params)`` or
``JSON.stringify(params)`` — not per-value stringification, which labeled fields
legitimately do.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_WEB_DIRS = [_ROOT / "web" / "components", _ROOT / "web" / "app", _ROOT / "web" / "lib"]

#: The banned shape: the params object, serialized in one breath.
_RAW_PARAMS = re.compile(r"JSON\.stringify\(\s*[\w.]*\bparams\b")

#: Declared, visible exemptions — the same shape as the frame-parity test's dynamic
#: sites. Each names the ONE line class it permits and why it is not a renderer.
#: An exemption that stops matching anything fails the test, so a stale entry cannot
#: quietly widen the door.
_EXEMPT: dict[str, str] = {
    # The params EDITOR seeds its text field with the stored object as JSON — the
    # field's contract IS JSON text a person edits, not a rendering of a proposal.
    "web/components/automations/AutomationRows.tsx":
        'return params && typeof params === "object" ? JSON.stringify(params) : "";',
}


def _web_sources():
    for d in _WEB_DIRS:
        for f in (*d.rglob("*.tsx"), *d.rglob("*.ts")):
            # A test's PROSE may name the banned shape (this ratchet's own subject);
            # a test that rendered one would fail its component assertions instead.
            if ".test." not in f.name:
                yield f


def test_no_proposal_renderer_prints_raw_params():
    offenders = []
    matched_exemptions = set()
    for f in _web_sources():
        rel = str(f.relative_to(_ROOT))
        text = f.read_text(errors="ignore")
        for i, line in enumerate(text.splitlines(), start=1):
            if not _RAW_PARAMS.search(line):
                continue
            if _EXEMPT.get(rel, "") == line.strip():
                matched_exemptions.add(rel)
                continue
            offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, (
        "A surface serializes a params object as raw JSON — render it as the "
        "ProposalCard (or labeled fields) instead:\n" + "\n".join(offenders)
    )
    stale = set(_EXEMPT) - matched_exemptions
    assert not stale, f"exemptions that no longer match anything — delete them: {sorted(stale)}"
