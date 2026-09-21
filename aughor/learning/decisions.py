"""Decision records — every closed-set choice the platform makes, in a trainable shape.

The platform is full of small decisions whose output is a pick from a list that existed
before the call: which route a question takes, which tool a converse step runs, which
declared definition an ambiguous term means. Today each of those is decided (mostly by an
LLM) and the *choice itself* evaporates — the session log keeps what ran, not what the
menu was. This store keeps the menu: one row per decision, holding the context the
decider saw, the options it chose among, which one it picked, and — once known — whether
the pick worked. That is exactly the `{context, options, label}` shape a selection model
trains on, so the exporter beside it (`exporters.export_decisions`) can turn accumulated
traffic into a corpus without a labeling pass.

Recording is OBSERVATION, never control: `record_decision` sits on request paths (the
tool loop, the route classifier), so it must never raise and never slow a turn — a failed
write is a tolerated counter, not a failed answer. Registered hermetically in the SAME
commit as this file (`AUGHOR_DECISIONS_DB` in `tests/conftest.py` and
`scripts/dump_openapi.py`) — a store is not hermetic until its env name is in both lists.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Optional

from aughor.db.backend import connect_store
from aughor.db.sqlite_util import resolve_db_path

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "decisions.db"

#: Caps on what one row may carry. A decision's context is a routing glimpse, not a
#: transcript — an uncapped context field would quietly become a second session log and
#: drag tool results (with their data rows) into a store the exporter ships out.
_MAX_CONTEXT = 2000
_MAX_OPTION = 400
_MAX_OPTIONS = 64


def _db_path() -> Path:
    return resolve_db_path("AUGHOR_DECISIONS_DB", _DEFAULT_PATH)


_LOCK = threading.RLock()

_DDL = """
CREATE TABLE IF NOT EXISTS decision_record (
    id         TEXT PRIMARY KEY,
    ts         TEXT NOT NULL DEFAULT '',
    org_id     TEXT NOT NULL DEFAULT 'default',
    site       TEXT NOT NULL DEFAULT '',    -- ask.route | converse.tool | framing.definition | ...
    conn_id    TEXT NOT NULL DEFAULT '',
    trace_id   TEXT NOT NULL DEFAULT '',
    context    TEXT NOT NULL DEFAULT '',
    options    TEXT NOT NULL DEFAULT '[]',  -- JSON list, the menu as the decider saw it
    label      INTEGER NOT NULL DEFAULT -1, -- index into options; -1 = chose none of them
    chosen     TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL DEFAULT 'llm', -- llm | rule | reflex
    confidence REAL NOT NULL DEFAULT 0.0,   -- the decider's own, 0.0 when it offers none
    outcome    TEXT NOT NULL DEFAULT '',    -- '' unknown | ok | error | accepted | rejected
    inv_id     TEXT NOT NULL DEFAULT ''     -- the investigation a human verdict arrives on
);
CREATE INDEX IF NOT EXISTS idx_decision_site ON decision_record (site, ts DESC);
CREATE INDEX IF NOT EXISTS idx_decision_ts   ON decision_record (ts DESC);
"""

#: `inv_id` arrived after the table did, so an existing store grows it additively. Its index
#: is deliberately NOT in `_DDL`: `executescript` runs before the ALTER, so on a store that
#: predates the column `CREATE INDEX ... (inv_id)` would reference a column that does not
#: exist yet and take the whole connection down. Column first, then index — always.
#: The module flag is because `_connect` runs per call and the PRAGMA is cheap, not free.
_MIGRATED = False


def _connect() -> sqlite3.Connection:
    global _MIGRATED
    conn = connect_store(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    if not _MIGRATED:
        from aughor.db.migrations import add_column_if_missing
        add_column_if_missing(conn, "decision_record", "inv_id", "TEXT NOT NULL DEFAULT ''")
        # JD-4: a sha256 of the assembled system prompt the decider was shown. METADATA, not
        # payload — it cannot be reversed into the prompt, so §6 item 4 lets it be written on
        # every row without a capture window. It is what lets a later replay PROVE it rebuilt
        # the same input before spending a token, the way `evals/frozen.py` fingerprints state.
        add_column_if_missing(conn, "decision_record", "prompt_fingerprint", "TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_inv ON decision_record (inv_id)")
        conn.commit()
        _MIGRATED = True
    return conn


def _now() -> str:
    from aughor.util.time import now_iso_z
    return now_iso_z()


def record_decision(site: str, context: str, options: list, *,
                    chosen: str = "", label: Optional[int] = None,
                    source: str = "llm", confidence: float = 0.0,
                    outcome: str = "", conn_id: str = "", trace_id: str = "",
                    inv_id: str = "", org_id: Optional[str] = None,
                    prompt_fingerprint: str = "") -> str:
    """Record one closed-set choice; returns its id, or '' when the write failed.

    `label` is derived from `chosen` when not given (exact match against `options`);
    a `chosen` that matches nothing records as -1 — "picked none of the listed" is a
    real outcome, and the exporter decides what to do with it, not this function.
    Never raises: this sits on the answer path, and a decision that could not be
    recorded must cost nothing but a counter.

    `conn_id`, `trace_id` and `inv_id` are the row's PROVENANCE, and a row missing them
    is not merely thinner — it is unusable. Measured 2026-09-19 on the live store: 40
    rows, every one `conn_id = ''`, so not one could be attributed to the connection
    whose schema and ontology the decider was reading. A selection corpus that cannot
    say which world a choice was made in has no context column. `inv_id` is the key a
    human verdict arrives on (`aughor/feedback/verdicts.py`), and therefore the only way
    `mark_outcomes_for_run` can ever close the loop on these rows.
    """
    try:
        opts = [str(o)[:_MAX_OPTION] for o in list(options)[:_MAX_OPTIONS]]
        if label is None:
            capped = str(chosen)[:_MAX_OPTION]
            label = opts.index(capped) if capped in opts else -1
        if not (0 <= int(label) < len(opts)):
            label = -1
        from aughor.org.context import current_org_id
        row = {
            "id": uuid.uuid4().hex, "ts": _now(),
            "org_id": org_id or current_org_id() or "default",
            "site": str(site), "conn_id": str(conn_id), "trace_id": str(trace_id),
            "inv_id": str(inv_id), "prompt_fingerprint": str(prompt_fingerprint)[:64],
            "context": str(context)[:_MAX_CONTEXT],
            "options": json.dumps(opts, ensure_ascii=False),
            "label": int(label), "chosen": str(chosen)[:_MAX_OPTION],
            "source": str(source), "confidence": float(confidence),
            "outcome": str(outcome),
        }
        cols = ", ".join(row)
        binds = ", ".join(f":{c}" for c in row)
        with _LOCK:
            conn = _connect()
            try:
                conn.execute(f"INSERT INTO decision_record ({cols}) VALUES ({binds})", row)
                conn.commit()
            finally:
                conn.close()
        return row["id"]
    except Exception as exc:  # noqa: BLE001 — observation must never fail the observed
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a decision that could not be recorded still happened; the turn goes on",
                 counter="learning.decision_record")
        return ""


def mark_outcome(decision_id: str, outcome: str) -> bool:
    """Close the loop on one decision once its result is known. Best-effort, never raises."""
    try:
        with _LOCK:
            conn = _connect()
            try:
                cur = conn.execute("UPDATE decision_record SET outcome = ? WHERE id = ?",
                                   (str(outcome), decision_id))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "an outcome that could not be marked leaves the decision unlabeled, not lost",
                 counter="learning.decision_outcome")
        return False


def mark_outcomes_for_run(*, inv_id: str = "", trace_id: str = "", outcome: str = "") -> int:
    """Close the loop on every decision a run made, from the one place a person judges it.

    `mark_outcome` has existed since this store was born and has never had a caller —
    which is why, measured 2026-09-19, all 40 live rows carry `outcome = 'ok'`. That value
    is written inline at insert by `tool_loop` and means "the tool did not raise", so it is
    a LIVENESS signal, not a quality one: every executed step is a positive example and the
    column never takes its other value. A label that cannot come out negative teaches
    nothing, and `exporters.list_for_export` will happily ship 40 of them.

    This is the negative half. It is driven by a human verdict on the finding the run
    produced, so `rejected` means a person looked at the answer these picks led to and said
    it was wrong. Returns the number of rows closed; never raises — a verdict that could
    not be propagated is still a verdict.
    """
    key, value = ("inv_id", inv_id) if inv_id else ("trace_id", trace_id)
    if not value or not outcome:
        return 0
    try:
        with _LOCK:
            conn = _connect()
            try:
                cur = conn.execute(
                    f"UPDATE decision_record SET outcome = ? WHERE {key} = ?",
                    (str(outcome), str(value)))
                conn.commit()
                return int(cur.rowcount or 0)
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001 — observation must never fail the observed
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a run whose decisions could not be closed still produced its verdict",
                 counter="learning.decision_outcomes_run")
        return 0


def attach_run(trace_id: str, inv_id: str) -> int:
    """Give a turn's decisions the investigation id, once the turn has one.

    A conversational turn's id does not exist while the turn runs — `save_chat_turn` mints
    it FROM the answer, after the tool loop has already made and recorded every pick. So the
    loop records a trace it chose up front, and this stitches the investigation on at the
    end. Without it a converse decision can never be closed by a verdict: measured
    2026-09-20, four rows from two real LuxExperience turns carried `conn_id` and an empty
    `inv_id`, which is attribution without a return path.

    Only fills rows that have none — a decision already attached to an investigation is not
    reassigned by a later turn that happens to share a trace. Never raises.
    """
    if not trace_id or not inv_id:
        return 0
    try:
        with _LOCK:
            conn = _connect()
            try:
                cur = conn.execute(
                    "UPDATE decision_record SET inv_id = ? WHERE trace_id = ? AND inv_id = ''",
                    (str(inv_id), str(trace_id)))
                conn.commit()
                return int(cur.rowcount or 0)
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001 — observation must never fail the observed
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a turn whose decisions could not be attached still answered",
                 counter="learning.decision_attach")
        return 0


def corpus_yield(site: Optional[str] = None) -> dict:
    """What the accumulated rows are actually worth as a selection corpus, per site.

    Three counts decide whether a row can be learned from at all, and each is a column
    that was empty or constant on the live store when this was written:

    * **attributable** — carries `conn_id`. A choice made against one connection's schema
      and ontology is not the same choice made against another's; without it the context
      column is missing.
    * **with_probability** — carries a non-zero `confidence`. Nothing can be RANKED by
      doubt without it, so the whole uncertainty-scheduling half has no input.
    * **discriminating** — the site's `outcome` column takes more than one distinct
      non-empty value. One value is not a label, however many rows carry it.

    `trainable` keeps `list_for_export`'s own floor (a listed option was chosen, and the
    menu had at least two options in it) so the two reads cannot drift.
    """
    clauses, params = [], []
    if site:
        clauses.append("site = ?"); params.append(site)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                f"SELECT site, conn_id, confidence, outcome, label, options "
                f"FROM decision_record {where}", params).fetchall()
        finally:
            conn.close()
    out: dict = {}
    for r in rows:
        s = out.setdefault(r["site"], {"total": 0, "attributable": 0, "with_probability": 0,
                                       "trainable": 0, "outcomes": {}, "discriminating": False})
        s["total"] += 1
        if (r["conn_id"] or ""):
            s["attributable"] += 1
        if float(r["confidence"] or 0.0) > 0.0:
            s["with_probability"] += 1
        try:
            opts = json.loads(r["options"] or "[]")
        except (TypeError, ValueError):
            opts = []
        if len(opts) >= 2 and 0 <= int(r["label"]) < len(opts):
            s["trainable"] += 1
        if (r["outcome"] or ""):
            s["outcomes"][r["outcome"]] = s["outcomes"].get(r["outcome"], 0) + 1
    for s in out.values():
        s["discriminating"] = len(s["outcomes"]) > 1
    return out


def list_decisions(site: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Recent rows, newest first, options decoded — the observability read."""
    clauses, params = [], []
    if site:
        clauses.append("site = ?"); params.append(site)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM decision_record {where} ORDER BY ts DESC, rowid DESC LIMIT ?",
                [*params, max(1, min(int(limit), 500))]).fetchall()
        finally:
            conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["options"] = json.loads(d.get("options") or "[]")
        out.append(d)
    return out


