"""Numbers stored as text — '₹1,099', '64%', '24,269' — must reach the analyst as numbers.

The defect this pins: a retail export whose price columns are currency-formatted text
produced a report titled "Discount leakage cannot be assessed: price data missing
across all dimensions" over data that was 100% populated. Every layer was individually
reasonable — DuckDB types '₹1,099' as VARCHAR because it IS a string; the metric
planner reads a type, not values; TRY_CAST of that text is NULL; a uniform-NULL result
is correctly flagged degenerate. Nothing in the chain ever looked at a value.

Three layers are covered here, in the order they fire:
  1. INGEST      re-types the column, so the planner sees a number at all.
  2. SCHEMA      carries sample values, so a planner can see a costume it must handle.
  3. DIAGNOSIS   when a metric still comes back all-NULL, says WHY — present-but-unparsed
                 vs. genuinely absent, which call for opposite work.

Hermetic: an isolated storage root; connectors are rebuilt fresh (as they are
per-request in the app) to exercise the reload path.
"""
from __future__ import annotations

import json

import duckdb
import pytest

from aughor.connectors.file.local_upload import LocalUploadConnection
from aughor.control_plane import vending
from aughor.explorer.verify import unparsed_numeric_diagnosis, verify_insight
from aughor.db.schema_render import (
    format_value_samples,
    parse_schema_tables,
    strip_value_samples,
)
from aughor.sql.numeric_text import (
    costume_clean_sql,
    detect_costume,
    interpret_costume,
)

# One row per price point, mirroring the shape of the real export.
_RETAIL_CSV = (
    "product,category,actual_price,discounted_price,discount_percentage,rating_count\n"
    'Cable,Electronics,"₹1,099",₹399,64%,"24,269"\n'
    'Purifier,Home,"₹59,900","₹14,400",76%,"1,234"\n'
    'Watch,Electronics,"₹19,999","₹1,799",91%,"98,250"\n'
    'Charger,Electronics,"₹1,39,900","₹99,900",29%,"5,012"\n'   # Indian lakh grouping
)


@pytest.fixture(autouse=True)
def _isolate_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")


def _conn():
    return LocalUploadConnection(connection_id="ws")


def _csv(tmp_path, body=_RETAIL_CSV, name="retail.csv"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def _coltype(c, schema, table, col):
    rows = c._duckdb.execute(f'DESCRIBE "{schema}"."{table}"').fetchall()
    return {r[0]: str(r[1]) for r in rows}[col]


# ── The shape gate ────────────────────────────────────────────────────────────
# The gate — not the strip — is what makes the transform safe, so it is tested on
# its own. Everything downstream trusts it.

@pytest.mark.parametrize("value,expected", [
    # Decorated numbers we must recognise.
    ("₹1,099",      1099.0),
    ("₹399",         399.0),
    ("$1,234.56",   1234.56),
    ("64%",           64.0),
    ("24,269",     24269.0),
    ("₹1,39,900", 139900.0),      # Indian lakh grouping — present in the real export
    ("2,50,000",  250000.0),
    ("1,234,567", 1234567.0),
    ("100 ₹",        100.0),      # trailing symbol
    # Text that must be left ALONE. A European decimal comma stripped as a thousands
    # separator silently multiplies the value — '1,5' would become 15.
    ("1,5",         None),
    ("1.234,56",    None),
    ("ID123",       None),
    ("abc",         None),
    ("",            None),
])
def test_shape_gate_admits_decoration_and_rejects_ambiguity(value, expected):
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE t AS SELECT ? AS v", [value])
    hit = detect_costume(con, "t", "v")
    if expected is None:
        # Either rejected outright, or (for undecorated text) never a costume at all.
        assert hit is None or con.execute(
            f"SELECT {costume_clean_sql('v')} FROM t").fetchone()[0] is None
    else:
        assert hit is not None, f"{value!r} should be detected as a decorated number"
        assert con.execute(f"SELECT {costume_clean_sql('v', hit['cast_to'])} FROM t"
                           ).fetchone()[0] == expected


def test_european_decimal_comma_is_never_stripped():
    """The corruption this gate exists to prevent, stated as its own claim."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES ('1,5'),('2,7'),('3,1')) x(v)")
    assert detect_costume(con, "t", "v") is None


def test_identifier_column_is_not_mistaken_for_a_number():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES ('ID123'),('ID456')) x(v)")
    assert detect_costume(con, "t", "v") is None


def test_undecorated_numeric_text_is_left_to_the_ordinary_probe():
    """Bare digits are the plain type-suggestion path's job. The two must stay disjoint,
    or they contend for the same column."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES ('10'),('20'),('30')) x(v)")
    assert detect_costume(con, "t", "v") is None


