"""Migrate the platform's SQLite stores into one Postgres — the cutover script.

Phase 3 of docs/VERCEL_PLATFORM_DESIGN_2026-08-05.md. The serving code already runs
on Postgres behind ``AUGHOR_DB_URL`` (schema-per-store, dialect translated at the
seam); what a deployment lacks is its DATA. This script moves it:

1. **Every platform ``data/*.db`` file** → its ``store_{stem}`` schema: the DDL is
   read from ``sqlite_master`` and run through the SAME ``backend.translate()`` the
   serving path uses — so a migrated table is byte-identical in shape to what the
   store would have created itself — then rows bulk-copy, and ``PRAGMA
   user_version`` carries into ``_aughor_meta`` so migrations do not re-apply.
2. **The JSON family stores** (exploration_*/business_profile_* legacy files) import
   through their own ``get_entry`` path against the Postgres-backed ledger — the
   migration IS the store's legacy-import path, pointed at the target.

Deliberately skipped, with reasons:
- ``checkpoints.db`` — LangGraph's SqliteSaver; its Postgres story is PostgresSaver,
  which owns a DIFFERENT schema. Copying sqlite-saver tables would be dead weight.
- ``*.duckdb`` — the analytics tier (MotherDuck / warehouse pushdown / Blob), not
  relational platform state.
- ``mat_cache`` / ``eval_baseline`` etc. that are rebuildable caches still migrate:
  cheap, and a warm start beats a cold one.

Refuses a NON-EMPTY target schema unless ``--wipe`` (drop-and-recreate) is given:
a half-written target must never be silently merged into. Verifies itself: per-table
row counts source vs target, and exits non-zero on any mismatch.

Usage:
    AUGHOR_DB_URL=postgres://… uv run python scripts/migrate_sqlite_to_postgres.py [--wipe] [--data-dir data]
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

SKIP_FILES = {
    "checkpoints.db",   # LangGraph SqliteSaver → PostgresSaver owns its own schema
}


def _pg(url: str, schema: str):
    from aughor.db.backend import PgConnection
    return PgConnection(url, schema=schema)


def _schema_for(db_file: Path) -> str:
    return "store_" + re.sub(r"[^a-z0-9_]", "_", db_file.stem.lower())


def migrate_db_file(db_file: Path, url: str, *, wipe: bool) -> tuple[int, int, list[str]]:
    """One sqlite file → its Postgres schema. Returns (tables, rows, mismatches)."""

    schema = _schema_for(db_file)
    src = sqlite3.connect(str(db_file))
    src.row_factory = sqlite3.Row
    objects = src.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type DESC"  # tables first
    ).fetchall()

    dst = _pg(url, schema)
    try:
        if wipe:
            cur = dst._pg.cursor()
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            cur.execute(f'CREATE SCHEMA "{schema}"')
            cur.execute(f'SET search_path TO "{schema}"')
            cur.close()
            dst.commit()
        else:
            existing = dst.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = ?",
                (schema,)).fetchone()[0]
            if existing:
                raise SystemExit(
                    f"{db_file.name}: target schema {schema} is not empty — "
                    "re-run with --wipe to drop and recreate it")

        n_tables = n_rows = 0
        mismatches: list[str] = []
        for obj in objects:
            dst.execute(obj["sql"])          # translate() maps DDL + types at the seam
            if obj["type"] != "table":
                continue
            n_tables += 1
            rows = src.execute(f'SELECT * FROM "{obj["name"]}"').fetchall()
            if rows:
                cols = rows[0].keys()
                placeholders = ",".join("?" * len(cols))
                collist = ",".join(f'"{c}"' for c in cols)
                insert = f'INSERT INTO "{obj["name"]}" ({collist}) VALUES ({placeholders})'
                batch = [tuple(r) for r in rows]
                for i in range(0, len(batch), 1000):
                    dst.executemany(insert, batch[i:i + 1000])
                n_rows += len(batch)
            got = dst.execute(f'SELECT count(*) FROM "{obj["name"]}"').fetchone()[0]
            if got != len(rows):
                mismatches.append(f"{schema}.{obj['name']}: src={len(rows)} dst={got}")
            # AUTOINCREMENT became a BY DEFAULT identity; after copying explicit ids
            # its sequence still sits at 1, and the first serving insert would
            # collide. Advance every identity sequence past the copied maximum.
            cur = dst._pg.cursor()
            cur.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema = %s AND table_name = %s
                     AND is_identity = 'YES'""", (schema, obj["name"]))
            for (id_col,) in cur.fetchall():
                cur.execute(
                    f'SELECT setval(pg_get_serial_sequence(\'"{schema}"."{obj["name"]}"\', %s),'
                    f' COALESCE((SELECT MAX("{id_col}") FROM "{obj["name"]}"), 0) + 1, false)',
                    (id_col,))
            cur.close()

        # user_version → _aughor_meta, so store migrations do not re-apply on PG.
        uv = src.execute("PRAGMA user_version").fetchone()[0]
        if uv:
            dst.execute(f"PRAGMA user_version = {int(uv)}")
        dst.commit()
        # translate() cache is shared process-wide; nothing to reset between files.
        return n_tables, n_rows, mismatches
    finally:
        dst.close()
        src.close()


def import_json_families(data_dir: Path) -> dict[str, int]:
    """Legacy per-key JSON files → the Postgres-backed family stores, through the
    stores' OWN import path (get_entry), so key naming cannot drift from serving."""
    counts: dict[str, int] = {}
    from aughor.business_profile import store as profile_store
    from aughor.explorer import store as explorer_store

    for prefix, family, label in (
        ("exploration_", explorer_store._family, "exploration"),
        ("business_profile_", profile_store._family, "business_profile"),
    ):
        n = 0
        for f in sorted(data_dir.glob(f"{prefix}*.json")):
            if f.name.endswith("__family.json"):
                continue
            key = f.stem[len(prefix):]
            if family().get_entry(key) is not None:
                n += 1
        counts[label] = n
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default="data", type=Path)
    ap.add_argument("--wipe", action="store_true",
                    help="drop and recreate each target schema before copying")
    args = ap.parse_args()

    url = os.environ.get("AUGHOR_DB_URL", "")
    if not (url.startswith("postgres://") or url.startswith("postgresql://")):
        print("AUGHOR_DB_URL must name the target postgres:// database", file=sys.stderr)
        return 2

    total_tables = total_rows = 0
    all_mismatches: list[str] = []
    db_files = sorted(p for p in args.data_dir.glob("*.db") if p.name not in SKIP_FILES)
    for db_file in db_files:
        tables, rows, mismatches = migrate_db_file(db_file, url, wipe=args.wipe)
        total_tables += tables
        total_rows += rows
        all_mismatches.extend(mismatches)
        flag = " MISMATCH" if mismatches else ""
        print(f"  {db_file.name:32} {tables:3} tables {rows:8,} rows{flag}")

    fam = import_json_families(args.data_dir)
    print(f"  json families: {fam}")
    print(f"TOTAL: {len(db_files)} stores, {total_tables} tables, {total_rows:,} rows")
    if all_mismatches:
        print("ROW-COUNT MISMATCHES:\n  " + "\n  ".join(all_mismatches), file=sys.stderr)
        return 1
    print("verified: every table's row count matches its source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
