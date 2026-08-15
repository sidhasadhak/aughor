"""The Data Catalog must obey the column config, and the table cap must actually cap.

Measured on a real deep-analysis run, 2026-08-15 (investigation ac6612df). The question named no
table, so the linker's recall-safety branch returned the schema byte-identical — all 23
tables of a canvas holding four unrelated datasets. `build_data_catalog` then rendered 5
sample rows per table with no truncation and no reference to the per-column config, and
`enforce_context_cap` — called on both paths — counted only `TABLE:` headers, so on a
catalog (`## name`) it was a silent no-op.

The prompt that reached OpenRouter's free tier therefore contained 9 credit-card numbers,
5 e-mail addresses and 2 phone numbers, and 29% of its 28,526 characters were
multi-paragraph cookie reviews inside an airline-outlier question. Every one of those
columns was already marked `sample: false`; `/ask`'s renderer had honoured that flag
since R11. Only this builder did not read it.
"""
import re

import pytest

from aughor.ontology.column_config import ColumnFlags, save_table_config
from aughor.tools.data_catalog import (
    _MAX_CELL_CHARS,
    build_data_catalog,
    clear_cache,
    enforce_context_cap,
)
from aughor.tools.schema_linker import rank_tables_for_context


class _Res:
    def __init__(self, columns, rows):
        self.columns, self.rows = columns, rows
        self.row_count = len(rows)
        self.error = None


class FakeConn:
    """Answers DESCRIBE and the catalog's LIMIT-5 sample; records every sample SELECT so
    a test can assert a column was never even read from the database."""
    dialect = "duckdb"

    def __init__(self, tables, connection_id):
        self._tables = tables           # {table: {"cols": [(name, type)], "row": {col: value}}}
        self._connection_id = connection_id
        self.sample_sql: list[str] = []

    def raw_execute(self, sql):
        m = re.match(r'DESCRIBE "([^"]+)"', sql)
        if not m or m.group(1) not in self._tables:
            raise ValueError(f"unexpected metadata query: {sql}")
        cols = self._tables[m.group(1)]["cols"]
        return ["column_name", "column_type", "null"], [[n, t, "YES"] for n, t in cols], None

    def execute(self, _tag, sql):
        self.sample_sql.append(sql)
        m = re.match(r'SELECT (.+) FROM "([^"]+)" LIMIT 5', sql)
        if not m:
            raise ValueError(f"unexpected query: {sql}")
        cols = [c.strip().strip('"') for c in m.group(1).split(",")]
        row = self._tables[m.group(2)]["row"]
        return _Res(cols, [[row[c] for c in cols]])


CARD = "4539-8721-0043-9912"
EMAIL = "priya.raman@example.com"

_SALES = {
    "sales_transactions": {
        "cols": [("transactionID", "BIGINT"), ("cardNumber", "VARCHAR"),
                 ("paymentMethod", "VARCHAR"), ("totalPrice", "DECIMAL")],
        "row": {"transactionID": 1, "cardNumber": CARD,
                "paymentMethod": "Visa", "totalPrice": 42.5},
    },
}


@pytest.fixture(autouse=True)
def _clean():
    clear_cache()
    yield
    clear_cache()


def _write_config(conn_id, schema, table, flags):
    save_table_config(conn_id, schema, table,
                      {c: ColumnFlags(**f) for c, f in flags.items()})


# ── the leak ─────────────────────────────────────────────────────────────────

def test_sample_false_column_is_never_selected_and_never_rendered():
    conn = FakeConn(_SALES, "c_leak")
    _write_config("c_leak", "default", "sales_transactions", {
        "cardNumber": {"visible": True, "sample": False},
        "paymentMethod": {"visible": True, "sample": True},
    })
    catalog = build_data_catalog(conn, ["sales_transactions"])

    assert CARD not in catalog
    # Defence in depth: the value never entered the process at all, so it cannot reach a
    # log, the catalog cache, or a traceback either.
    assert all("cardNumber" not in sql for sql in conn.sample_sql)
    # The column itself is still declared — the model must know it exists to write SQL.
    assert "| cardNumber | VARCHAR |" in catalog
    assert "Visa" in catalog                      # a sampled dimension is untouched