def test_unit_is_captured_not_discarded():
    """The symbol is a UNIT. Dropping it turns ₹3.4M into an uncaptionable 3400000."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES ('₹1,099'),('₹399')) x(v)")
    assert detect_costume(con, "t", "v")["unit"] == "₹"
    con.execute("CREATE TABLE p AS SELECT * FROM (VALUES ('64%'),('43%')) x(v)")
    assert detect_costume(con, "p", "v")["unit"] == "%"


def test_percent_and_currency_stay_double_grouped_integer_earns_bigint():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE m AS SELECT * FROM (VALUES ('₹1,099'),('₹399')) x(v)")
    assert detect_costume(con, "m", "v")["cast_to"] == "DOUBLE"
    con.execute("CREATE TABLE g AS SELECT * FROM (VALUES ('24,269'),('98,250')) x(v)")
    assert detect_costume(con, "g", "v")["cast_to"] == "BIGINT"


def test_interpret_costume_tolerates_stringified_counts():
    """QueryResult stringifies every cell, so the runtime diagnosis feeds this strings."""
    assert interpret_costume(["4", "4", "4", "0", "0", "₹", "₹1,099"])["unit"] == "₹"
    assert interpret_costume(["0", "0", "0", "0", "0", "NULL", "NULL"]) is None


# ── Layer 1: ingest ───────────────────────────────────────────────────────────

def test_ingest_retypes_decorated_columns(tmp_path):
    c = _conn()
    c.ingest_file(_csv(tmp_path), table_name="retail", schema="main")
    assert _coltype(c, "main", "retail", "actual_price") == "DOUBLE"
    assert _coltype(c, "main", "retail", "discounted_price") == "DOUBLE"
    assert _coltype(c, "main", "retail", "discount_percentage") == "DOUBLE"
    assert _coltype(c, "main", "retail", "rating_count") == "BIGINT"
    assert _coltype(c, "main", "retail", "product") == "VARCHAR"   # untouched


def test_the_metric_that_reported_missing_data_now_computes(tmp_path):
    """The defect, end to end: this aggregate returned NULL over fully-populated data."""
    c = _conn()
    c.ingest_file(_csv(tmp_path), table_name="retail", schema="main")
    total, n = c._duckdb.execute(
        "SELECT SUM(actual_price - discounted_price), COUNT(actual_price) FROM main.retail"
    ).fetchone()
    assert n == 4                                   # every row parsed, none lost
    assert total == pytest.approx(1099 - 399 + 59900 - 14400 + 19999 - 1799 + 139900 - 99900)


def test_transform_survives_reload(tmp_path):
    """The trap: the pinned contract says DOUBLE while the FILE still holds '₹1,099'.
    Honouring the contract alone would TRY_CAST that text to NULL — the ingest would
    look correct and the first restart would silently empty the column."""
    c1 = _conn()
    c1.ingest_file(_csv(tmp_path), table_name="retail", schema="main")
    before = c1._duckdb.execute(
        "SELECT SUM(actual_price), COUNT(actual_price) FROM main.retail").fetchone()

    c2 = _conn()                                    # fresh connector — re-reads the CSV
    after = c2._duckdb.execute(
        "SELECT SUM(actual_price), COUNT(actual_price) FROM main.retail").fetchone()
    assert after == before
    assert after[1] == 4, "reload emptied the column"


def test_parallel_reader_clone_keeps_the_transform(tmp_path):
    """`make_reader` bypasses __init__ to build a thread-safe clone. If it lost the
    transform, a phase running in parallel would read NULLs while the same query ran
    serially returned numbers — a discrepancy that depends on scheduling."""
    c = _conn()
    c.ingest_file(_csv(tmp_path), table_name="retail", schema="main")
    reader = c.make_reader()
    assert _coltype(reader, "main", "retail", "actual_price") == "DOUBLE"
    assert reader._duckdb.execute(
        "SELECT COUNT(actual_price) FROM main.retail").fetchone()[0] == 4


def test_old_sidecar_without_transforms_still_loads(tmp_path):
    """A sidecar written before this change has no `column_transforms` key."""
    c1 = _conn()
    c1.ingest_file(_csv(tmp_path, "a,b\n1,x\n2,y\n", "old.csv"), table_name="old", schema="main")
    sc = c1._upload_dir / "main" / "old.csv.import.json"
    sc.write_text(json.dumps({"table_name": "old", "schema": "main", "column_types": {}}))
    c2 = _conn()
    assert _coltype(c2, "main", "old", "a") == "BIGINT"


def test_transform_is_recorded_in_the_sidecar(tmp_path):
    c = _conn()
    c.ingest_file(_csv(tmp_path), table_name="retail", schema="main")
    cfg = json.loads((c._upload_dir / "main" / "retail.csv.import.json").read_text())
    tf = cfg["column_transforms"]
    assert tf["actual_price"]["cast_to"] == "DOUBLE"
    assert tf["actual_price"]["unit"] == "₹"
    assert "actual_price" in {f["table_name"]: f for f in c.list_files()}["retail"][
        "column_transforms"]


def test_user_override_wins_over_detection(tmp_path):
    """An explicit caller decision is authoritative — detection must not overrule it."""
    c = _conn()
    c.ingest_file(_csv(tmp_path), table_name="retail", schema="main",
                  column_types={"actual_price": "VARCHAR"})
    assert _coltype(c, "main", "retail", "actual_price") == "VARCHAR"
    cfg = json.loads((c._upload_dir / "main" / "retail.csv.import.json").read_text())
    assert "actual_price" not in cfg["column_transforms"]


def test_accepting_the_suggested_numeric_type_does_not_empty_the_column(tmp_path):
    """The regression that matters most: `analyze_file` SUGGESTS DOUBLE for a currency
    column and the import UI offers it as a one-click chip. Sending that suggestion back
    used to skip costume detection, leaving a plain TRY_CAST over '₹1,099' — so the one
    action the product recommends silently emptied the column at ingest, destroying at
    load time what had merely been unreadable before."""
    c = _conn()
    suggested = {col["name"]: col["suggested_type"]
                 for col in c.analyze_file(_csv(tmp_path))["columns"]}
    assert suggested["actual_price"] == "DOUBLE"        # what the UI puts on the chip

    c.ingest_file(_csv(tmp_path), table_name="retail", schema="main",
                  column_types={"actual_price": suggested["actual_price"]})
    total, n = c._duckdb.execute(
        "SELECT SUM(actual_price), COUNT(actual_price) FROM main.retail").fetchone()
    assert n == 4, "accepting the tool's own suggestion emptied the column"
    assert total == pytest.approx(1099 + 59900 + 19999 + 139900)


@pytest.mark.parametrize("requested", ["DOUBLE", "BIGINT", "INTEGER", "DECIMAL"])
def test_any_numeric_override_still_reaches_the_values(tmp_path, requested):
    """Every numeric type a caller can pick means "I want a number here", and stripping
    the decoration is the only way to get one. A real workspace was found with
    `actual_price` pinned INTEGER over '₹1,099' — 1,465 rows, zero non-null — which is
    precisely the report that started this."""
    c = _conn()
    c.ingest_file(_csv(tmp_path), table_name="retail", schema="main",
                  column_types={"actual_price": requested})
    n = c._duckdb.execute("SELECT COUNT(actual_price) FROM main.retail").fetchone()[0]
    assert n == 4, f"override to {requested} emptied the column"


def test_a_quote_in_a_csv_header_cannot_inject_sql(tmp_path):
    """Column names come from the CSV header and never pass through `_safe_ident`
    (which guards only table/schema names). An unescaped one closes the identifier and
    the remainder of the cell executes on the workspace's own DuckDB handle."""
    body = '"b"" , 42 AS ""pwned",v\nkeep,2\n'
    c = _conn()
    c.ingest_file(_csv(tmp_path, body, "inj.csv"), table_name="inj", schema="main")
    declared = [r[0] for r in c._duckdb.execute('DESCRIBE "main"."inj"').fetchall()]
    assert declared[0] == 'b" , 42 AS "pwned'           # one column, quote and all

    schema_text = c.get_schema()                        # this is where samples are read
    # The schema reports exactly the columns the table has — the payload did not become
    # a second column — and the sample shown is that column's OWN value. Unescaped, the
    # emitted SQL was `SELECT "b" , 42 AS "pwned", "v" FROM …`: a different column list
    # than the caller asked for, which either errors out (losing every sample) or, with
    # a payload naming a real sibling column, executes whatever follows the quote.
    assert parse_schema_tables(schema_text)["inj"] == declared
    # Each column is sampled from its OWN values — not from an injected expression.
    assert f'{declared[0]}  VARCHAR  ~ e.g. \'keep\'' in schema_text
    assert "'42'" not in schema_text


