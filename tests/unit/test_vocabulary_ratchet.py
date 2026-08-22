"""Wave W · P0 — the glossary is ENFORCED, not just written.

`docs/GLOSSARY.md` says one word per concept. A glossary nobody checks is a document that
drifts, and this repo has the receipts: the 2026-07-03 review already wrote NOM-01…NOM-12
naming a dozen of these collisions, and a survey on 2026-08-01 found nine of them still
live, plus new ones. Writing it down a second time changes nothing on its own.

So the vocabulary ships as a **one-way ratchet** instead of a rule. Each retired term has a
measured baseline; a PR may lower a baseline, never raise it. Nothing is required to reach
zero in one PR — the counts fall as files are touched by normal work, which is what keeps
this from becoming a sweep that conflicts with every in-flight branch.

Baselines measured 2026-08-01 on `main`+P0. If one legitimately must rise (a new connector
whose product name is genuinely part of an integration), exempt the path rather than raising
the number — an exemption states a reason, a raised number states nothing.
"""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Where retired vocabulary is enforced. `docs/` is deliberately absent: study documents and
#: wave arcs are historical records, and rewriting history to match today's names would
#: destroy the reason the code looks like it does.
CODE_ROOTS = ("aughor", "web", "tests", "scripts", "evals")

_SKIP_PARTS = {"__pycache__", "node_modules", ".next", ".git", "dist", "build"}
_SKIP_FILES = {
    "web/lib/api.gen.ts", "web/package-lock.json", "uv.lock",
    # This file NAMES every retired term — in the table below and in its own failure
    # messages. Counting itself made all 21 baselines look breached on the first run.
    "tests/unit/test_vocabulary_ratchet.py",
    # A frozen RECORDING of real API responses, not authored prose. The ratchet governs
    # the vocabulary we write; this file is the backend's wire format and the model's own
    # output, captured verbatim — scanning it measures neither. Renaming a term inside it
    # would also make it stop matching the API it mirrors, which is the same reason
    # `web/lib/api.gen.ts` is exempt. (It moved four baselines on first commit: `insight`
    # +41 from finding payloads, `investigation_in_web` +41 from route names, and
    # `tableau` +2 from the dataset's actual title, "Tableau Sample Superstore".)
    "web/public/demo-api.json",
}
_EXTS = {".py", ".ts", ".tsx", ".css", ".yaml", ".yml", ".json"}

