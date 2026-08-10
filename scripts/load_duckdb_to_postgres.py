#!/usr/bin/env python
"""Copy a DuckDB file's tables into Postgres, so a deployment has data to query.

`scripts/migrate_sqlite_to_postgres.py` moves the platform's own STATE — history,
receipts, the connection registry — and deliberately skips `*.duckdb`, calling it "the
analytics tier, not relational platform state". That is the right call for what it does,
and it leaves a gap this fills: on Vercel nothing serves the analytics tier at all. No
`.duckdb` file is tracked in git (`.gitignore` names them one by one), the filesystem is
thrown away between requests, and production comes up with a connection list and empty
shelves behind it. This is the one-time copy that puts the tables somewhere that persists.

The two scripts are siblings, not alternatives:

    AUGHOR_DB_URL=…                  scripts/migrate_sqlite_to_postgres.py   # platform state
    AUGHOR_DEFAULT_POSTGRES_DSN=…    scripts/load_duckdb_to_postgres.py      # data to query

They can name the same database. They are separate because they answer different
questions — "does the deployment remember anything" and "is there anything in it".

THE DSN IS READ FROM THE ENVIRONMENT, NEVER FROM AN ARGUMENT. A connection string on the
command line is a password in the shell history and in every `ps` listing while the copy
runs, which for a load that takes minutes is not a small window.

Types are mapped conservatively and NEVER narrowed. Anything unrecognised lands in TEXT
rather than being guessed at, because this codebase has already paid for the other
approach: a currency column silently narrowed on reload, losing data that looked fine
until someone summed it. A column that arrives as TEXT is visible and fixable; a column
that arrives as BIGINT because `TRY_CAST('4.2' AS BIGINT)` happens to succeed in DuckDB
is neither.

Refuses a non-empty target schema unless `--wipe`, and verifies itself: per-table row
counts source against target, non-zero exit on any mismatch. Both conventions are
borrowed from the sibling script on purpose — a half-written target must never be
silently merged into, and a copy that says nothing about whether it worked is not a copy
you can deploy behind.

Usage:
    AUGHOR_DEFAULT_POSTGRES_DSN=postgres://… \\
        uv run python scripts/load_duckdb_to_postgres.py data/luxexperience_demo.duckdb [--wipe]

    # inspect first, touch nothing
    AUGHOR_DEFAULT_POSTGRES_DSN=postgres://… \\
        uv run python scripts/load_duckdb_to_postgres.py data/aughor.duckdb --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

#: DuckDB type → Postgres type. Only exact, lossless correspondences are listed; the
#: fallback is TEXT, which is the point (see the module docstring). DECIMAL carries its
#: precision through the `startswith` branch below rather than appearing here.
_TYPE_MAP = {
    "BOOLEAN": "BOOLEAN",
    "TINYINT": "SMALLINT",
    "SMALLINT": "SMALLINT",
    "INTEGER": "INTEGER",
    "BIGINT": "BIGINT",
    "HUGEINT": "NUMERIC",          # 128-bit: NUMERIC is the only faithful home
    "UTINYINT": "SMALLINT",
    "USMALLINT": "INTEGER",
    "UINTEGER": "BIGINT",
    "UBIGINT": "NUMERIC",          # unsigned 64-bit overflows Postgres BIGINT
    "FLOAT": "REAL",
    "REAL": "REAL",
    "DOUBLE": "DOUBLE PRECISION",
    "VARCHAR": "TEXT",
    "BLOB": "BYTEA",
    "DATE": "DATE",
    "TIME": "TIME",
    "TIMESTAMP": "TIMESTAMP",
    "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ",
    "TIMESTAMP_NS": "TIMESTAMP",
    "TIMESTAMP_MS": "TIMESTAMP",
    "TIMESTAMP_S": "TIMESTAMP",
    "UUID": "UUID",
    "JSON": "JSONB",
    "INTERVAL": "INTERVAL",
}

BATCH = 5000

#: Markers of a DSN that was copied from an example and never filled in. Worth detecting
#: rather than letting the driver fail on it: a placeholder produces the same
#: `OperationalError` as a genuinely unreachable host, and the two want opposite replies.
_PLACEHOLDER_MARKS = ("…", "...", "<", ">", "your-", "your_", "your ", "example.com",
                      "USER:PASSWORD", "HOST", "DBNAME", "changeme")


def _looks_unfilled(dsn: str) -> bool:
    host = dsn.split("@")[-1] if "@" in dsn else dsn
    return any(m in host for m in _PLACEHOLDER_MARKS)


def _pg_type(duck_type: str) -> str:
    t = (duck_type or "").upper().strip()
    if t in _TYPE_MAP:
        return _TYPE_MAP[t]
    if t.startswith("DECIMAL") or t.startswith("NUMERIC"):
        return t.replace("DECIMAL", "NUMERIC")       # DECIMAL(18,2) → NUMERIC(18,2)
    # Nested and unknown types (LIST, STRUCT, MAP, ENUM, …). TEXT keeps the value
    # readable and the failure visible, which is the whole policy.
    return "TEXT"


def _tables(duck, source_schema: str | None) -> list[tuple[str, str]]:
    q = "SELECT schema_name, table_name FROM duckdb_tables()"
    args: list = []
    if source_schema:
        q += " WHERE schema_name = ?"
        args.append(source_schema)
    return [(s, t) for s, t in duck.execute(q + " ORDER BY 1, 2", args).fetchall()]


def load(duckdb_path: Path, dsn: str, *, target_schema: str | None,
         only: set[str] | None, wipe: bool, dry_run: bool) -> int:
    import duckdb as ddb
    import psycopg2
    from psycopg2.extras import execute_values

    # The target is checked FIRST, before the source is opened or a single line is
    # printed. Connecting last meant a bad DSN produced a cheerful "14 tables" header and
    # then a failure, which reads as "it got partway through" when nothing had been
    # touched at all — and on a buffered stdout the two even arrived out of order.
    pg = None
    if not dry_run:
        try:
            pg = psycopg2.connect(dsn, connect_timeout=10)
        except psycopg2.OperationalError as exc:
            print(f"could not connect to Postgres: "
                  f"{str(exc).strip().splitlines()[0]}", file=sys.stderr)
            if _looks_unfilled(dsn):
                print("\nThat DSN still contains a placeholder — substitute the real one:\n"
                      "    AUGHOR_DEFAULT_POSTGRES_DSN='postgresql://USER:PASSWORD@HOST:5432/DBNAME' \\\n"
                      f"        uv run python scripts/{Path(__file__).name} "
                      f"{duckdb_path} --wipe", file=sys.stderr)
            else:
                print("\nCheck the host is reachable and the credentials are right. "
                      "`--dry-run` needs no database at all if you only want to see "
                      "what would be copied.", file=sys.stderr)
            return 2

    duck = ddb.connect(str(duckdb_path), read_only=True)
    found = _tables(duck, None)
    if not found:
        print(f"{duckdb_path.name}: no tables", file=sys.stderr)
        duck.close()
        if pg: pg.close()
        return 1

    # The DuckDB schema is the default target schema, so `luxexperience.orders` stays
    # `luxexperience.orders` — the app scopes connections by schema name, and renaming
    # it here would quietly break every saved reference to a table.
    schemas = {s for s, _ in found}
    if target_schema is None and len(schemas) > 1:
        print(f"{duckdb_path.name} spans {sorted(schemas)} — name one with --schema",
              file=sys.stderr)
        duck.close()
        if pg: pg.close()
        return 2
    dest = target_schema or next(iter(schemas))

    selected = [(s, t) for s, t in found if not only or t in only]
    if only:
        missing = only - {t for _, t in selected}
        if missing:
            print(f"not in {duckdb_path.name}: {sorted(missing)}", file=sys.stderr)
            duck.close()
            if pg: pg.close()
            return 2

    print(f"{duckdb_path.name} → postgres schema \"{dest}\"  ({len(selected)} tables)")
    if dry_run:
        for s, t in selected:
            n = duck.execute(f'SELECT count(*) FROM "{s}"."{t}"').fetchone()[0]
            cols = duck.execute(f'DESCRIBE "{s}"."{t}"').fetchall()
            print(f"  {t:28} {n:9,} rows  {len(cols):3} cols")
        print("dry run — nothing written")
        duck.close()
        return 0

    try:
        cur = pg.cursor()
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = %s",
                    (dest,))
        if cur.fetchone()[0]:
            if not wipe:
                print(f'target schema "{dest}" is not empty — re-run with --wipe to drop '
                      "and recreate it", file=sys.stderr)
                return 2
            cur.execute(f'DROP SCHEMA IF EXISTS "{dest}" CASCADE')
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{dest}"')
        pg.commit()

        total_rows = 0
        mismatches: list[str] = []
        done: list[str] = []
        for src_schema, table in selected:
            cols = duck.execute(f'DESCRIBE "{src_schema}"."{table}"').fetchall()
            coldefs = ", ".join(f'"{c[0]}" {_pg_type(c[1])}' for c in cols)
            names = [c[0] for c in cols]
            collist = ", ".join(f'"{n}"' for n in names)
            src_n = duck.execute(f'SELECT count(*) FROM "{src_schema}"."{table}"').fetchone()[0]

            # Named before the work, and flushed. A 700k-row load over the internet takes
            # minutes, and Python buffers stdout when it is not a terminal — so without
            # this the whole thing looks hung until it is finished, which is exactly when
            # someone decides it has hung and kills it.
            print(f"  {table:28} {src_n:>9,} rows ", end="", flush=True)
            try:
                cur.execute(f'CREATE TABLE "{dest}"."{table}" ({coldefs})')
                insert = f'INSERT INTO "{dest}"."{table}" ({collist}) VALUES %s'
                reader = duck.execute(f'SELECT {collist} FROM "{src_schema}"."{table}"')
                copied = 0
                while True:
                    batch = reader.fetchmany(BATCH)
                    if not batch:
                        break
                    execute_values(cur, insert, batch, page_size=BATCH)
                    copied += len(batch)
                    if src_n > 50_000:          # a dot per batch on the big ones
                        print(".", end="", flush=True)
                pg.commit()
            except Exception as exc:
                # One table's failure ends the load, but it must not end it as a
                # traceback. Earlier tables are already committed — each commits on its
                # own, because a single transaction around 700k rows is its own risk — so
                # the target is now PARTIAL, and the only safe next step is to say so and
                # name it. A loader that dies silently mid-way leaves a database that
                # looks loaded.
                pg.rollback()
                print(" FAILED", flush=True)
                print(f"\n{type(exc).__name__} on {dest}.{table}: "
                      f"{str(exc).strip().splitlines()[0]}", file=sys.stderr)
                print(f"\n{len(done)} of {len(selected)} tables were copied before this "
                      f"({', '.join(done) or 'none'}).\n"
                      f"The target schema \"{dest}\" is now PARTIAL — it must not be used "
                      f"as-is. Re-run the same command with --wipe to start clean.",
                      file=sys.stderr)
                return 1

            cur.execute(f'SELECT count(*) FROM "{dest}"."{table}"')
            got = cur.fetchone()[0]
            if got != src_n:
                mismatches.append(f"{dest}.{table}: src={src_n} dst={got}")
            total_rows += copied
            done.append(table)
            print(f" {'MISMATCH' if got != src_n else 'ok'}", flush=True)

        cur.close()
        print(f"TOTAL: {len(selected)} tables, {total_rows:,} rows")
        if mismatches:
            print("ROW-COUNT MISMATCHES:\n  " + "\n  ".join(mismatches), file=sys.stderr)
            return 1
        print("verified: every table's row count matches its source")
        return 0
    finally:
        pg.close()
        duck.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("duckdb", type=Path, help="the .duckdb file to copy FROM")
    ap.add_argument("--schema", default=None,
                    help="target postgres schema (default: the DuckDB schema's own name)")
    ap.add_argument("--only", default="",
                    help="comma-separated table names; default is every table")
    ap.add_argument("--wipe", action="store_true",
                    help="drop and recreate the target schema first")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be copied and write nothing")
    args = ap.parse_args()

    if not args.duckdb.exists():
        print(f"no such file: {args.duckdb}", file=sys.stderr)
        return 2

    # Env, not argv — see the module docstring. --dry-run needs no credential, so it
    # stays usable for anyone inspecting a file before deciding anything.
    dsn = os.environ.get("AUGHOR_DEFAULT_POSTGRES_DSN", "")
    if not args.dry_run and not (dsn.startswith("postgres://") or dsn.startswith("postgresql://")):
        print("AUGHOR_DEFAULT_POSTGRES_DSN must name the target postgres:// database "
              "(it is read from the environment, never from an argument)", file=sys.stderr)
        return 2

    only = {t.strip() for t in args.only.split(",") if t.strip()} or None
    return load(args.duckdb, dsn, target_schema=args.schema, only=only,
                wipe=args.wipe, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
