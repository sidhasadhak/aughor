# DuckDB, where it differs from what you expect

Where DuckDB silently disagrees with Postgres, MySQL and Snowflake: integer division,
rounding casts, date arithmetic that returns a number, functions from other dialects that
do not exist, and a table name that can read a file.

This is not an introduction to DuckDB. It is the short list of places where SQL that looks
right, and would be right elsewhere, is wrong here — usually without an error.

Every statement below was **run against DuckDB** and its output recorded; the executable
copy is `tests/unit/test_duckdb_engine_pack.py`, which fails if the engine stops behaving
this way or if a claim here is edited into something untrue. Nothing is recalled from
documentation.

## `/` is float division

    5 / 2   -> 2.5        -- not 2
    5 // 2  -> 2          -- integer division is the double slash

On Postgres and MySQL, `5/2` is `2`. A ratio written as `count(a)/count(b)` therefore
returns a *different number* on DuckDB than the same text does on a warehouse — and it is
DuckDB that gives the answer you actually wanted. Port a query in either direction and this
is the line that changes meaning without erroring.

## `CAST`/`TRY_CAST` to an integer ROUNDS

    TRY_CAST('4.2' AS BIGINT)   -> 4
    TRY_CAST('4.5' AS BIGINT)   -> 5
    TRY_CAST('4.9' AS BIGINT)   -> 5
    TRY_CAST('-4.9' AS BIGINT)  -> -5

`TRY_CAST` returns NULL when a value *cannot* be read as the target type — so people use a
non-NULL result as proof the column is integral. It is not. A rating of `4.9` cast to BIGINT
becomes `5`, and nothing errors. This is how a price or rating column stored as VARCHAR gets
typed as BIGINT and silently loses its fractions.

Prove the column first, do not infer it:

    SELECT count(*) FILTER (
      WHERE try_cast(c AS DOUBLE) IS NOT NULL
        AND try_cast(c AS DOUBLE) <> floor(try_cast(c AS DOUBLE))
    ) AS fractional_values
    FROM t

`TRY_CAST` also returns NULL for anything with formatting in it — `'1,234'` and `'$4.20'`
are both NULL, not 1234 and 4.20. Strip separators and currency symbols before casting.

## Date arithmetic returns an integer, not an interval

    typeof(DATE '2024-03-01' - DATE '2024-01-01')            -> BIGINT   (value: 60)
    typeof(TIMESTAMP '2024-03-01' - TIMESTAMP '2024-01-01')  -> INTERVAL

So on DATEs the difference is *already* a number of days, and wrapping it errors:

    date_part('day', d2 - d1)          -- Binder Error: No function matches
    EXTRACT(EPOCH FROM (d2 - d1))      -- same

Use `d2 - d1` directly for days, or `date_diff('day', d1, d2)`. On TIMESTAMPs the
subtraction *is* an interval, so `EXTRACT(EPOCH FROM (t2 - t1))` is valid there — cast both
sides to TIMESTAMP if you need seconds.

## Functions from other dialects that do not exist here

| You wrote | DuckDB says | Use instead |
|---|---|---|
| `TIMESTAMPDIFF(...)` | Catalog Error | `date_diff('day', a, b)` or `b - a` on DATEs |
| `JULIANDAY(d)` | Catalog Error | `date_diff('day', DATE '1970-01-01', d)` |
| `to_char(d, 'YYYY-MM')` | Catalog Error | `strftime(d, '%Y-%m')`, or `date_trunc('month', d)` to bucket |
| `epoch_days(d)` | Catalog Error | `epoch(d)` for seconds; the family is `epoch`, `epoch_ms`, `epoch_us`, `epoch_ns` |

`epoch_days` is on this list because this product's own SQL-repair advice recommended it for
two years. A function name that sounds right is not a function.

## A bare table name does not search other schemas

    SELECT count(*) FROM orders      -- Catalog Error, even with s1.orders present
    SELECT count(*) FROM s1.orders   -- 1

There is no cross-schema search path. On a connection with more than one schema, always
qualify. Dropping the qualifier does not fall back — it fails.

## A table source that is not a table is read as a FILE

    SELECT count(*) FROM 'data.csv'      -- reads the file
    SELECT count(*) FROM "data.csv"      -- reads the file
    SELECT count(*) FROM data.csv        -- reads the file — bare relative name, unquoted
    SELECT count(*) FROM /tmp/data.csv   -- Parser Error: a path containing / must be quoted

DuckDB's replacement scan turns an unmatched table name into a file read. Convenient when
you mean it. When you *mistype a table name that happens to look like a file*, you get
someone's file instead of "table does not exist" — and the unquoted form makes that
reachable from a name with no quoting at all, as long as it has no slash in it.

## Parameters are `$name`, never `:name`

    SELECT $who      -- binds
    SELECT ?         -- binds, positional
    SELECT :who      -- Parser Error: syntax error at or near ":"

Aughor's SQL editor accepts `:name` and rewrites it before execution, so `:name` is the
right thing to type *there*. Anywhere you hand SQL to the driver yourself, it must be
`$name`.

## `approx_count_distinct` is approximate

    SELECT approx_count_distinct(id) FROM t   -- 11, on a table with 10 distinct ids

It is HyperLogLog, and it is wrong on small inputs in a way that looks like a real number.
Use `count(DISTINCT id)` unless the table is large enough that the trade is worth making,
and never quote its output as an exact figure.

## Worth using, because DuckDB has it and your other warehouse may not

    SELECT * EXCLUDE (internal_id) FROM t
    SELECT * REPLACE (amount * 2 AS amount) FROM t
    SELECT g, count(*) FROM t GROUP BY ALL
    SELECT id FROM t QUALIFY row_number() OVER (PARTITION BY g ORDER BY id) = 1
    SELECT count(*) FROM t USING SAMPLE 10%          -- TABLESAMPLE (10 PERCENT) also works

`QUALIFY` removes the subquery a window filter otherwise needs. `GROUP BY ALL` removes the
class of bug where the SELECT list and the GROUP BY drift apart.

## Types coming back

`1.5` is `DECIMAL(2,1)`, not a float — DuckDB returns DECIMAL columns as Python `Decimal`,
which fails a `float`-only check. `avg()` over a DECIMAL returns DOUBLE. If you compare a
column's type to what an aggregate over it produces, they will not match.