def test_non_conforming_values_go_null_rather_than_wrong(tmp_path):
    """Detection accepts a column at 95%, so up to 1 value in 20 need not match the
    shape. A blunt strip turns the accounting negative '(₹1,234)' into +1234 — a sign
    flip inside a column now presented as clean numeric. NULL is the honest outcome."""
    con = duckdb.connect(":memory:")
    vals = ["('₹1,099')"] * 19 + ["('(₹1,234)')"]
    con.execute(f"CREATE TABLE t AS SELECT * FROM (VALUES {','.join(vals)}) x(v)")
    assert detect_costume(con, "t", "v") is not None     # the column is still accepted
    assert con.execute(
        f"SELECT {costume_clean_sql('v')} FROM t WHERE v LIKE '(%'").fetchone()[0] is None
    assert con.execute(
        f"SELECT COUNT({costume_clean_sql('v')}) FROM t").fetchone()[0] == 19


def test_plain_numeric_file_is_unchanged(tmp_path):
    """No costume, no transform — the ordinary path must stay byte-for-byte itself."""
    c = _conn()
    c.ingest_file(_csv(tmp_path, "sku,price,qty\nA,1.5,3\nB,2.0,4\n", "plain.csv"),
                  table_name="plain", schema="main")
    cfg = json.loads((c._upload_dir / "main" / "plain.csv.import.json").read_text())
    assert cfg["column_transforms"] == {}
    assert _coltype(c, "main", "plain", "qty") == "BIGINT"


