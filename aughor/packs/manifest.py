"""The one way the platform writes into a pack's manifest (the 2027 study's close-out, C9).

`promote.set_status` and `kit.upload` used to `yaml.safe_load` the manifest, change a key and `yaml.safe_dump` the
mapping back — which drops every comment and every quoting choice its author made. A manifest's comments are where
a pack's provenance is argued (banking's `pack.yaml` carries IP-4's dating and gate 6's reason; the B2B SaaS draft's
carries why its anatomy is 0), so a promotion that erased them erased the record a reviewer reads. PyYAML has no
round-trip mode and the repo does not carry ruamel; the keys the platform ever writes are top-level scalars —
`status`, `source`, `source_url`, `uploaded_by`, `uploaded_at` — so a line-level rewrite is the whole need:

- a key already present has its line replaced in place, a block or flow value it had removed with it, and a trailing
  comment on the line kept;
- a key absent is appended at the end;
- every other byte stays as the author wrote it, and `yaml.safe_load` of the result is the loaded original with
  exactly those keys changed (the tests hold it).
"""
from __future__ import annotations

import re
from typing import Any

import yaml

_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*)\s*:(.*)$")
_TRAILING_COMMENT = re.compile(r"\s+#.*$")


def scalar(value: Any) -> str:
    """One YAML scalar as PyYAML would write it — quoted when a bare spelling would read as another type (an ISO
    timestamp, a number, `yes`), unquoted otherwise."""
    text = yaml.safe_dump(value, default_flow_style=True, width=10**9, allow_unicode=True).strip()
    if text.endswith("\n..."):
        text = text[: -len("\n...")].rstrip()
    return text


def _value_end(lines: list[str], start: int) -> int:
    """The index after the value that begins on ``lines[start]``: continuation lines are indented, and a blank run
    belongs to the value only when an indented line follows it."""
    j = start + 1
    while j < len(lines):
        line = lines[j]
        if line.strip() == "":
            k = j
            while k < len(lines) and lines[k].strip() == "":
                k += 1
            if k < len(lines) and lines[k][:1] in (" ", "\t"):
                j = k
                continue
            break
        if line[:1] in (" ", "\t"):
            j += 1
            continue
        break
    return j


def _trailing_comment(rest: str) -> str:
    """The ` # comment` at the end of a scalar line, or "" — a `#` inside quotes is not a comment."""
    m = _TRAILING_COMMENT.search(rest)
    if not m:
        return ""
    before = rest[: m.start()]
    if before.count("'") % 2 or before.count('"') % 2:
        return ""
    return m.group(0)


def rewrite_scalars(text: str, changes: dict[str, Any]) -> str:
    """``text`` with each top-level key in ``changes`` set to its value, and nothing else touched."""
    pending = dict(changes)
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = _KEY.match(lines[i])
        if m and m.group(1) in pending:
            key = m.group(1)
            out.append(f"{key}: {scalar(pending.pop(key))}{_trailing_comment(m.group(2))}")
            i = _value_end(lines, i)
            continue
        out.append(lines[i])
        i += 1
    if pending:
        while out and out[-1].strip() == "":
            out.pop()
        for key, value in pending.items():
            out.append(f"{key}: {scalar(value)}")
        out.append("")
    result = "\n".join(out)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result
