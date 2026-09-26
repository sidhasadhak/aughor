"""SP-15, §6 item 33(b) — the corpus's second shelf: the glossary and the §3 arc summaries,
served through `platform_help`'s alias resolution, read from the files the repo maintains.

Pinned on a fixture docs tree (deterministic), then on the real one (present in a checkout):
a term answers with its meaning and its retired spellings; a retired spelling resolves to
the word that replaced it; an arc answers under `arc <code>` and its code; a hand-written
alias outranks a parsed one; no docs means empty shelves, never an error.
"""
from __future__ import annotations

from aughor.agent import platform_tools as pt

_GLOSSARY = """# Glossary

## Answering

| Use this | For | Don't use |
|---|---|---|
| **Survey** | A wide question answered by many cuts at once | "landscape", `wide wave`; `explore` in anything a user reads |
| **Exploration** | Background autonomous learning about the data | cartography |
| **Answer** | Any reply to any question | — |
"""

_ROADMAP = """# Roadmap

### 3.9 · Arc XY — the example arc (adopted 2026-01-01; decision §6 item 1)

> **Origin.** The user asked for *an example*. This is its first paragraph, which is the
> summary a reader wants.
>
> The second paragraph is history and is not served.

### 3.10 · Arc ZZ — a second arc (drafted 2026-02-02)

Prose without an origin block.
"""


def _root(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "GLOSSARY.md").write_text(_GLOSSARY, encoding="utf-8")
    (tmp_path / "ROADMAP.md").write_text(_ROADMAP, encoding="utf-8")
    return tmp_path


def test_the_glossary_shelf_serves_terms_and_resolves_retired_spellings(tmp_path):
    topics, aliases = pt._glossary_shelf(_root(tmp_path))
    assert topics["survey"].startswith("Survey (answering) — A wide question answered by many cuts at once.")
    assert 'Not: "landscape", `wide wave`; `explore` in anything a user reads.' in topics["survey"]
    assert topics["answer"] == "Answer (answering) — Any reply to any question."
    assert aliases["cartography"] == "exploration"
    assert aliases["landscape"] == "survey" and aliases["wide wave"] == "survey"
    assert "explore in anything a user reads" not in aliases      # a clause is not a spelling


def test_the_arc_shelf_serves_the_header_and_the_first_origin_paragraph(tmp_path):
    topics, aliases = pt._arc_shelf(_root(tmp_path))
    assert topics["arc xy"] == ("Arc XY — the example arc. The user asked for an example. This is its "
                                "first paragraph, which is the summary a reader wants.")
    assert topics["arc zz"] == "Arc ZZ — a second arc."
    assert aliases == {"xy": "arc xy", "zz": "arc zz"}


def test_no_docs_means_empty_shelves_never_an_error():
    assert pt._glossary_shelf(None) == ({}, {})
    assert pt._arc_shelf(None) == ({}, {})


def test_the_real_shelves_are_loaded_in_a_checkout():
    """The checkout ships docs/; the shelves are then real, and the wave's own arc answers."""
    assert pt._DOCS_ROOT is not None
    out = pt.platform_help("c1", {"topic": "tj"})
    assert out["topic"] == "arc tj" and out["help"].startswith("Arc TJ — trajectories")
    finding = pt.platform_help("c1", {"topic": "finding"})
    assert finding["topic"] == "finding" and "evidence-backed fact" in finding["help"]
    assert pt.platform_help("c1", {"topic": "cartography"})["topic"] == "exploration"


def test_a_hand_written_alias_outranks_a_parsed_one():
    """`why` → analysis was written by hand; the glossary must not re-point it."""
    assert pt._HELP_ALIASES["why"] == "analysis"
    assert pt.platform_help("c1", {"topic": "why"})["topic"] == "analysis"