def test_fractional_column_is_never_suggested_as_bigint(tmp_path):
    """DuckDB's TRY_CAST('4.2' AS BIGINT) SUCCEEDS, truncating to 4 — so probing types in
    order proposed BIGINT for a rating column, and accepting it discarded the decimals.

    The stray '|' is what makes the column land as VARCHAR in the first place (it is why
    the real export's `rating` was text at all); without it DuckDB types the column DOUBLE
    and the suggestion path never runs.
    """
    c = _conn()
    info = c.analyze_file(_csv(tmp_path, "rating\n4.2\n4.0\n3.9\n4.1\n4.3\n4.4\n"
                                         "4.5\n4.6\n3.8\n3.7\n4.7\n4.8\n"
                                         "4.9\n3.6\n3.5\n3.4\n3.3\n3.2\n3.1\n|\n", "r.csv"))
    col = info["columns"][0]
    assert col["detected_type"].upper().startswith("VARCHAR")
    assert col["suggested_type"] == "DOUBLE", "BIGINT here silently truncates 4.2 → 4"


def test_analyze_reports_the_detected_format(tmp_path):
    c = _conn()
    cols = {c_["name"]: c_ for c_ in c.analyze_file(_csv(tmp_path))["columns"]}
    fmt = cols["actual_price"]["detected_format"]
    assert cols["actual_price"]["suggested_type"] == "DOUBLE"
    assert fmt["kind"] == "currency" and fmt["unit"] == "₹"
    assert cols["discount_percentage"]["detected_format"]["kind"] == "percent"
    assert cols["product"]["detected_format"] is None


# ── Layer 2: schema context carries values ────────────────────────────────────

def test_schema_context_shows_sample_values(tmp_path):
    """`actual_price VARCHAR` is indistinguishable from an empty column. Values are what
    let a planner tell a missing price from one written as '₹1,099'."""
    c = _conn()
    c.ingest_file(_csv(tmp_path), table_name="retail", schema="main")
    s = c.get_schema()
    assert "~ e.g." in s
    assert "'Cable'" in s                            # a real value, not just a type
    assert parse_schema_tables(s)["retail"][:3] == ["product", "category", "actual_price"]


def test_samples_never_break_the_column_parsers(tmp_path):
    """A value containing a newline would split the schema line and the tail would parse
    as a bogus column."""
    c = _conn()
    c.ingest_file(_csv(tmp_path, 'note,v\n"line one\nline two",1\n', "n.csv"),
                  table_name="n", schema="main")
    assert parse_schema_tables(c.get_schema())["n"] == ["note", "v"]