#: term → (pattern, roots it is enforced in, paths exempt from it, why it is retired).
#: The canonical replacement for each is in `docs/GLOSSARY.md`.
BANNED: dict[str, tuple[str, tuple[str, ...], tuple[str, ...], str]] = {
    # ── Internal jargon ───────────────────────────────────────────────────────────────
    "ada": (
        r"\bADA\b|\bada[._]", CODE_ROOTS,
        # `ada_report` is a frame the backend emits. The data-part map exists to make
        # the part NAMES a closed, checkable set, so it must spell them exactly as the
        # wire does — renaming one here would silently stop matching the frame it is
        # meant to declare, which is the failure the map was added to prevent.
        ("web/lib/aughorUIDataTypes.ts",),
        "an acronym that expands, in its own docstring, to words it does not spell; "
        "say 'deep analysis'",
    ),
    "insight": (
        r"(?i)insight", CODE_ROOTS,
        # Exempt because they name FROZEN WIRE/API identifiers verbatim, and a test that
        # renamed them would assert a contract the backend does not speak:
        #   test_stream_chat_transcript — `insight` / `insight_delta` are SSE event types.
        #   test_converse_route_off_state, probe_converse_turn — `insight_id` is a field on
        #     AskRequest; both construct request shapes to prove the /ask door's behaviour.
        #   ci0_scorecard — `insight` is the FROZEN report_json key quick-turn prose is
        #     stored under; the CI-0 scorecard reads the historical store as written.
        # Same reason api.ts and uiMessageAdapter.ts are exempt from `investigation_in_web`.
        ("tests/integration/test_stream_chat_transcript.py",
         "tests/unit/test_converse_route_off_state.py",
         "scripts/probe_converse_turn.py",
         "scripts/ci0_scorecard.py",
         # CI-2's findings tool reads the explorer store, whose frozen state key is the
         # retired term; the test constructs fake states carrying the same key. Both
         # already speak 'findings' everywhere the word is theirs to choose.
         "aughor/agent/platform_tools.py",
         "tests/unit/test_platform_tools.py",
         # CI-4's tests construct /ask request shapes carrying the frozen `insight_id`
         # field — the same reason test_converse_route_off_state is exempt.
         "tests/unit/test_ci4_depth_as_tool.py"),
        "covered seven different concepts; a discovered fact is a 'finding', answer prose "
        "is a 'narrative', a sub-question summary is a 'takeaway'",
    ),
    "soma": (
        r"(?i)\bsoma\b|soma_", CODE_ROOTS, (),
        "named after the SOMA-SQL paper; it is an 'ambiguity probe'",
    ),
    "kinetic": (
        # The Overview's attention strip switches on `NeedsHumanRow.source`, whose wire
        # value is `kinetic_inbox`. It matches the field, never the reader: the chip that
        # renders from it says "proposal".
        r"(?i)kinetic", CODE_ROOTS,
        ("web/components/FleetOverviewPanel.tsx",),
        "a physics metaphor for governed writes; they are 'actions'",
    ),
    "persona": (
        r"(?i)persona", CODE_ROOTS, (),
        "one of five words for a user-created agent; it is a 'custom agent'",
    ),
    "hire": (
        r"(?i)\bhire[drs]?\b|\bhiring\b", CODE_ROOTS, (),
        "you create a custom agent, you do not employ it",
    ),
    "specialist": (
        r"(?i)specialist", CODE_ROOTS, (),
        "one of five words for a domain bundle; it is a 'pack'",
    ),
    "expertise": (
        r"(?i)expertise", CODE_ROOTS, ("packs/",),
        "same concept as 'pack'; the on-disk `expertise.md` filename is frozen format",
    ),
    "digest": (
        # (?<!hex)(?<!\.) so hashlib's hexdigest()/.digest() are not vocabulary.
        r"(?i)(?<!hex)(?<!\.)\bdigest", CODE_ROOTS, (),
        "one of three words for the periodic narrative; it is a 'briefing'",
    ),
    "agentic_ops": (
        r"(?i)agentic\s*ops", CODE_ROOTS, (),
        "one of three names for the agents workspace; it is 'Agents'",
    ),
    "control_room": (
        # The module that SERVES the frozen routes, and the tests that call them, must
        # spell the path. The reason string already grants the routes their freeze; this
        # exempts the two places that cannot avoid naming them, and nothing else.
        r"(?i)control[\s_-]room", CODE_ROOTS,
        ("aughor/routers/control_room.py", "tests/unit/test_agent_ops_endpoints.py",
         "tests/unit/test_agent_ops_data_plane.py"),
        "same screen as 'Agentic Ops' and 'Fleet'; it is 'Agents'. The /control-room/* "
        "routes are frozen contract until the P4 router rename",
    ),
    "fleet": (
        # `FleetOverviewPanel` is the Overview layer's component and `getFleetOverview`
        # calls `/control-room/fleet`, both frozen alongside the route below. The word
        # reaches no reader: the layer is labelled "Overview" and the table "All agents".
        r"(?i)\bfleet", ("web",),
        ("web/components/FleetOverviewPanel.tsx", "web/lib/api.ts"),
        "retired from the UI; the layer is 'Overview'",
    ),
    "charter": (
        # The API's row discriminant IS `kind: "charter"` (see FleetCharterRow), so these
        # files spell it to match the wire. Exempted as TYPE vocabulary, never as prose —
        # the visible strings say "built-in", "custom" and "Agents", and a charter's own
        # page is reached from a layer called Roster.
        r"(?i)charter", ("web",),
        ("web/lib/api.ts", "web/components/FleetOverviewPanel.tsx",
         "web/components/AgenticAgentsPanel.tsx"),
        "not a user-facing word; the roster lists 'agents'",
    ),
    "investigation_in_web": (
        r"(?i)investigat", ("web",),
        ("web/lib/api.ts", "web/lib/uiMessageAdapter", "web/lib/sseFrames",
         "web/lib/aughorUIDataTypes.ts", "web/app/api/chat/",
         # The Overview receives the shell's `onOpenInvestigation` prop (shared with three
         # other panels) and reads `resolve.investigation_id` off a needs-human row — a
         # wire field. Its own prose says "deep analysis"; renaming either would break the
         # contract without changing a word any reader sees.
         "web/components/FleetOverviewPanel.tsx",
         # The parts renderer's single occurrence is an IMPORT PATH: the payload
         # shape types (GuardReceipt, ConverseStep, ContextManifest) live in
         # `investigationStream.ts`, so naming them means naming that module.
         # Those five types are precisely what OUTLIVES the reducer — moving them
         # to a neutrally-named module is a real migration step and would retire
         # this exemption, but it touches five components and belongs with the
         # reducer's retirement rather than ahead of it.
         "web/components/chat/PartsMessage.tsx"),
        "the user-visible word is 'deep analysis'. `investigation` stays as the BACKEND "
        "spelling only (frozen table/route/job-kind); web/lib/api.ts is exempt because it "
        "must mirror the backend contract field-for-field, and the SSE→UIMessage seam is "
        "exempt for the same reason — every file in it names the wire frames verbatim, "
        "including the start frame's investigation_id drop-recovery handle. CI-1d widened "
        "that seam from one file to five (the adapter and its tests, the SSE splitter and "
        "its tests, the data-part vocabulary, and the /api/chat route and its tests); the "
        "prefixes cover each file WITH its test, because a fixture that renames a wire "
        "frame stops testing the wire",
    ),
    # ── External product names ────────────────────────────────────────────────────────
    "palantir": (r"(?i)palantir", CODE_ROOTS, (), "name our features for what they do"),
    "genie": (r"(?i)\bgenie\b", CODE_ROOTS, (), "name our features for what they do"),
    "foundry": (r"(?i)\bfoundry\b", CODE_ROOTS, (), "name our features for what they do"),
    "databricks": (
        r"(?i)databricks", CODE_ROOTS, (),
        "keep it only where we genuinely integrate; elsewhere describe the behaviour",
    ),
    "copilotkit": (r"(?i)copilotkit", CODE_ROOTS, (), "the protocol we speak is AG-UI"),
    "reforce": (r"(?i)reforce", CODE_ROOTS, (), "cite the paper, don't name the feature for it"),
    "blueprint": (
        r"(?i)blueprint", ("web",), (),
        "describe the colour and its role, not the design system it came from",
    ),
    # Both found by the P1/P2 sweeps rather than the original survey — neither is an
    # integration here (no connector, no dependency), so both are pure inspiration-naming.
    "tableau": (
        # The palette modules are EXEMPT, not banned: `tableau10`/`tableau20` are the
        # standard identifiers for those categorical schemes (d3 ships
        # `schemeTableau10`), and the key is persisted in org settings. Banning it would
        # force a breaking rename of a value that is simply the palette's real name.
        # What is banned is describing OUR design system as Tableau's.
        r"(?i)tableau|\btab10\b", ("web",),
        ("web/lib/chartPalettes.ts", "web/lib/orgSettings.ts",
         "web/components/QueryBuilder.tsx",
         # CA-4 moved Chart.tsx's resolver (and its palette-name doc comment)
         # into resolveOption.ts — the exemption follows the code.
         "web/components/charts/resolveOption.ts"),
        "our design system is ours; name the colour scheme, not its origin",
    ),
    "mindsdb": (
        r"(?i)mindsdb", CODE_ROOTS, (),
        "not an integration — describe what the code does",
    ),
}

