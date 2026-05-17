"""
Load global_rules.md and format it for injection into LLM prompts.

The file is re-read on every call — edit it without restarting the server.

Two injection modes:
  full  — all sections, used by investigation (decompose, plan, synthesize)
  chat  — only SQL-correctness and display sections, used by direct chat queries
"""
from __future__ import annotations

import re
from pathlib import Path

_RULES_FILE = Path(__file__).parent.parent / "data" / "global_rules.md"

# Section headers like "## 7. SQL Correctness"
_SECTION_HEADER = re.compile(r"^##\s+(\d+)\.\s+(.+)$")

# Sections to include in the lightweight "chat" mode
_CHAT_SECTIONS = {0, 7, 8}  # Operating Posture, SQL Correctness, Display Formatting


def _parse(text: str) -> dict[int, tuple[str, list[str]]]:
    """
    Returns {section_num: (section_title, [rule_strings])}.
    Skips comment lines (#), horizontal rules (---), and blank lines.
    """
    sections: dict[int, tuple[str, list[str]]] = {}
    current_num: int | None = None
    current_rules: list[str] = []
    current_title = ""

    for line in text.splitlines():
        stripped = line.strip()

        # Section header
        m = _SECTION_HEADER.match(stripped)
        if m:
            if current_num is not None:
                sections[current_num] = (current_title, current_rules)
            current_num = int(m.group(1))
            current_title = m.group(2)
            current_rules = []
            continue

        # Skip comments, dividers, empty lines, and preamble prose
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue

        # Capture bullet rules
        if stripped.startswith("- "):
            current_rules.append(stripped[2:])

    # Flush last section
    if current_num is not None:
        sections[current_num] = (current_title, current_rules)

    return sections


def _format_block(sections: dict[int, tuple[str, list[str]]], include: set[int] | None = None) -> str:
    if not sections:
        return ""
    lines = ["GLOBAL RULES (authoritative — always follow):"]
    for num in sorted(sections):
        if include is not None and num not in include:
            continue
        title, rules = sections[num]
        if not rules:
            continue
        lines.append(f"\n[{title}]")
        for r in rules:
            lines.append(f"- {r}")
    lines.append("")
    return "\n".join(lines)


def _load() -> dict[int, tuple[str, list[str]]]:
    try:
        return _parse(_RULES_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def get_rules_block() -> str:
    """Full rules block — all sections. Use for investigation nodes."""
    return _format_block(_load())


def get_chat_rules_block() -> str:
    """Lightweight rules block — SQL and display sections only. Use for direct chat queries."""
    return _format_block(_load(), include=_CHAT_SECTIONS)
