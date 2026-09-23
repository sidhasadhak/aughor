"""Arc CP · CP-4 — the answer envelope: the core emits structure, a door renders it.

Measured on 2026-09-23 (ROADMAP §3.22, CP-0): a real Slack answer carried the same five rows
twice — once as a table the model wrote into its prose, once as the grid the transport
attached — because neither half could see the other. The same answer narrated "No guard
receipts fired on this query", against the standing decision that Slack messages carry no
receipts. Both are one fault: prose has no fields, so a door cannot select from it, and
shortening it needs a second model call — which spends back what centralising was for.

So the ask stream now ends with ONE `envelope` frame, folded deterministically from the
frames the run already emitted, and a door reads that:

* ``headline`` — the answer's first sentence;
* ``body`` — the rest of the prose, which NEVER carries a table: every GFM table the model
  wrote is lifted out (`lift_tables`) and, when the run streamed no grid of its own,
  becomes the grid — so "the grid is one field" holds by construction and a duplicate is
  impossible rather than suppressed;
* ``grid`` / ``chart`` — the rows and the DECISION about how to draw them (encodings — PNG
  width, a CSV past N rows, a fenced block — belong to the door);
* ``caveats`` — what qualifies the number, worth a reader's eye on every surface;
* ``follow_ups`` — the questions the run suggested next;
* ``provenance`` — SQL, tables, guard receipts, ids, confidence: the record. A door that
  drops it (Slack, by the user's 2026-09-22 rule) drops a FIELD, and one that shows it
  (the PDF) shows the same field.

The fold is the single implementation. It never invents: a field the frames did not carry
stays empty, and the counter `lifted_tables` says how often the model tabulated in prose,
which is the number that tells whether the prompt's "do not write tables" is being heard.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

# ── The envelope ──────────────────────────────────────────────────────────────


class Grid(BaseModel):
    """A result set for a READER: positional rows in column order."""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    caption: str = ""

    @property
    def empty(self) -> bool:
        return not self.columns or not self.rows


class ChartDecision(BaseModel):
    """Which picture the grid wants — a decision, central. ``auto`` defers to the shape
    resolver every renderer already shares; it is still the core's to say."""
    chart_type: str = "auto"
    chart_config: dict[str, Any] = Field(default_factory=dict)


class Provenance(BaseModel):
    """The record behind the answer. A door SELECTS whether to show it; the field exists
    either way, which is the whole difference from narrating it into the prose."""
    investigation_id: str = ""
    receipt_id: str = ""
    connection_id: str = ""
    session_id: str = ""
    mode: str = ""
    confidence: str = ""
    sql: list[str] = Field(default_factory=list)
    tables_used: list[str] = Field(default_factory=list)
    guard_receipts: list[dict[str, Any]] = Field(default_factory=list)
    folded_at: str = ""


class AnswerEnvelope(BaseModel):
    version: int = 1
    question: str = ""
    headline: str = ""
    body: str = ""
    grid: Optional[Grid] = None
    chart: Optional[ChartDecision] = None
    caveats: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)
    error: str = ""
    #: How many tables the model wrote into its prose this turn. Zero is the goal; the
    #: count is what says whether the prompt is being heard, so it rides the envelope.
    lifted_tables: int = 0

    @property
    def has_answer(self) -> bool:
        return bool(self.headline or self.body or self.error)


# ── Lifting tables out of prose ───────────────────────────────────────────────

#: A GFM delimiter row: pipes, dashes, colons and spaces. The dash is what makes it a
#: delimiter rather than an empty row; the pipe is what makes it a table rather than a
#: horizontal rule under a sentence that happened to contain "revenue | margin".
_DELIM_ROW = re.compile(r"^\|?[\s:|-]+\|?$")
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def _is_delimiter(line: str) -> bool:
    s = line.strip()
    return "-" in s and "|" in s and bool(_DELIM_ROW.match(s))


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in _UNESCAPED_PIPE.split(s)]


def lift_tables(text: str) -> tuple[str, list[Grid]]:
    """Every GFM table in ``text``, parsed and REMOVED, with the prose that remains.

    A table is a header line containing a pipe, a delimiter row directly under it, and the
    contiguous pipe-bearing lines after that. Only the delimiter's shape decides — never
    the content — so prose with a pipe in it is left exactly as written.
    """
    lines = (text or "").split("\n")
    kept: list[str] = []
    grids: list[Grid] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "|" in line and i + 1 < len(lines) and _is_delimiter(lines[i + 1]):
            columns = _cells(line)
            rows: list[list[Any]] = []
            j = i + 2
            while j < len(lines) and lines[j].strip() and "|" in lines[j]:
                cells = _cells(lines[j])
                rows.append((cells + [""] * len(columns))[: len(columns)])
                j += 1
            grids.append(Grid(columns=columns, rows=rows))
            i = j
            continue
        kept.append(line)
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip(), grids


