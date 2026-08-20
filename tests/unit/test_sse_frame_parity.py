"""Every SSE frame the ask surface emits must have a consumer — or a named reason.

The frontend's frame dispatcher (`consumeStream`'s `switch (p.type)`) has no permissive
fallthrough, so a frame nobody handles is indistinguishable from a frame nobody sent: it
vanishes, the turn still completes, and the UI looks fine. Nine frame types were reaching
no consumer that way before this test existed — including `paused`, whose sibling branch
`plan_pending` *is* handled, so a run that pauses for review would render as a finished,
empty answer.

Same spirit as the chart-vocab parity test and the api.gen.ts drift check: read the
artifacts that actually ship, on both sides of the seam, and fail when they disagree. A
new backend frame now has exactly two honest destinations — a `case` in the dispatcher,
or an entry in `UNRENDERED_FRAMES` stating why it renders nowhere.

The parser refuses to guess. Its first version matched only string literals and so missed
`learning` and `activations`, which are emitted from a loop over a tuple of names — the
exact "guard whose key stops matching" failure this file warns about, committed inside the
guard itself. Dynamic call sites must now be declared below, and an undeclared one fails
the test rather than being silently skipped.

It happened a second time, predictably, when `_stream_chat` split into `_answer_core` +
a streaming wrapper: the quick path stopped calling `_sse` and started calling `emit`, and
fourteen frame names left `emitted` in one commit while every one of them was still on the
wire. So the parser reads the EMISSION VOCABULARY (`_sse("x"` and `emit("x"`), not one
function's name. The wrapper's own `_sse(_frame_type, payload)` is the transport, not a
source of names — it re-serializes tuples the core already declared literally — and it is
registered below as carrying nothing new, rather than being hidden from the parser.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _ROOT / "aughor" / "routers" / "investigations.py"
# CA-1 retired the 107-case reducer; the consumer side is now three artifacts.
# `chatTurn.ts` PROJECTS a frame into the turn, `uiMessageAdapter.ts` routes the
# prose frames to text channels, and `aughorUIDataTypes.ts` declares the frames
# that deliberately render nothing.
_PROJECTION = _ROOT / "web" / "lib" / "chatTurn.ts"
_ADAPTER = _ROOT / "web" / "lib" / "uiMessageAdapter.ts"
_DATA_TYPES = _ROOT / "web" / "lib" / "aughorUIDataTypes.ts"

_NAME = r"[A-Za-z_][A-Za-z0-9_]*"

#: How a frame is named at its call site. `_sse` is the wire encoder; `emit` is the
#: callback the sync answer core reports through — the same vocabulary, one hop earlier.
#: The lookbehind keeps `session_log.emit(` and `Ledger.emit(` (different contracts, not
#: SSE) out of the parse.
_EMIT = r"(?:_sse|(?<![\w.])emit)"

#: Emission calls whose first argument is a variable, not a literal. Each maps the variable
#: to every frame name it can carry, so the contract stays checkable. Adding a dynamic site
#: without registering it here fails `test_no_unreadable_emission_sites`.
_DYNAMIC_SITES: dict[str, frozenset[str]] = {
    # investigations.py: `for _evt in ("learning", "activations"): emit(_evt, ...)`
    "_evt": frozenset({"learning", "activations"}),
    # investigations.py, THREE relay sites, all making the same claim: `_stream_chat` and
    # `_stream_converse` re-serializing what the bridge handed them, and `_stream_converse`'s
    # `_forward` passing a tool's frames on unchanged. None contributes a name of its own —
    # every tuple they carry was created by an `emit("literal", …)` call the parser has
    # already read. Declared empty rather than filtered out, so the sites stay visible here
    # instead of being invisible to the parser; the two tests below check the claim.
    "_frame_type": frozenset(),
}


def _emitted_frames() -> set[str]:
    """Frame names the ask surface sends — literal call sites plus declared dynamic ones."""
    src = _BACKEND.read_text()
    frames = set(re.findall(rf'{_EMIT}\(\s*"({_NAME})"', src))
    for var in _dynamic_vars(src):
        frames |= _DYNAMIC_SITES[var]        # KeyError is impossible: the test below gates it
    return frames


def _dynamic_vars(src: str) -> set[str]:
    """Variables passed as the frame name, excluding the encoder's own def."""
    return {
        v for v in re.findall(rf"{_EMIT}\(\s*({_NAME})\s*,", src)
        if v != "event_type"                 # `def _sse(event_type: str, data: dict)`
    }