def list_for_export(site: str, limit: int = 100000) -> list[dict]:
    """Every trainable row for one site, oldest first: a listed option was chosen and
    the menu had a real choice in it (two options minimum — jevlike's own floor)."""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM decision_record WHERE site = ? AND label >= 0 "
                "ORDER BY ts ASC, rowid ASC LIMIT ?", (site, int(limit))).fetchall()
        finally:
            conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["options"] = json.loads(d.get("options") or "[]")
        if len(d["options"]) >= 2 and 0 <= d["label"] < len(d["options"]):
            out.append(d)
    return out


def site_stats() -> dict:
    """Per-site accumulation — total rows, trainable rows (a listed option was chosen),
    and rows whose outcome landed. The volume half of "is this decision learnable"."""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT site, COUNT(*) AS total, "
                "SUM(CASE WHEN label >= 0 THEN 1 ELSE 0 END) AS labeled, "
                "SUM(CASE WHEN outcome != '' THEN 1 ELSE 0 END) AS with_outcome "
                "FROM decision_record GROUP BY site ORDER BY site").fetchall()
        finally:
            conn.close()
    return {r["site"]: {"total": int(r["total"]), "labeled": int(r["labeled"] or 0),
                        "with_outcome": int(r["with_outcome"] or 0)} for r in rows}


def sites() -> list[str]:
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute("SELECT DISTINCT site FROM decision_record ORDER BY site").fetchall()
        finally:
            conn.close()
    return [r["site"] for r in rows]
