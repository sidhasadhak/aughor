"""Arc DE's live receipts, in one command (ROADMAP §3.51; `docs/DBX_STUDY_2026-10-01.md` §6).

Every wave of Arc DE was built and measured on the build machine, where no warehouse connection is reachable:
no BigQuery (theLook), no Postgres, no MySQL, no Trino. What each wave still owes is a measurement on a live
connection, and this script runs them all and writes one receipt, so finishing the arc on the machine that
holds the connections is one invocation:

    uv run python scripts/de_live_receipts.py --connection 8233e4fd                  # theLook (BigQuery)
    uv run python scripts/de_live_receipts.py --connection 8233e4fd --mysql <id> --postgres <id> --trino <id>

Per connection it runs, each in its own section and each failing on its own (a step that cannot run says so
and the rest still run):

  DE-1   the parse-step audit — what the step would refuse among the connection's newest statements
         (`scripts/de1_parse_step_precheck.py --connection`), and on `--mysql` one live refusal of an executable
         comment with the session's read-only flag beside it
  DE-3b  on `--trino`: one statement through the door, its doors and the declared engine
  DE-3c  the typed metadata read — the coverage row, and how many keys and comments the engine declared
  DE-4   column lineage over the connection's newest statements (`scripts/de4_lineage_precheck.py --connection`)
  DE-5d  the bytes the engine says a page costs against a re-run (the `bytes-processed` / `bytes-billed` /
         `cache-hit` door words) — the study's falsifier 3, measured
  DE-5e  the first GEOGRAPHY / GEOMETRY value the schema holds, its declared type on the typed response and the
         encoding it arrives in (WKT, GeoJSON or WKB as hex)

The receipt goes to `docs/DE_LIVE_RECEIPT_<date>.md` (or `--out`). Nothing is written to any warehouse: every
statement is a read through the connection's own door under the `query_workbench` label, audited like a person's.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

LABEL = "query_workbench"
_WKT = re.compile(r"^\s*(SRID=\d+;)?\s*(POINT|LINESTRING|POLYGON|MULTIPOINT|MULTILINESTRING|MULTIPOLYGON|GEOMETRYCOLLECTION)\b", re.I)
_HEX = re.compile(r"^[0-9A-Fa-f]+$")


class Receipt:
    def __init__(self) -> None:
        self.sections: list[tuple[str, str]] = []

    def add(self, title: str, body: str) -> None:
        self.sections.append((title, body.rstrip()))
        print(f"\n## {title}\n{body.rstrip()}")

    def render(self, argv: list[str]) -> str:
        today = dt.date.today().isoformat()
        head = ["# Live receipt — Arc DE, measured on the machine that holds the connections",
                "", f"**Date:** {today} · **Arc:** `ROADMAP.md` §3.51 · **Study:** `docs/DBX_STUDY_2026-10-01.md` §6", "",
                f"**Command:** `{' '.join(argv)}`", "",
                "Every statement below went through the connection's own door under the `query_workbench` label, audited "
                "like a person's; nothing was written to any warehouse. A section that could not run says so.", ""]
        for title, body in self.sections:
            head += [f"## {title}", "", body, ""]
        return "\n".join(head)


def _open(conn_id: str):
    from aughor.db.connection import open_connection_for
    return open_connection_for(conn_id)


def _step(receipt: Receipt, title: str, fn) -> None:
    try:
        receipt.add(title, fn() or "(nothing to report)")
    except Exception as exc:  # noqa: BLE001 — a receipt records what could not run, in its own words
        receipt.add(title, f"could not run: {type(exc).__name__}: {str(exc)[:500]}")


def _script(name: str, *args: str) -> str:
    cmd = [sys.executable, str(REPO / "scripts" / name), *args]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    text = (out.stdout or "") + (("\n[stderr]\n" + out.stderr) if out.stderr.strip() else "")
    return f"`{' '.join(Path(c).name if c.endswith('.py') else c for c in cmd[1:])}` → exit {out.returncode}\n\n```\n{text.strip()[:6000]}\n```"


def _schema(conn_id: str, db) -> str:
    from aughor.routers._shared import get_schema_cached
    return get_schema_cached(conn_id, db)


def _first_table(schema_text: str) -> tuple[str, str] | None:
    from aughor.db.schema_render import parse_schema_tables
    for table, cols in parse_schema_tables(schema_text or "").items():
        if cols:
            return table, cols[0]
    return None


def _doors(result) -> str:
    return ", ".join(str(d) for d in (getattr(result, "doors", None) or [])) or "(no doors recorded)"


def _cost_words(result) -> list[str]:
    return [str(d) for d in (getattr(result, "doors", None) or [])
            if str(d).startswith(("bytes-processed:", "bytes-billed:")) or str(d) == "cache-hit"]


# ── the steps ────────────────────────────────────────────────────────────────────────────────────

def de1_audit(conn_id: str) -> str:
    return _script("de1_parse_step_precheck.py", "--connection", conn_id, "--limit", "2000")


def de4_lineage(conn_id: str) -> str:
    return _script("de4_lineage_precheck.py", "--connection", conn_id, "--limit", "2000")


def de3c_metadata(conn_id: str) -> str:
    from aughor.db.metadata import read_declared_metadata
    db = _open(conn_id)
    try:
        read = read_declared_metadata(db, cache_key=conn_id)
    finally:
        db.close()
    d = read.as_dict()
    lines = [f"engine `{d['engine']}` · strategy `{d['strategy']}`", "",
             "| fact | answer | detail |", "|---|---|---|"]
    for fact, answer in d["facts"].items():
        lines.append(f"| {fact} | {answer} | {d['detail'].get(fact, '')} |")
    lines += ["", f"primary keys declared: {len(read.primary_keys)} · foreign keys declared: {len(read.foreign_keys)} · "
                  f"comments: {len(read.comments)}"]
    for k in read.foreign_keys[:10]:
        lines.append(f"- {k.table}({', '.join(k.columns)}) → {k.ref_table}({', '.join(k.ref_columns)})")
    return "\n".join(lines)


def de5d_bytes(conn_id: str) -> str:
    db = _open(conn_id)
    try:
        picked = _first_table(_schema(conn_id, db))
        if not picked:
            return "no table with a column in the schema text — nothing to measure"
        table, column = picked
        from aughor.db.quoting import ident_quote
        q = ident_quote(db)
        qt = ".".join(f"{q}{p}{q}" for p in table.split("."))
        inner = f"SELECT * FROM {qt} ORDER BY {q}{column}{q}"
        probes = {
            "first page  (LIMIT 501)":          f"SELECT * FROM ({inner}) __q LIMIT 501",
            "second page (LIMIT 501 OFFSET 500)": f"SELECT * FROM ({inner}) __q LIMIT 501 OFFSET 500",
            "re-run      (LIMIT 1001)":         f"SELECT * FROM ({inner}) __q LIMIT 1001",
            "count       (COUNT(*))":           f"SELECT COUNT(*) AS n FROM ({inner}) __q",
        }
        lines = [f"table `{table}`, ordered by `{column}`", "", "| statement | rows | cost words on the trail | error |",
                 "|---|---|---|---|"]
        for name, sql in probes.items():
            # A bounded read, so the row counts read true past the connector's per-call cap; the door is the same.
            res = db.execute_bounded(LABEL, sql, 1100)
            lines.append(f"| {name} | {len(res.rows)} | {', '.join(_cost_words(res)) or '(none — this engine says no bytes)'} "
                         f"| {str(res.error or '')[:120]} |")
        lines += ["", "Falsifier 3 reads off this table: a second page that bills as many bytes as the re-run is a page "
                      "that costs what the whole result costs."]
        return "\n".join(lines)
    finally:
        db.close()


def de5e_geometry(conn_id: str) -> str:
    db = _open(conn_id)
    try:
        schema_text = _schema(conn_id, db)
        from aughor.db.schema_render import sqlglot_schema
        found: list[tuple[str, str, str]] = []
        for table, cols in (sqlglot_schema(schema_text) or {}).items():
            if not isinstance(cols, dict):
                continue
            for col, typ in cols.items():
                if isinstance(typ, dict):      # schema-qualified: {schema: {table: {col: type}}}
                    for c2, t2 in typ.items():
                        if re.search(r"GEOGRAPHY|GEOMETRY", str(t2), re.I):
                            found.append((f"{table}.{col}", c2, str(t2)))
                elif re.search(r"GEOGRAPHY|GEOMETRY", str(typ), re.I):
                    found.append((table, col, str(typ)))
        if not found:
            return "no GEOGRAPHY or GEOMETRY column in the schema text — this connection holds no geometry to read"
        table, column, declared = found[0]
        from aughor.db.quoting import ident_quote
        q = ident_quote(db)
        qt = ".".join(f"{q}{p}{q}" for p in table.split("."))
        res, payload = db.execute_typed(LABEL, f"SELECT {q}{column}{q} FROM {qt} WHERE {q}{column}{q} IS NOT NULL LIMIT 1")
        if res.error:
            return f"`{table}.{column}` ({declared}): the read failed — {res.error[:300]}"
        if not res.rows:
            return f"`{table}.{column}` ({declared}): every row is NULL — nothing to read"
        from aughor.routers.query import _json_cell
        raw = (payload or {}).get("rows") or [[res.rows[0][0]]]
        cell = _json_cell(raw[0][0])
        typed_name = ((payload or {}).get("types") or [""])[0]
        text = str(cell)
        if _WKT.match(text):
            encoding = "WKT"
        elif text.lstrip().startswith("{"):
            encoding = "GeoJSON" if '"type"' in text else "JSON text, not GeoJSON"
        elif _HEX.match(text.strip()) and len(text.strip()) >= 42:
            encoding = "WKB as hex"
        else:
            encoding = "unrecognised — the viewer will show it as text"
        return (f"`{table}.{column}` — declared `{declared}` in the schema; the typed response names it "
                f"`{typed_name or '(no type offered)'}`; the value arrives as **{encoding}**, {len(text)} chars:\n\n"
                f"```\n{text[:200]}{'…' if len(text) > 200 else ''}\n```")
    finally:
        db.close()


def de3b_trino(conn_id: str) -> str:
    from aughor.db.metadata import engine_type_of
    db = _open(conn_id)
    try:
        res = db.execute(LABEL, "SELECT 1 AS one")
        engine = engine_type_of(db)
        return (f"declared engine: `{engine}` · dialect `{getattr(db, 'dialect', '?')}` · rows {len(res.rows)} · "
                f"error {res.error!r}\n\ndoors: {_doors(res)}")
    finally:
        db.close()


def de1_mysql(conn_id: str) -> str:
    db = _open(conn_id)
    try:
        lines = []
        ro = db.execute(LABEL, "SELECT @@session.transaction_read_only AS ro")
        lines.append(f"`SELECT @@session.transaction_read_only` → rows {ro.rows} · error {ro.error!r}")
        bad = db.execute(LABEL, "/*!50000 DROP TABLE users */ SELECT 1")
        lines.append(f"`/*!50000 DROP TABLE users */ SELECT 1` → error {str(bad.error)[:200]!r}")
        lines.append(f"doors: {_doors(bad)}")
        lines.append("")
        lines.append("Expected: the session is read-only (1) and the executable comment is refused by the parse step, "
                     "with `blocked:validation` on the trail and no `audited`-then-run.")
        return "\n".join(lines)
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--connection", required=True, help="the main connection (theLook's id on the machine that serves it)")
    ap.add_argument("--mysql", help="a MySQL connection id: DE-1's live refusal and the read-only session")
    ap.add_argument("--postgres", help="a Postgres connection id: DE-3c's metadata read")
    ap.add_argument("--trino", help="a Trino connection id: DE-3b's statement through the door")
    ap.add_argument("--out", help="where to write the receipt (default docs/DE_LIVE_RECEIPT_<date>.md)")
    ap.add_argument("--skip", default="", help="comma list of steps to skip: de1,de3c,de4,de5d,de5e")
    args = ap.parse_args()
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    receipt = Receipt()
    cid = args.connection
    if "de1" not in skip:
        _step(receipt, f"DE-1 · the parse-step audit on {cid}", lambda: de1_audit(cid))
    if "de3c" not in skip:
        _step(receipt, f"DE-3c · the typed metadata read on {cid}", lambda: de3c_metadata(cid))
    if "de4" not in skip:
        _step(receipt, f"DE-4 · column lineage on {cid}", lambda: de4_lineage(cid))
    if "de5d" not in skip:
        _step(receipt, f"DE-5d · what a page costs against a re-run on {cid}", lambda: de5d_bytes(cid))
    if "de5e" not in skip:
        _step(receipt, f"DE-5e · the first geometry on {cid}", lambda: de5e_geometry(cid))
    if args.postgres:
        _step(receipt, f"DE-3c · the typed metadata read on Postgres {args.postgres}", lambda: de3c_metadata(args.postgres))
    if args.mysql:
        _step(receipt, f"DE-3c · the typed metadata read on MySQL {args.mysql}", lambda: de3c_metadata(args.mysql))
        _step(receipt, f"DE-1 · one live refusal on MySQL {args.mysql}", lambda: de1_mysql(args.mysql))
    if args.trino:
        _step(receipt, f"DE-3b · Trino {args.trino} through the door", lambda: de3b_trino(args.trino))
        _step(receipt, f"DE-3c · the typed metadata read on Trino {args.trino}", lambda: de3c_metadata(args.trino))

    out = Path(args.out) if args.out else REPO / "docs" / f"DE_LIVE_RECEIPT_{dt.date.today().isoformat()}.md"
    out.write_text(receipt.render(sys.argv), encoding="utf-8")
    print(f"\nreceipt written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