def _consumed_frames() -> tuple[set[str], set[str]]:
    """(rendered, deliberately-unrendered) as declared by the shipping frontend.

    Post-CA-1 a frame is RENDERED if the projection has a projector for it, or the
    adapter routes it to a text channel (prose frames become channel-stamped text
    parts, not data parts). Everything else is either declared unrendered or —
    the property the closed switch could not offer — reaches the shell named, as
    a labelled block. That escape hatch is why this gate no longer guards against
    silence; it guards against a frame nobody chose to render.
    """
    proj = _PROJECTION.read_text()
    start = proj.index("const PART_PROJECTORS")
    body = proj[start:proj.index("export const PROJECTED_PARTS")]
    # One indent level: the map's own keys, never a nested object's.
    projected = set(re.findall(rf'^  ({_NAME})\s*:', body, re.M))
    projected |= set(re.findall(rf'^  "({_NAME})"\s*:', body, re.M))

    adapter = _ADAPTER.read_text()
    tc = re.search(r"const TEXT_CHANNELS[^=]*=\s*\{(.*?)\n\};", adapter, re.S)
    assert tc, "TEXT_CHANNELS not found — the adapter moved; update this parser"
    projected |= set(re.findall(rf'^  ({_NAME})\s*:', tc.group(1), re.M))

    types = _DATA_TYPES.read_text()
    m = re.search(r"export const UNRENDERED_FRAMES[^=]*=\s*new Set\(\[(.*?)\]\)", types, re.S)
    assert m, "UNRENDERED_FRAMES not found — the declaration moved; update this parser"
    return projected, set(re.findall(rf'"({_NAME})"', m.group(1)))


def test_no_unreadable_emission_sites():
    """The parser must never skip a call site it cannot read.

    Without this, a frame emitted through a variable is absent from `emitted`, so the
    parity test below passes while that frame drops on the floor — a green guard over an
    unguarded seam, which is worse than no guard at all.
    """
    undeclared = _dynamic_vars(_BACKEND.read_text()) - set(_DYNAMIC_SITES)
    assert not undeclared, (
        f"_sse() called with undeclared variable(s) {sorted(undeclared)}. Register the frame "
        "names in _DYNAMIC_SITES, or pass a string literal so the contract stays readable."
    )


def _top_level_body(marker: str) -> str:
    """The source of one top-level function, from its `def` to the next one."""
    src = _BACKEND.read_text()
    body = src[src.index(marker):]
    end = re.search(r"\n(?:@|async def |def |class )", body[1:])
    return body[: end.start()] if end else body


def test_the_relay_really_does_only_relay():
    """`_frame_type` is declared above as carrying no names of its own. That is a claim
    about `_stream_chat`, so check it instead of trusting it: the wrapper may encode the
    relayed tuple and its own terminal `error`, and nothing else. A third `_sse(...)` there
    would be a frame the parser cannot see, which is the exact hole `_DYNAMIC_SITES` exists
    to close."""
    body = _top_level_body("async def _stream_chat(")

    first_args = re.findall(r"_sse\(\s*([^,)]+)\s*,", body)
    assert sorted(first_args) == ['"error"', "_frame_type"], (
        f"_stream_chat encodes frames the parser cannot read: {first_args}. Every other "
        "frame must be named literally at an `emit(\"…\")` call inside `_answer_core`."
    )