def test_strip_value_samples_is_load_bearing():
    """Sample VALUES are data. Left in the text, a product named 'Discount Cable' is
    harvested by the loss-signal scan as a discount COLUMN — one that does not exist,
    handed to the planner as something to aggregate."""
    from aughor.agent.loss_signals import detect_loss_signals
    schema = (
        "TABLE: sales  (3 rows)\n"
        "  product  VARCHAR  ~ e.g. 'Discount Cable', 'Refund Kit'\n"
        "  amount  DOUBLE  ~ e.g. '10.0'\n"
    )
    # Unstripped, the scan invents columns out of product names …
    from aughor.agent.loss_signals import CONTRA_REVENUE_RE
    assert {m.group(1).lower() for m in CONTRA_REVENUE_RE.finditer(schema)}
    # … stripped, it sees only the real columns, so the detector reports no contra signal.
    assert not {m.group(1).lower()
                for m in CONTRA_REVENUE_RE.finditer(strip_value_samples(schema))}
    assert detect_loss_signals("where are we losing money?", schema) is None


def test_format_value_samples_bounds_and_dedupes():
    assert format_value_samples([]) == ""
    assert format_value_samples([None, None]) == ""
    assert format_value_samples(["a", "a", "b"]) == "  ~ e.g. 'a', 'b'"
    long = format_value_samples(["x" * 200])
    assert len(long) < 60 and long.endswith("…'")
    assert "\n" not in format_value_samples(["a\nb"])


# ── Layer 3: the diagnosis ────────────────────────────────────────────────────

def test_diagnosis_names_the_column_and_the_format(tmp_path):
    """When a metric still comes back all-NULL, the report must not call present data
    missing — 'go find it' and 'parse it' are opposite instructions."""
    c = _conn()
    # Ingested with the price pinned as text, standing in for a source we only read.
    c.ingest_file(_csv(tmp_path), table_name="retail", schema="main",
                  column_types={"actual_price": "VARCHAR"})
    why = unparsed_numeric_diagnosis(
        "SELECT SUM(TRY_CAST(actual_price AS DOUBLE)) FROM main.retail", c)
    assert why and "actual_price" in why
    assert "currency" in why and "needs parsing" in why
    assert "₹" in why                                # quotes a real value back


def test_diagnosis_is_silent_when_data_is_genuinely_absent(tmp_path):
    """The generic advisory is CORRECT for an empty column and must survive."""
    c = _conn()
    c.ingest_file(_csv(tmp_path, "product,actual_price\nA,\nB,\n", "empty.csv"),
                  table_name="empty", schema="main")
    assert unparsed_numeric_diagnosis(
        "SELECT SUM(TRY_CAST(actual_price AS DOUBLE)) FROM main.empty", c) is None


def test_diagnosis_degrades_to_todays_wording_without_a_connection():
    assert unparsed_numeric_diagnosis("SELECT SUM(x) FROM t", None) is None
    ok, why = verify_insight([["NULL"], ["NULL"]], "", "SELECT SUM(x) FROM t")
    assert not ok and "no variation to rank" in why


def test_gate_prefers_the_root_cause_over_the_symptom(tmp_path):
    """The gate keeps rejecting the finding either way; only the REASON changes."""
    c = _conn()
    c.ingest_file(_csv(tmp_path), table_name="retail", schema="main",
                  column_types={"actual_price": "VARCHAR"})
    sql = "SELECT SUM(TRY_CAST(actual_price AS DOUBLE)) AS total FROM main.retail"
    ok, why = verify_insight([["NULL"], ["NULL"]], "", sql, diagnose_conn=c)
    assert not ok
    assert "actual_price" in why and "no variation to rank" not in why


# ── Leakage direction ─────────────────────────────────────────────────────────
# A rate labelled "leakage" must rise as money is lost. Bound to net/gross it measures
# the opposite, and the whole report inverts with it.

@pytest.mark.parametrize("label,sql,expect_fix", [
    # The live defect: retention wearing a leakage name.
    ("Leakage Rate", "SUM(discounted_price) / SUM(actual_price)", True),
    ("discount leakage rate", "SUM(net_amount) / NULLIF(SUM(gross_amount), 0)", True),
    ("Leakage Rate", "SUM(a.final_price) / SUM(a.list_price)", True),
    # Already correct — must NOT be touched.
    ("Leakage Rate", "SUM(actual_price - discounted_price) / SUM(actual_price)", False),
    ("Leakage Rate", "SUM(refund_amount) / SUM(gross_revenue)", False),
    # Not a leakage claim at all.
    ("Average order value", "SUM(discounted_price) / SUM(actual_price)", False),
    # Ambiguous shapes are left alone.
    ("Leakage Rate", "SUM(discounted_price) / SUM(actual_price) / SUM(x)", False),
    ("Leakage Rate", "AVG(discounted_price)", False),
])
def test_leakage_direction_fix(label, sql, expect_fix):
    from aughor.agent.loss_signals import leakage_direction_fix
    got = leakage_direction_fix(label, sql)
    assert (got is not None) is expect_fix, f"{label!r} / {sql!r}"