def test_withheld_columns_are_named_so_they_do_not_read_as_empty():
    conn = FakeConn(_SALES, "c_named")
    _write_config("c_named", "default", "sales_transactions",
                  {"cardNumber": {"visible": True, "sample": False}})
    catalog = build_data_catalog(conn, ["sales_transactions"])
    assert "Sample values withheld by column config" in catalog
    assert "cardNumber" in catalog.split("withheld by column config")[1]


def test_invisible_column_is_pruned_entirely():
    conn = FakeConn(_SALES, "c_hidden")
    _write_config("c_hidden", "default", "sales_transactions",
                  {"cardNumber": {"visible": False, "sample": True}})
    catalog = build_data_catalog(conn, ["sales_transactions"])
    assert "cardNumber" not in catalog            # not even the column line
    assert CARD not in catalog
    assert "transactionID" in catalog


def test_no_config_is_the_old_behaviour():
    # Fail-open: a connection with no config store renders exactly as before, so this
    # change cannot silently blank a catalog for connections that never got a build.
    conn = FakeConn(_SALES, "c_none")
    catalog = build_data_catalog(conn, ["sales_transactions"])
    assert CARD in catalog and "Visa" in catalog
    assert "withheld" not in catalog


def test_schema_qualified_table_finds_its_own_schema_config():
    tables = {"main.sales_customers": {
        "cols": [("customerID", "BIGINT"), ("email_address", "VARCHAR")],
        "row": {"customerID": 7, "email_address": EMAIL},
    }}
    conn = FakeConn(tables, "workspace")
    _write_config("workspace", "main", "sales_customers",
                  {"email_address": {"visible": True, "sample": False}})
    catalog = build_data_catalog(conn, ["main.sales_customers"])
    assert EMAIL not in catalog


# ── the blob bloat ───────────────────────────────────────────────────────────

def test_long_cells_are_truncated():
    review = "These cookies were " + ("delicious and chewy " * 200)
    conn = FakeConn({"media_customer_reviews": {
        "cols": [("new_id", "BIGINT"), ("review", "VARCHAR")],
        "row": {"new_id": 1, "review": review},
    }}, "c_blob")
    # sample stays ON, so this measures truncation alone, not the config filter.
    catalog = build_data_catalog(conn, ["media_customer_reviews"])
    assert "…[truncated]" in catalog
    assert len(catalog) < len(review)
    assert review[:50] in catalog                 # the shape of the value survives


# ── the cache must not outlive the policy ────────────────────────────────────

def test_turning_sample_off_invalidates_the_cached_catalog():
    conn = FakeConn(_SALES, "c_cache")
    assert CARD in build_data_catalog(conn, ["sales_transactions"])
    _write_config("c_cache", "default", "sales_transactions",
                  {"cardNumber": {"visible": True, "sample": False}})
    # Same connection, same tables — a table-only cache key would serve the card number
    # for the next hour.
    assert CARD not in build_data_catalog(conn, ["sales_transactions"])


# ── the cap that was blind ───────────────────────────────────────────────────

def test_context_cap_counts_catalog_headers():
    catalog = "\n\n".join(f"## t{i}\n\n| Column | Type |\n| c | INT |" for i in range(23))
    out = enforce_context_cap(catalog, max_tables=10)
    assert out.count("## t") == 10
    assert "## t10" not in out
    assert "CONTEXT CAP: 23 tables available" in out


def test_context_cap_still_counts_raw_schema_headers():
    schema = "\n\n".join(f"TABLE: t{i}\n  c  INT" for i in range(12))
    out = enforce_context_cap(schema, max_tables=4)
    assert out.count("TABLE: t") == 4


def test_context_cap_is_a_noop_under_the_limit():
    catalog = "## a\n\n| Column |\n\n## b\n\n| Column |"
    assert enforce_context_cap(catalog, max_tables=10) == catalog


# ── ranking when the linker abstains ─────────────────────────────────────────

_MIXED_SCHEMA = "\n\n".join([
    # A canvas of unrelated datasets: an airline core that joins up, plus free-floating
    # media/sales tables — the 2026-08-15 shape in miniature. Deliberately ordered so
    # alphabetical/schema order would keep the WRONG tables.
    "TABLE: media_customer_reviews\n  new_id  BIGINT\n  review  VARCHAR",
    "TABLE: cookie_notes\n  note_id  BIGINT\n  note  VARCHAR",
    "TABLE: flights\n  flight_id  BIGINT\n  aircraft_id  BIGINT\n  delay_minutes  INTEGER",
    "TABLE: bookings\n  booking_id  BIGINT\n  flight_id  BIGINT\n  amount  DECIMAL",
    "TABLE: tickets\n  ticket_id  BIGINT\n  booking_id  BIGINT\n  flight_id  BIGINT",
    "TABLE: dim_date\n  d_date_sk  BIGINT\n  year  INTEGER",
])
_MIXED = ["media_customer_reviews", "cookie_notes", "flights", "bookings", "tickets", "dim_date"]