def test_the_converse_relay_relays_too_and_names_its_own_frames_literally():
    """The same claim, for the second body — otherwise the converse path is an UNGUARDED
    copy of the guarded one, and a green guard over an unguarded seam is worse than none.

    Two halves, because the converse wrapper does two things `_stream_chat` does not. It
    ENCODES (the `_sse` half, identical contract: the relayed tuple plus its own terminal
    `error`). And it MINTS — the turn's own `converse_step` / `mode` / `headline` / `done`
    — which is exactly why those must be literal here: a frame the converse body invented
    behind a variable would reach the wire while the parity gate below reported full
    coverage.
    """
    body = _top_level_body("async def _stream_converse(")

    first_args = re.findall(r"_sse\(\s*([^,)]+)\s*,", body)
    assert sorted(first_args) == ['"error"', "_frame_type"], (
        f"_stream_converse encodes frames the parser cannot read: {first_args}."
    )

    minted = re.findall(rf'(?<![\w.])emit\(\s*"({_NAME})"', body)
    assert set(minted) >= {"converse_step", "headline", "done"}, (
        f"the converse body no longer names its own terminal frames literally: {minted}. "
        "A turn that emits no `headline` renders empty, and one that emits no `done` never "
        "finishes — both are silent, and both are what these literals make checkable."
    )
    dynamic = {v for v in re.findall(rf'(?<![\w.])emit\(\s*({_NAME})\s*,', body)}
    assert dynamic <= {"_frame_type"}, (
        f"the converse body emits through undeclared variable(s) {sorted(dynamic)} — "
        "register them in _DYNAMIC_SITES or name the frame literally."
    )


def test_every_emitted_frame_has_a_consumer_or_a_stated_reason():
    """The gate. Before CA-1 a frame with neither was a SILENT drop; now it reaches
    the shell as a labelled "unrecognised" block — visible, but still not rendered.
    Visible-but-unrendered is a cheaper bug than silence and a worse one to ship, so
    the gate stands: every emitted frame is projected, routed to a text channel, or
    named as deliberately unrendered."""
    emitted = _emitted_frames()
    assert emitted, "parsed zero frames — the _sse() call shape changed; fix the parser"

    rendered, unrendered = _consumed_frames()
    assert rendered, "parsed zero projectors — the projection moved; fix the parser"

    orphaned = emitted - rendered - unrendered
    assert not orphaned, (
        f"SSE frames emitted with no consumer and no stated reason: {sorted(orphaned)}. "
        "Add a projector to chatTurn.ts's PART_PROJECTORS (or a TEXT_CHANNELS entry for "
        "prose), or add the name to UNRENDERED_FRAMES with the reason it renders nowhere."
    )


def test_unrendered_list_does_not_outlive_its_frames():
    """The other direction: a name kept here after the backend stopped sending it is stale
    documentation, and stale documentation is how the list stops being read.

    This is the failure mode that blinded the contract scanner in #251 (266 paths -> 0) and
    the fleet orphan split: a guard whose key no longer matches anything keeps passing
    while guarding nothing.
    """
    emitted = _emitted_frames()
    _, unrendered = _consumed_frames()
    stale = unrendered - emitted
    assert not stale, (
        f"UNRENDERED_FRAMES names frames the backend no longer emits: {sorted(stale)}. "
        "Drop them — the list is only useful while every entry is live."
    )


#: Projectors with no producer IN THE SCANNED SURFACE. Kept, not deleted, because a
#: frontend that still understands an older wire name is what makes a rolling deploy safe,
#: because a RESTORED turn replays these names from storage where old rows still carry
#: them, and because one of them is produced by a router this parser does not read.
#: Tracked here so the set cannot grow quietly:
#:   answer, insight, insight_delta — pre-rename spellings (`headline`, `narrative`)
#:   figure                         — the AG-UI seam's composite frame (routers/agui.py,
#:                                    a different surface than the `/ask` one scanned here)
#:   status                         — declared in the part vocabulary; the native stream
#:                                    spells progress with phase frames, so the projector
#:                                    is defensive rather than dead
_CASES_WITHOUT_PRODUCER = frozenset({
    "answer", "insight", "insight_delta", "figure", "status",
})


def test_dispatcher_has_no_new_cases_without_producers():
    """The third direction. Rot arrives from the frontend side too: a projector for a
    frame the backend no longer sends reads as coverage while covering nothing."""
    emitted = _emitted_frames()
    rendered, _ = _consumed_frames()
    # `ada_report` is a documented deliberate alias handled beside `answer_report`.
    unclaimed = rendered - emitted - _CASES_WITHOUT_PRODUCER - {"ada_report"}
    assert not unclaimed, (
        f"projectors with no backend producer: {sorted(unclaimed)}. Delete them, or "
        "add to _CASES_WITHOUT_PRODUCER with the reason the compatibility branch stays."
    )