def test_corrected_leakage_matches_the_real_loss(tmp_path):
    """The corrected formula must reproduce the discount actually in the data — and rank
    the deepest-discounted segment as the WORST, which is the reading that inverted."""
    from aughor.agent.loss_signals import leakage_direction_fix
    fixed, note = leakage_direction_fix("Leakage Rate",
                                        "SUM(discounted_price) / SUM(actual_price)")
    assert "retained" in note.lower() or "RETAINED" in note
    c = _conn()
    c.ingest_file(_csv(tmp_path), table_name="retail", schema="main")
    rate = c._duckdb.execute(f"SELECT {fixed} FROM main.retail").fetchone()[0]
    gross = 1099 + 59900 + 19999 + 139900
    net = 399 + 14400 + 1799 + 99900
    assert rate == pytest.approx((gross - net) / gross)
    # The inversion, stated directly: the corrected rate is the COMPLEMENT of what the
    # original formula returned. Both are valid numbers; only one is called "leakage".
    retained = c._duckdb.execute(
        "SELECT SUM(discounted_price)/SUM(actual_price) FROM main.retail").fetchone()[0]
    assert rate == pytest.approx(1 - retained)

    # …and the deepest-discounted product now ranks last, not first.
    worst = c._duckdb.execute(
        f"SELECT product FROM main.retail GROUP BY product ORDER BY {fixed} DESC LIMIT 1"
    ).fetchone()[0]
    assert worst == "Watch"         # ₹19,999 → ₹1,799: 91% off, the deepest in the fixture


@pytest.mark.parametrize("label,worse_high", [
    ("discount leakage rate", True),
    ("refund rate", True),
    ("customer churn rate", True),
    ("cost per order", True),
    ("net revenue", False),
    ("gross margin %", False),
    ("retention rate", False),
    ("average order value", False),
])
def test_metric_polarity_decides_which_tail_matters(label, worse_high):
    """The cross-section ranks ascending by default — right for revenue, backwards for a
    loss rate, where the worst segment is the LARGEST. A capped ascending scan of leakage
    returns the healthiest slice of the business, and the report then cannot locate the
    loss it was asked about."""
    from aughor.agent.loss_signals import higher_is_worse
    assert higher_is_worse(label) is worse_high


@pytest.mark.parametrize("sql,expected", [
    ("SUM(actual_price - discounted_price) / NULLIF(SUM(actual_price), 0) * 100",
     "SUM(actual_price - discounted_price)"),
    ("100.0 * SUM(actual_price - discounted_price) / NULLIF(SUM(actual_price), 0)",
     "SUM(actual_price - discounted_price)"),
    ("SUM(refund_amount) / SUM(gross_revenue)", "SUM(refund_amount)"),
    ("AVG(x)", None),                                  # not a ratio
    ("SUM(a)/SUM(b)/SUM(c)", None),                    # ambiguous
    ("(a - b) / c", None),                             # numerator not an aggregate
])
def test_loss_magnitude_extracts_the_money_behind_the_rate(sql, expected):
    """A rate says how deeply, never how much. 90% leakage on ₹2M and on ₹900 rank the
    same by rate; only the magnitude separates them."""
    from aughor.agent.loss_signals import loss_magnitude_sql
    assert loss_magnitude_sql(sql) == expected


def test_loss_magnitude_runs_and_equals_the_real_money(tmp_path):
    from aughor.agent.loss_signals import loss_magnitude_sql
    expr = loss_magnitude_sql(
        "SUM(actual_price - discounted_price) / NULLIF(SUM(actual_price), 0) * 100")
    c = _conn()
    c.ingest_file(_csv(tmp_path), table_name="retail", schema="main")
    total = c._duckdb.execute(f"SELECT {expr} FROM main.retail").fetchone()[0]
    assert total == pytest.approx((1099 - 399) + (59900 - 14400)
                                  + (19999 - 1799) + (139900 - 99900))