#: Measured 2026-08-01 after Wave W phases 1-3. A baseline may fall, never rise.
#: `blueprint`, `foundry`, `mindsdb` and `tableau` are at ZERO — they stay listed so
#: the ratchet keeps them there.
BASELINE: dict[str, int] = {
    # 664 → 654. Wave 2d deleted ten FLAG_META descriptions and their guard comments,
    # most of them ada-era prose. Counted over `git ls-files` only — a box that has run
    # the eval suite feeds the scanner untracked MLflow yaml under evals/bakeoff_out/,
    # which is what CI's fresh checkout will never see.
    # 628 → 602: CA-3 reworded the uppercase-acronym prose in investigate.py and the
    # router to "deep-analysis" — the analyst module's unavoidable phase-node call
    # sites (the API names stay frozen) ride inside that paydown.
    # 601 → 592: the `ada.*` flag names left in investigate.py's comments named aliases
    # that no longer exist (the registry test asserts none survive), and one counter
    # metered under the retired prefix while its own neighbours used the live one.
    # 592 → 556: adding the breakdown ROUTE grew this before it shrank it — a new node
    # briefly took the prefix beside it. It is `deep_breakdown`; the two frozen API names
    # next to it are the only reason the term appears in that file at all. The paydown is
    # three sweep scripts that each held a local variable literally named `ada`.
    "ada": 556,
    "agentic_ops": 27,
    "blueprint": 0,
    # 72 → 4: the wire-discriminant files were exempted with their reason (the API row
    # kind IS "charter"), and the two places it reached prose now say "built-in".
    "charter": 4,
    "control_room": 27,
    "copilotkit": 5,
    # 54 → 49: mostly already true on main (the study references moved to docs/, which is
    # outside CODE_ROOTS); Wave 2d removed the last one in a FLAG_META description.
    "databricks": 49,
    "digest": 166,
    "expertise": 43,
    # 58 → 28: FleetOverviewPanel and the api.ts client are exempt — they name the
    # frozen /control-room/fleet route and its component. No reader sees the word.
    "fleet": 28,
    "foundry": 0,
    "genie": 23,
    "hire": 27,
    # 1967 → 1960 → 1959: the mislabel guard's tests named the emission gate in prose;
    # saying "finding" there (the glossary word) paid for the API names they must import.
    "insight": 1959,
    # 659 → 617: CA-1 deleted the reducer stack (investigationStream.ts, useChat.ts,
    # useInvestigationThread.ts, aguiTransport.ts) — 42 spellings went with it.
    "investigation_in_web": 617,
    "kinetic": 402,
    "mindsdb": 0,
    "palantir": 6,
    "persona": 281,  # paid down 2026-08-06: the user-agents graduation eval retired with its flag
    "reforce": 1,
    "soma": 26,
    # 88 → 87 → 86: the explore log line that announced steering said "specialist pack";
    # it now says "pack", which is what the glossary calls the thing. Lowered again after
    # #248 so the gain is locked in rather than left as headroom for the next occurrence.
    "specialist": 86,
    "tableau": 0,
}


