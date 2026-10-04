# Live receipt — Arc DE, measured on the machine that holds the connections

**Date:** 2026-10-04 · **Arc:** `ROADMAP.md` §3.51 · **Study:** `docs/DBX_STUDY_2026-10-01.md` §6

**Command:** `scripts/de_live_receipts.py --connection 8233e4fd`

Every statement below went through the connection's own door under the `query_workbench` label, audited like a person's; nothing was written to any warehouse. A section that could not run says so.

## DE-1 · the parse-step audit on 8233e4fd

`de1_parse_step_precheck.py --connection 8233e4fd --limit 2000` → exit 0

```
audit log, connection 8233e4fd, newest 2000
===========================================
statements: 2000   ran without an engine error: 1999   dialect: bigquery
the parse step would refuse: 0   of which valid (ran clean): 0
```

## DE-3c · the typed metadata read on 8233e4fd

engine `bigquery` · strategy `driver_api`

| fact | answer | detail |
|---|---|---|
| columns | supported |  |
| primary_keys | unknown | INFORMATION_SCHEMA.TABLE_CONSTRAINTS carries unenforced keys and the schema API carries field descriptions; neither is read yet |
| foreign_keys | unknown | INFORMATION_SCHEMA.TABLE_CONSTRAINTS carries unenforced keys and the schema API carries field descriptions; neither is read yet |
| comments | unknown | INFORMATION_SCHEMA.TABLE_CONSTRAINTS carries unenforced keys and the schema API carries field descriptions; neither is read yet |

primary keys declared: 0 · foreign keys declared: 0 · comments: 0

## DE-4 · column lineage on 8233e4fd

`de4_lineage_precheck.py --connection 8233e4fd --limit 2000` → exit 0

```
connection 8233e4fd: 1999 audited statements that ran, dialect bigquery, 7 tables, 75 columns in the schema
statements: 1999 (0 failed to parse or qualify)
output columns: 5088 of 7656 resolved to a table column — certain 1659, likely 3429, possible 0
filter columns: 30293  join columns: 1340  group columns: 1022
time: 148.0 ms a statement (schema given)
unresolved:
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`inventory_i
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`inventory_i
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _v ← (WITH `customer_order_counts` AS (SELECT `orders`.`user_id` 
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`orders`.`cr
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _v ← (WITH `customer_order_counts` AS (SELECT `orders`.`user_id` 
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`orders`.`cr
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`events`.`cr
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`events`.`cr
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← COUNT(*) AS `_n`
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← COUNT(*) AS `_n`
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`inventory_i
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`inventory_i
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _v ← (WITH `customer_order_counts` AS (SELECT `orders`.`user_id` 
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`orders`.`cr
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _v ← (WITH `customer_order_counts` AS (SELECT `orders`.`user_id` 
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`orders`.`cr
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`events`.`cr
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`events`.`cr
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` AS `_n` FROM (SELECT MIN(CAST(`order_items
  __brief_period__: _w ← 'current' AS `_w`
  __brief_period__: _n ← (SELECT `_r`.`_n` 
```

## DE-5d · what a page costs against a re-run on 8233e4fd

table `events`, ordered by `id`

| statement | rows | cost words on the trail | error |
|---|---|---|---|
| first page  (LIMIT 501) | 501 | bytes-processed:384810944, bytes-billed:384827392 |  |
| second page (LIMIT 501 OFFSET 500) | 501 | bytes-processed:384810944, bytes-billed:384827392 |  |
| re-run      (LIMIT 1001) | 1001 | bytes-processed:384810944, bytes-billed:384827392 |  |
| count       (COUNT(*)) | 1 | bytes-processed:0, bytes-billed:0 |  |

Falsifier 3 reads off this table: a second page that bills as many bytes as the re-run is a page that costs what the whole result costs.

## DE-5e · the first geometry on 8233e4fd

`distribution_centers.distribution_center_geom` — declared `GEOGRAPHY` in the schema; the typed response names it `GEOGRAPHY`; the value arrives as **WKT**, 23 chars:

```
POINT(-81.1167 32.0167)
```

## Addendum · DE-1 over every audited statement on 8233e4fd

Not part of the script's run. The newest 2,000 statements above are one day (2026-10-03, 09:00Z to 21:55Z) and mostly the platform's own — 1,172 `__brief_period__`, 700 `__monitor__`, about 100 written by a person or a model. The same pre-check over the connection's whole audited history, 2026-08-25 to 2026-10-03, 1,901 distinct statements, read from a snapshot copy of the audit store taken with the API stopped:

`de1_parse_step_precheck.py --connection 8233e4fd --dialect bigquery --limit 30000` → exit 0

```
audit log, connection 8233e4fd, newest 22263
============================================
statements: 22263   ran without an engine error: 19921   dialect: bigquery
the parse step would refuse: 4   of which valid (ran clean): 0
```

## How this receipt was taken

- A first run on 2026-10-03 measured nothing in three sections, and said so in none: both audit pre-checks read each record's `sql`, a key no audit row carries (the store's column is `sql_full`), so 22,267 rows counted as 0 statements and "0 refused"; the geometry step read column types from `sqlglot_schema`, which answers `UNKNOWN` for every column, so it reported no geometry on a schema text naming two GEOGRAPHY columns; and the paging step measured the schema's first table, which holds 10 rows and has no second page. All three were fixed in the scripts before this run (`sql_full`, and a pre-check that reads rows and finds no statement now exits non-zero; types from the schema text's own `TABLE:` lines; the first table with more than 1,001 rows).
- The script opens `data/` itself and audits each statement, so it was run with the API stopped — one writer on those files — and the ledger and the audit store passed `PRAGMA integrity_check` before the API was started again.
- Billed on BigQuery by this run: three scans of `events` at 384.8 MB each (about 1.15 GB). The count billed nothing.
- Still owed: the MySQL, Postgres and Trino sections — no connection ids were given.
