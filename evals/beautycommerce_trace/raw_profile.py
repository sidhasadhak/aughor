"""Raw schema profile — what a careful analyst pulls on first contact with a warehouse.

NO LLM, NO glossary: just structure (tables, columns, types, row counts), per-column
cardinality / null-rate / sample-or-range, and candidate key/FK relationships inferred
from name + uniqueness. This is the substrate the cold trace reasons over.
"""
import duckdb

DB = "data/beautycommerce_analytics.duckdb"
SCHEMA = "analytics"
c = duckdb.connect(DB, read_only=True)


def tables():
    return [r[0] for r in c.execute(
        f"SELECT table_name FROM information_schema.tables WHERE table_schema='{SCHEMA}' ORDER BY table_name"
    ).fetchall()]


def cols(t):
    return c.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        f"WHERE table_schema='{SCHEMA}' AND table_name='{t}' ORDER BY ordinal_position"
    ).fetchall()


def profile_col(t, col, dtype):
    n = c.execute(f"SELECT COUNT(*) FROM {SCHEMA}.{t}").fetchone()[0]
    nulls = c.execute(f'SELECT COUNT(*) FROM {SCHEMA}.{t} WHERE "{col}" IS NULL').fetchone()[0]
    distinct = c.execute(f'SELECT COUNT(DISTINCT "{col}") FROM {SCHEMA}.{t}').fetchone()[0]
    null_pct = round(100 * nulls / n, 1) if n else 0
    info = f"dtype={dtype} distinct={distinct} null%={null_pct}"
    d = dtype.upper()
    if any(x in d for x in ("INT", "DECIMAL", "DOUBLE", "FLOAT", "BIGINT", "NUMERIC")):
        mn, mx, avg = c.execute(
            f'SELECT MIN("{col}"), MAX("{col}"), ROUND(AVG("{col}")::DOUBLE,2) FROM {SCHEMA}.{t}'
        ).fetchone()
        info += f" range=[{mn}..{mx}] avg={avg}"
    elif "DATE" in d or "TIMESTAMP" in d:
        mn, mx = c.execute(f'SELECT MIN("{col}"), MAX("{col}") FROM {SCHEMA}.{t}').fetchone()
        info += f" span=[{mn}..{mx}]"
    else:  # text/bool
        if distinct <= 12:
            vals = [r[0] for r in c.execute(
                f'SELECT DISTINCT "{col}" FROM {SCHEMA}.{t} WHERE "{col}" IS NOT NULL LIMIT 12'
            ).fetchall()]
            info += f" values={vals}"
        else:
            vals = [r[0] for r in c.execute(
                f'SELECT "{col}" FROM {SCHEMA}.{t} WHERE "{col}" IS NOT NULL LIMIT 3'
            ).fetchall()]
            info += f" sample={vals}"
    # candidate primary key?
    if distinct == n and nulls == 0:
        info += "  [PK?]"
    return info


def main():
    ts = tables()
    print(f"=== {SCHEMA} — {len(ts)} tables ===\n")
    for t in ts:
        n = c.execute(f"SELECT COUNT(*) FROM {SCHEMA}.{t}").fetchone()[0]
        print(f"TABLE {SCHEMA}.{t}  ({n:,} rows)")
        for col, dtype in cols(t):
            print(f"    {col:<24} {profile_col(t, col, dtype)}")
        print()


if __name__ == "__main__":
    main()