@lru_cache(maxsize=1)
def _repo_content() -> frozenset[str] | None:
    """Paths git considers repo content — tracked, plus new files not gitignored.

    ``None`` when git cannot answer.

    The baselines below were measured over ``git ls-files`` (see the note on `ada`), but
    the walk used to ``rglob`` the filesystem, so the scanner and the numbers it is
    checked against disagreed about what "the repo" means. On a developer box that has
    run the suite, that gap is filled by BYPRODUCTS — `web/data/exploration_*.json`,
    MLflow yaml under `evals/bakeoff_out/` — which CI's fresh checkout never sees. The
    result was a ratchet that fails locally on a clean diff and passes in CI, which has
    now cost four sessions; the failure names innocent terms, so the natural reading is
    "my change did this". It is not.

    ``--others --exclude-standard`` rather than tracked-only deliberately: a NEW source
    file is repo content the moment it is written, and dropping it would blind the
    ratchet to exactly the file most likely to introduce retired vocabulary. Byproducts
    are gitignored, so the ignore rules already draw the line correctly.

    ``None`` (no git, or a source tarball) falls back to the old walk rather than
    silently scanning nothing — an empty scan passes every baseline, which is the one
    way this must not fail.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "-z", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True, text=True, timeout=60, check=True).stdout
    except Exception:
        return None
    return frozenset(p for p in out.split("\0") if p)


def _scannable() -> list[tuple[str, Path]]:
    content = _repo_content()
    out: list[tuple[str, Path]] = []
    for root in CODE_ROOTS:
        base = REPO / root
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in _EXTS:
                continue
            if _SKIP_PARTS & set(p.parts):
                continue
            rel = p.relative_to(REPO).as_posix()
            if rel in _SKIP_FILES:
                continue
            if content is not None and rel not in content:
                continue      # a byproduct of running the suite, not repo content
            out.append((rel, p))
    return out


def count(term: str, files: list[tuple[str, Path]] | None = None) -> int:
    """Occurrences of a retired term inside its enforced scope."""
    pattern, roots, exempt, _ = BANNED[term]
    rx = re.compile(pattern)
    total = 0
    for rel, path in (files if files is not None else _scannable()):
        if not any(rel.startswith(r + "/") for r in roots):
            continue
        if any(rel.startswith(e) for e in exempt):
            continue
        total += len(rx.findall(path.read_text(errors="ignore")))
    return total


@pytest.fixture(scope="module")
def files() -> list[tuple[str, Path]]:
    return _scannable()


def test_scan_actually_reaches_the_code(files):
    """Vacuous-pass guard: an empty or tiny file list would make every count 0 and every
    baseline 'met'. The repo is >1000 scannable files; a collapse means the walk broke."""
    assert len(files) > 800, f"only {len(files)} files scanned — the walk is broken"


def test_no_retired_term_grew(files):
    """The ratchet. Lower a baseline when you lower a count; never the reverse."""
    grew = {}
    for term, limit in BASELINE.items():
        now = count(term, files)
        if now > limit:
            grew[term] = (limit, now, BANNED[term][3])
    assert not grew, "\n".join(
        f"'{term}' rose {was} → {now}. It is retired because {why}. "
        f"See docs/GLOSSARY.md for the word to use instead."
        for term, (was, now, why) in sorted(grew.items())
    )


def test_baselines_are_not_stale(files):
    """A baseline far above the real count silently buys back room to regress. When a term
    drops well below its baseline, lower the baseline in the same PR."""
    slack = {}
    for term, limit in BASELINE.items():
        now = count(term, files)
        if limit - now > 25:
            slack[term] = (limit, now)
    assert not slack, "\n".join(
        f"'{term}' baseline {was} but only {now} remain — lower it to {now} in this PR"
        for term, (was, now) in sorted(slack.items())
    )


def test_every_banned_term_has_a_baseline():
    assert set(BANNED) == set(BASELINE), (
        f"missing baselines: {sorted(set(BANNED) - set(BASELINE))}; "
        f"orphaned baselines: {sorted(set(BASELINE) - set(BANNED))}"
    )


def test_every_banned_term_states_why():
    """The failure message is the whole point — a ratchet that fires without explaining
    itself gets silenced rather than fixed."""
    for term, (_, _, _, why) in BANNED.items():
        assert len(why) > 20, f"{term} needs a real reason, got {why!r}"


def test_the_ratchet_can_actually_fire(tmp_path):
    """A fabricated term must be countable, or the regex layer is silently dead."""
    probe = tmp_path / "probe.py"
    probe.write_text("insight insight ADA kinetic\n")
    rx = re.compile(BANNED["insight"][0])
    assert len(rx.findall(probe.read_text())) == 2


def test_canonical_words_are_not_banned():
    """Guard against the ratchet eating the vocabulary it exists to protect: the words the
    glossary tells authors to USE must never appear in BANNED."""
    for word in ("deep analysis", "quick answer", "finding", "narrative", "survey",
                 "briefing", "segment", "action", "notification", "pack", "custom agent"):
        for term, (pattern, _, _, _) in BANNED.items():
            assert not re.search(pattern, word), (
                f"BANNED[{term!r}] matches the canonical word {word!r} — the ratchet would "
                f"fight the glossary"
            )


def test_glossary_exists_and_covers_the_banned_terms():
    """Every retired term must be findable in the glossary, or an author who hits the
    ratchet has nowhere to look up the replacement."""
    text = (REPO / "docs" / "GLOSSARY.md").read_text().lower()
    missing = [t for t in ("insight", "soma", "kinetic", "persona", "specialist", "digest",
                           "fleet", "palantir", "genie", "databricks")
               if t not in text]
    assert not missing, f"docs/GLOSSARY.md does not mention: {missing}"


# ── The flag alias layer (Wave W · P0) ────────────────────────────────────────────────
# The layer ships INERT: both maps empty, so flag resolution is byte-identical to before it
# existed. These pin the mechanism now so the first real rename (P3) is a one-line change to
# a tested path rather than an untested one.


def test_every_alias_resolves_to_a_registered_flag():
    """P0 shipped this layer inert; P3 filled it with the `ada.*` family. Every retired
    name must land on a name that actually exists, or the alias silently resolves to
    nothing and the flag reads as off."""
    from aughor.kernel.flags import FLAG_ENV, RENAMED, RETIRED_ENV

    for old, new in RENAMED.items():
        assert new in FLAG_ENV, f"{old} -> {new}, which is not registered"
    for var, target in RETIRED_ENV.items():
        assert target in FLAG_ENV, f"retired env {var} -> {target}, which is not registered"


def test_canonical_is_identity_for_current_names():
    from aughor.kernel.flags import FLAG_ENV, _canonical

    for name in FLAG_ENV:
        assert _canonical(name) == name


def test_no_ada_flag_survives_in_the_registry():
    """The rename is complete: no `ada.*` flag is registered, and — since an alias
    only means something while its target lives (the last three `ada.*` aliases left
    2026-08-06 with Wave 5's hardwires) — every surviving alias must point at a
    REGISTERED flag, or `_canonical` resolves the old name to a dead one."""
    from aughor.kernel.flags import FLAG_ENV, RENAMED

    assert not [n for n in FLAG_ENV if n.startswith("ada.")]
    dangling = {old: new for old, new in RENAMED.items() if new not in FLAG_ENV}
    assert not dangling, f"aliases pointing at unregistered flags: {dangling}"


def test_a_renamed_flag_resolves_through_its_old_name(monkeypatch):
    from aughor.kernel import flags

    monkeypatch.setitem(flags.RENAMED, "ada.legacy_probe", "deep_analysis.legacy_probe")
    monkeypatch.setitem(flags.FLAG_ENV, "deep_analysis.legacy_probe", "AUGHOR_DA_LEGACY_PROBE")

    assert flags._canonical("ada.legacy_probe") == "deep_analysis.legacy_probe"
    monkeypatch.setenv("AUGHOR_DA_LEGACY_PROBE", "1")
    assert flags.flag_enabled("ada.legacy_probe") is True
    assert flags.flag_enabled("deep_analysis.legacy_probe") is True


def test_a_retired_env_var_still_works_until_the_operator_migrates(monkeypatch):
    """An operator's existing .env must not silently stop working on the day we rename."""
    from aughor.kernel import flags

    monkeypatch.setitem(flags.FLAG_ENV, "deep_analysis.legacy_probe", "AUGHOR_DA_LEGACY_PROBE")
    monkeypatch.setitem(flags.RETIRED_ENV, "AUGHOR_ADA_LEGACY_PROBE", "deep_analysis.legacy_probe")

    monkeypatch.delenv("AUGHOR_DA_LEGACY_PROBE", raising=False)
    monkeypatch.setenv("AUGHOR_ADA_LEGACY_PROBE", "1")
    assert flags.flag_enabled("deep_analysis.legacy_probe") is True
    # …and flag_state must agree, or the UI shows "off" beside a flag that is on.
    assert flags.flag_state("deep_analysis.legacy_probe") == "on"


def test_the_current_env_var_wins_over_a_retired_one(monkeypatch):
    from aughor.kernel import flags

    monkeypatch.setitem(flags.FLAG_ENV, "deep_analysis.legacy_probe", "AUGHOR_DA_LEGACY_PROBE")
    monkeypatch.setitem(flags.RETIRED_ENV, "AUGHOR_ADA_LEGACY_PROBE", "deep_analysis.legacy_probe")

    monkeypatch.setenv("AUGHOR_ADA_LEGACY_PROBE", "1")
    monkeypatch.setenv("AUGHOR_DA_LEGACY_PROBE", "0")
    assert flags.flag_enabled("deep_analysis.legacy_probe") is False


def test_flag_overrides_accepts_a_retired_name(monkeypatch):
    """A script pinned to the old name must keep running, not raise UnknownFlagError."""
    from aughor.kernel import flags

    monkeypatch.setitem(flags.RENAMED, "ada.legacy_probe", "deep_analysis.legacy_probe")
    monkeypatch.setitem(flags.FLAG_ENV, "deep_analysis.legacy_probe", "AUGHOR_DA_LEGACY_PROBE")

    with flags.flag_overrides({"ada.legacy_probe": True}):
        assert flags.flag_enabled("deep_analysis.legacy_probe") is True


def test_an_unregistered_flag_still_raises(monkeypatch):
    """The alias layer must not weaken the typo guard it routes through."""
    from aughor.kernel import flags

    with pytest.raises(flags.UnknownFlagError):
        with flags.flag_overrides({"totally.made.up": True}):
            pass


def test_a_retired_name_never_reregisters():
    """A rename that quietly reappears in FLAG_ENV would resurrect two live names for one
    flag — the exact drift this layer exists to prevent."""
    from aughor.kernel.flags import FLAG_ENV, RENAMED

    clashes = sorted(set(RENAMED) & set(FLAG_ENV))
    assert not clashes, f"retired flag names re-registered in FLAG_ENV: {clashes}"