def first_line(text: str) -> str:
    """The first non-empty line, as a plain sentence: no heading marks, no emphasis wrap."""
    for raw in (text or "").split("\n"):
        s = raw.strip().lstrip("#").strip().rstrip(":").strip()
        s = re.sub(r"^\*\*(.+?)\*\*$", r"\1", s)
        s = s.strip("*_ ")
        if s:
            return s
    return ""


def _after_first_line(text: str) -> str:
    """Everything after the first non-empty line, stripped."""
    lines = (text or "").split("\n")
    for i, raw in enumerate(lines):
        if raw.strip():
            return "\n".join(lines[i + 1:]).strip()
    return ""


# ── The fold ──────────────────────────────────────────────────────────────────


def _positional(columns: list[str], raw: Any) -> list[list[Any]]:
    """Rows as positional lists in column order. `trusted_query` and some tools publish
    dict rows; the reader-facing grid is positional, so the conversion happens once, here."""
    rows: list[list[Any]] = []
    for r in raw or []:
        if isinstance(r, dict):
            rows.append([r.get(c) for c in columns])
        elif isinstance(r, (list, tuple)):
            rows.append(list(r))
    return rows


def _strs(items: Any) -> list[str]:
    return [str(x).strip() for x in (items or []) if str(x or "").strip()]