def test_a_named_table_outranks_the_unrelated_ones():
    kept = rank_tables_for_context("which flights had the worst delays?",
                                   _MIXED_SCHEMA, _MIXED, cap=2)
    assert kept[0] == "flights"
    assert "media_customer_reviews" not in kept


def test_no_signal_falls_back_to_the_connected_core_not_schema_order():
    # The 2026-08-15 question: no table matches a keyword. Schema order would keep the two
    # free-floating blob tables that happen to come first; FK degree keeps the tables that
    # actually join to something — which is what "the entities in this data" means.
    kept = rank_tables_for_context("profile the most unusual entities in this data",
                                   _MIXED_SCHEMA, _MIXED, cap=3)
    assert len(kept) == 3
    assert set(kept) == {"flights", "bookings", "tickets"}
    assert "media_customer_reviews" not in kept
    assert "cookie_notes" not in kept


def test_no_signal_and_no_joins_is_still_capped_deterministically():
    # Nothing scores AND nothing joins — the cap must still hold, in the schema's own
    # order, rather than falling through to "send everything".
    flat = "\n\n".join(f"TABLE: t{i}\n  c{i}  VARCHAR" for i in range(5))
    kept = rank_tables_for_context("profile the entities", flat,
                                   [f"t{i}" for i in range(5)], cap=2)
    assert kept == ["t0", "t1"]


def test_a_pinned_temporal_dimension_survives_the_cut():
    # dim_date is added BECAUSE the question never names it, so it scores zero and any
    # relevance cut drops it first — unless it is pinned.
    kept = rank_tables_for_context("monthly bookings revenue", _MIXED_SCHEMA, _MIXED,
                                   cap=2, pinned=["dim_date"])
    assert "dim_date" in kept
    assert "bookings" in kept
    assert len(kept) == 2


def test_ranking_is_a_noop_when_everything_fits():
    assert rank_tables_for_context("anything", _MIXED_SCHEMA, _MIXED, cap=10) == _MIXED


# ── the cap must not go blind on a capable model ─────────────────────────────

_WIDE = [f"t{i}" for i in range(23)]
_WIDE_SCHEMA = "\n\n".join(f"TABLE: t{i}\n  t{i}_id  BIGINT\n  label  VARCHAR" for i in range(23))


def test_no_signal_is_capped_below_a_capable_models_budget():
    # `context_table_cap` is 10 on the baseline tier but 24 on a capable model, and the
    # canvas that produced the 2026-08-15 report had 23 tables — so on the model class
    # most likely to be pointed at a big canvas, a cap of 24 would cap NOTHING. With no
    # relevance signal the conservative baseline applies regardless of what the caller
    # can afford.
    kept = rank_tables_for_context("profile the most unusual entities in this data",
                                   _WIDE_SCHEMA, _WIDE, cap=24)
    assert len(kept) == 10


def test_a_grounded_ranking_still_gets_the_full_caller_budget():
    # The tightening is about ABSENT evidence, not about distrusting the profile: when
    # tables actually score, the caller's larger budget is honoured.
    schema = _WIDE_SCHEMA + "\n\nTABLE: flights\n  flight_id  BIGINT\n  delay_minutes  INTEGER"
    kept = rank_tables_for_context("which flights had the worst delays?",
                                   schema, _WIDE + ["flights"], cap=15)
    assert len(kept) == 15
    assert kept[0] == "flights"


def test_a_pin_survives_the_no_signal_tightening_too():
    pinned = ["t22"]
    kept = rank_tables_for_context("profile the entities", _WIDE_SCHEMA, _WIDE,
                                   cap=24, pinned=pinned)
    assert len(kept) == 10
    assert "t22" in kept                          # last by schema order, kept by the pin


def test_truncation_constant_is_a_shape_not_a_paragraph():
    assert 50 <= _MAX_CELL_CHARS <= 500
