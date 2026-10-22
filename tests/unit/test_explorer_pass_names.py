"""The explorer's passes are named for what they do — never "Phase N" (PENDING item 53, 2026-10-23).

On 2026-10-22 the user watched an exploration and read "Phase 8 manifest-driven ON — 17 baseline cells",
"Starting (domain_intel_only=True)", "Phase 9: 24 candidate pairs" and, in the chat, "Analyzing adhoc_3…".
None of those words says what the platform is doing. The names now are the jobs the code already had —
structure · questions · synthesis — and the five structure passes (docs/GLOSSARY.md › The explorer's passes).

Population, named so the guard cannot pass for the wrong reason: every STRING LITERAL (log lines, journal
labels, prompt text, docstrings, API descriptions) in ``aughor/explorer/*.py`` and
``aughor/routers/exploration.py``, plus the one line of ``web/lib/chatTurn.ts`` that writes the thinking row.
A comment may still say "durable execution" or "Phase 2 of the 2027 study" — those name plan documents, and
a comment is not a reader surface, so they are deliberately outside the population.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PHASE_NUMBER = re.compile(r"\bPhase[ -]?\d")


def _string_literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def _explorer_files() -> list[Path]:
    files = sorted((ROOT / "aughor" / "explorer").glob("*.py"))
    files.append(ROOT / "aughor" / "routers" / "exploration.py")
    assert len(files) > 10, "the population moved — re-point this guard"
    return files


def test_no_phase_number_reaches_a_reader_from_the_explorer():
    hits = [(p.name, ln, v.strip()[:90]) for p in _explorer_files()
            for ln, v in _string_literals(p) if PHASE_NUMBER.search(v)]
    assert not hits, f"a phase number in a string a reader may meet: {hits}"


def test_the_explorers_retired_words_left_its_strings():
    retired = ("manifest-driven", "baseline cell", "Starting (domain_intel_only", "domain intelligence")
    hits = [(ln, word) for ln, v in _string_literals(ROOT / "aughor" / "explorer" / "agent.py")
            for word in retired if word.lower() in v.lower()]
    assert not hits, hits


def test_the_thinking_row_names_the_step_not_its_id():
    src = (ROOT / "web" / "lib" / "chatTurn.ts").read_text(encoding="utf-8")
    assert "${phase?.phase_id}" not in src and "${phase.phase_id}" not in src, \
        "the thinking row interpolates a step id again"
    assert "phase_name" in src.split("phase_complete:", 1)[1][:600], \
        "the thinking row no longer reads the step's name"


def test_the_catalogs_label_for_the_questions_pass_is_a_readers_phrase():
    src = (ROOT / "web" / "components" / "BriefingPanel.tsx").read_text(encoding="utf-8")
    assert "synthesising domain intelligence" not in src
    assert re.search(r"domain_intel:\s+\"asking its questions\"", src), "the label moved or changed"