class EnvelopeFolder:
    """Fold the ask stream's ``(type, payload)`` frames into one :class:`AnswerEnvelope`.

    Replace semantics for every streamed text (the last delta IS the whole text, the rule
    `investigations._record` keeps); last-wins for the grid, because a conversational turn
    may run several queries and the one the closing prose is about is the one it finished
    on. A settled ``headline`` frame wins over its deltas.
    """

    def __init__(self, *, question: str = "", connection_id: str = "",
                 session_id: str = "") -> None:
        self.question = question
        self.connection_id = connection_id
        self.session_id = session_id
        self._headline = ""
        self._headline_final = False
        self._narrative = ""
        self._summary = ""
        self._columns: list[str] = []
        self._rows: list = []
        self._chart_type = ""
        self._chart_config: dict[str, Any] = {}
        self._sql: list[str] = []
        self._tables: list[str] = []
        self._receipts: list[dict[str, Any]] = []
        self._caveats: list[str] = []
        self._followups: list[str] = []
        self._inv_id = ""
        self._receipt_id = ""
        self._mode = ""
        self._confidence = ""
        self._error = ""

    # ── frames ──
    def feed(self, kind: str, payload: Any) -> None:
        p = payload if isinstance(payload, dict) else {}
        if kind == "start":
            self._inv_id = str(p.get("investigation_id") or self._inv_id)
            self.connection_id = str(p.get("connection_id") or self.connection_id)
            self.question = str(p.get("question") or self.question)
        elif kind == "done":
            self._inv_id = self._inv_id or str(p.get("inv_id") or "")
            self._mode = self._mode or str(p.get("body") or "")
        elif kind == "receipt_id":
            self._receipt_id = str(p.get("receipt_id") or self._receipt_id)
        elif kind == "sql":
            sql = str(p.get("sql") or "").strip()
            if sql and sql not in self._sql:
                self._sql.append(sql)
        elif kind == "columns":
            self._columns = [str(c) for c in (p.get("columns") or [])]
        elif kind == "rows":
            self._rows = list(p.get("rows") or [])
        elif kind == "chart_type":
            self._chart_type = str(p.get("chart_type") or "")
        elif kind == "chart_config":
            cfg = p.get("chart_config")
            self._chart_config = dict(cfg) if isinstance(cfg, dict) else {}
        elif kind == "headline":
            text = str(p.get("headline") or "")
            if text:
                self._headline, self._headline_final = text, True
        elif kind == "headline_delta":
            if not self._headline_final:
                self._headline = str(p.get("headline") or self._headline)
        elif kind in ("narrative", "narrative_delta"):
            self._narrative = str(p.get("narrative") or self._narrative)
        elif kind == "answer_report":
            self._report(p.get("answer_report"))
        elif kind == "report":
            rep = p.get("report")
            if isinstance(rep, dict) and rep.get("headline") and not self._headline_final:
                self._headline, self._headline_final = str(rep["headline"]), True
        elif kind == "explore_report":
            rep = p.get("explore_report")
            if isinstance(rep, dict):
                if rep.get("headline") and not self._headline_final:
                    self._headline, self._headline_final = str(rep["headline"]), True
                self._summary = str(rep.get("conclusion") or rep.get("narrative") or self._summary)
        elif kind == "guard_receipt":
            receipt = {k: v for k, v in p.items() if k != "type"}
            if receipt:
                self._receipts.append(receipt)
                self._caveats.extend(_strs(receipt.get("caveats")))
                if receipt.get("caveat"):
                    self._caveats.append(str(receipt["caveat"]))
                self._caveats.extend(_strs(receipt.get("e1_messages")))
        elif kind == "tables_used":
            self._tables = _strs(p.get("tables") or p.get("tables_used"))
        elif kind == "followups":
            self._followups = _strs(p.get("questions") or p.get("followups"))
        elif kind == "mode":
            self._mode = self._mode or str(p.get("query_mode") or "")
        elif kind == "error":
            self._error = str(p.get("hint") or p.get("message") or p.get("error") or "the run failed")

    def _report(self, rep: Any) -> None:
        """A deep run's ``answer_report``: the finished sentence, its summary, and every
        caveat the phases and findings carried — the report's own words, never a summary
        this fold invented."""
        if not isinstance(rep, dict):
            return
        if rep.get("headline"):
            self._headline, self._headline_final = str(rep["headline"]), True
        if rep.get("executive_summary"):
            self._summary = str(rep["executive_summary"])
        if rep.get("confidence"):
            self._confidence = str(rep["confidence"])
        self._caveats.extend(_strs(rep.get("data_gaps")))
        for phase in rep.get("phases") or []:
            if not isinstance(phase, dict):
                continue
            self._caveats.extend(_strs(phase.get("caveats")))
            for finding in phase.get("findings") or []:
                if isinstance(finding, dict) and finding.get("trust_caveat"):
                    self._caveats.append(str(finding["trust_caveat"]))

    # ── the envelope ──
    def finish(self) -> AnswerEnvelope:
        head_text, lifted_h = lift_tables(self._headline)
        body, lifted_b = lift_tables(self._narrative or self._summary)
        if "\n" in head_text:
            # The whole answer arrived as the headline (the converse path emits its prose
            # that way). The first line is the sentence; the REST is the body — never the
            # whole text again, or every door would open by saying the sentence twice
            # (measured on the first live receipt, 2026-09-23).
            headline = first_line(head_text)
            rest = _after_first_line(head_text)
            body = rest if not body else f"{rest}\n\n{body}".strip()
        else:
            headline = head_text
        lifted = lifted_h + lifted_b

        grid: Optional[Grid] = None
        if self._columns and self._rows:
            rows = _positional(self._columns, self._rows)
            if rows:
                grid = Grid(columns=self._columns, rows=rows)
        if grid is None:
            grid = next((g for g in lifted if not g.empty), None)

        chart = None
        if grid is not None:
            chart = ChartDecision(chart_type=self._chart_type or "auto",
                                  chart_config=self._chart_config)

        caveats: list[str] = []
        for c in self._caveats:
            if c and c not in caveats:
                caveats.append(c)

        return AnswerEnvelope(
            question=self.question,
            headline=headline,
            body=body if body != headline else "",
            grid=grid,
            chart=chart,
            caveats=caveats,
            follow_ups=list(self._followups),
            provenance=Provenance(
                investigation_id=self._inv_id, receipt_id=self._receipt_id,
                connection_id=self.connection_id, session_id=self.session_id,
                mode=self._mode,
                confidence=self._confidence, sql=list(self._sql),
                tables_used=list(self._tables), guard_receipts=list(self._receipts),
                folded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
            error=self._error,
            lifted_tables=len(lifted),
        )


def fold_frames(frames: Any, *, question: str = "", connection_id: str = "",
                session_id: str = "") -> AnswerEnvelope:
    """Fold an iterable of ``{"type": …, …}`` frame dicts — the test-facing entry."""
    folder = EnvelopeFolder(question=question, connection_id=connection_id,
                            session_id=session_id)
    for frame in frames:
        if isinstance(frame, dict) and frame.get("type"):
            folder.feed(str(frame["type"]), frame)
    return folder.finish()
