"""AT-4/6/7 wired — the profiler resolves a concept from live rows, and something reads it.

`test_concept.py` proves the CONTRACT (two layers agree, or nothing). This file proves the
contract is connected: that the profiler builds real witnesses from a real table, that a
concept only appears when two layers agree, and that three consumers change their answer
because of it. A resolved concept nothing reads would be a receipt, and the program the
roadmap describes is explicitly not a receipt system.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from aughor.agent.relationship import plan_relationship
from aughor.db.connection import DuckDBConnection
from aughor.tools.concept import concept_of
from aughor.tools.profiler import (
    _name_witnesses,
    _semantic_type,
    build_column_profiles,
    render_profile_annotations,
    profile_connection,
)


def _conn(ddl: str, rows: str):
    c = DuckDBConnection.__new__(DuckDBConnection)
    c._path = Path(":memory:")
    c._conn = duckdb.connect(":memory:")
    c._connection_id = ""            # no query history in a unit test
    c._schema_name = None
    c._conn.execute(ddl)
    c._conn.execute(rows)
    return c


# ── a coordinate, typed by two layers, on a table that says nothing ──────────

_GEO_DDL = """
CREATE TABLE places (
  latitude DOUBLE, longitude DOUBLE, delay_days INTEGER, city VARCHAR
)
"""


def _geo_rows(n: int = 120) -> str:
    vals = ",".join(
        f"({18.25 + i * 0.0137:.8f}, {-66.03 - i * 0.9137:.8f}, {i % 7}, 'c{i % 9}')"
        for i in range(n)
    )
    return f"INSERT INTO places VALUES {vals}"


_GEO_COLS = [("latitude", "DOUBLE"), ("longitude", "DOUBLE"),
             ("delay_days", "INTEGER"), ("city", "VARCHAR")]


def test_a_numeric_latitude_stops_being_a_key():
    """The defect in the roadmap's own words: `_GEO_CODE_PATTERN` says a latitude is a
    key, so the one column that could answer 'where is this customer' was excluded from
    every numeric path. It takes two layers to overrule the pattern — name AND partner."""
    assert _semantic_type("latitude", "DOUBLE", False, 500, 1000, 0.0, (-90.0, 90.0)) == "key"
    profs = build_column_profiles(_conn(_GEO_DDL, _geo_rows()), "places", _GEO_COLS, set(), 120)
    by_col = {p.column: p for p in profs}
    assert concept_of(by_col["latitude"].concept, by_col["latitude"].concept_confidence) == "geo.latitude"
    assert by_col["latitude"].semantic_type == "measure"
    assert by_col["longitude"].semantic_type == "measure"


def test_the_evidence_names_both_layers_so_a_human_can_check():
    profs = build_column_profiles(_conn(_GEO_DDL, _geo_rows()), "places", _GEO_COLS, set(), 120)
    ev = {p.column: p.concept_evidence for p in profs}["latitude"]
    assert any(e.startswith("name: ") for e in ev)
    assert any(e.startswith("pair: ") for e in ev)
    assert any("decimal places" in e for e in ev)      # the number, not just the verdict


_NO_PARTNER_DDL = "CREATE TABLE t (latitude DOUBLE, score DOUBLE)"


def _no_partner_rows(n: int = 120) -> str:
    # `score` is deliberately coordinate-SHAPED: inside ±90, eight decimals, high
    # cardinality. Only its name differs.
    vals = ",".join(f"({18.25 + i * 0.0137:.8f}, {40.5 + i * 0.0231:.8f})" for i in range(n))
    return f"INSERT INTO t VALUES {vals}"


_NO_PARTNER_COLS = [("latitude", "DOUBLE"), ("score", "DOUBLE")]


def test_a_latitude_no_longer_needs_a_partner_once_its_VALUES_vouch_for_it():
    """This is what AT-5 bought. Before the value layer, `latitude` alone was a name with
    nothing to agree with it, so it stayed a hint unless a longitude sat beside it. Now its
    own values are the second witness — and a table is allowed to store only a latitude."""
    profs = build_column_profiles(_conn(_NO_PARTNER_DDL, _no_partner_rows()), "t",
                                  _NO_PARTNER_COLS, set(), 120)
    lat = {p.column: p for p in profs}["latitude"]
    assert concept_of(lat.concept, lat.concept_confidence) == "geo.latitude"
    assert lat.semantic_type == "measure"
    layers = {e.split(":", 1)[0] for e in lat.concept_evidence}
    assert {"name", "value"} <= layers, lat.concept_evidence


def test_a_coordinate_SHAPE_that_nothing_else_agrees_with_stays_a_hint():
    """AT-0 measured a 60% false-positive rate for the bounded-range test alone, and this
    is that finding still holding: `score` has exactly the values of a latitude and nothing
    seconds it, so it types nothing and moves nothing."""
    profs = build_column_profiles(_conn(_NO_PARTNER_DDL, _no_partner_rows()), "t",
                                  _NO_PARTNER_COLS, set(), 120)
    score = {p.column: p for p in profs}["score"]
    assert score.concept == "geo.latitude"              # kept — it is real information
    assert concept_of(score.concept, score.concept_confidence) == ""
    assert score.semantic_type == "measure"             # what it was before AT-5 touched it


# ── the flag that is a stored comparison ─────────────────────────────────────

_FLAG_DDL = "CREATE TABLE ship (real_days INTEGER, sched_days INTEGER, late_risk INTEGER)"


def _flag_rows(n: int = 150) -> str:
    vals = ",".join(f"({i % 7}, {i % 4}, {1 if (i % 7) > (i % 4) else 0})" for i in range(n))
    return f"INSERT INTO ship VALUES {vals}"


_FLAG_COLS = [("real_days", "INTEGER"), ("sched_days", "INTEGER"), ("late_risk", "INTEGER")]


def test_the_magnitude_behind_a_flag_becomes_a_fact_on_the_table():
    """Six consecutive runs of one question had to invent this subtraction from a prompt
    paragraph. It is a measured property of the table."""
    conn = _conn(_FLAG_DDL, _flag_rows())
    tps, cps = profile_connection(conn, ["ship"], {})
    notes = tps["ship"].derived_quantities
    assert notes, "a table whose flag is a comparison implies a magnitude"
    assert any('"real_days" - "sched_days"' in n for n in notes)
    flag = cps["ship.late_risk"]
    assert concept_of(flag.concept, flag.concept_confidence) == "flag.binary"
    # The concept answers WHAT the column is; the comparison is WHY, and it survives in
    # the evidence rather than becoming a second concept the layers then split their vote
    # between.
    assert any("sched_days" in e for e in flag.concept_evidence), flag.concept_evidence


def test_the_derived_quantity_reaches_the_rendered_profile():
    conn = _conn(_FLAG_DDL, _flag_rows())
    text = render_profile_annotations(*profile_connection(conn, ["ship"], {}))
    assert "DERIVED QUANTITIES" in text
    assert '"real_days" - "sched_days"' in text


def test_a_confident_concept_renders_with_its_prohibition_not_just_its_name():
    """AT-7: the label alone is a receipt. `never SUM` is the part that changes an answer."""
    conn = _conn(_GEO_DDL, _geo_rows())
    text = render_profile_annotations(*profile_connection(conn, ["places"], {}))
    assert "IS geo.latitude" in text
    assert "never SUM, AVG" in text


def test_a_hint_is_invisible_in_the_prompt():
    """Showing 'possibly a latitude (0.49)' in a prompt is how a guess becomes a fact one
    paraphrase later. `score` holds coordinate-shaped values on one layer only."""
    text = render_profile_annotations(
        *profile_connection(_conn(_NO_PARTNER_DDL, _no_partner_rows()), ["t"], {}))
    assert "score" in text
    assert "score" not in text.split("IS geo.latitude")[0].splitlines()[-1]


# ── the name layer on its own ────────────────────────────────────────────────

def test_a_space_separated_id_is_recognised_as_an_identifier():
    """AT-0's live defect: `Customer Id` matched neither `_id$` nor `customerId`, so seven
    identifier columns in data_co profiled as free text at 9,754 distinct values."""
    assert any(w.concept == "key.identifier" for w in _name_witnesses("Customer Id", "VARCHAR"))
    assert any(w.concept == "key.identifier" for w in _name_witnesses("Product Card Id", "VARCHAR"))
    assert _semantic_type("Customer Id", "VARCHAR", False, 9754, 180519, 0.0, None) == "key"
    # …and the shapes that already worked still do
    assert _semantic_type("customer_id", "VARCHAR", False, 10, 100, 0.0, None) == "key"
    assert _semantic_type("customerId", "VARCHAR", False, 10, 100, 0.0, None) == "key"


def test_an_image_is_not_a_duration():
    """`_DURATION_PATTERN` is unanchored, so `Product Image` ends in `age`. Harmless where
    it already lived (numeric measures only); not harmless in a rule offered every column."""
    for innocent in ("Product Image", "average", "package", "mileage", "usage"):
        assert not any(w.concept == "duration.days" for w in _name_witnesses(innocent, "VARCHAR")), innocent
    # …and `\b` would have been the wrong fix: an underscore is a word character, so
    # `\bdays$` does not match `lead_time_days` at all.
    for real in ("lead_time_days", "days", "shipping_delay", "Days"):
        assert any(w.concept == "duration.days" for w in _name_witnesses(real, "INTEGER")), real


def test_two_name_patterns_agreeing_is_still_one_witness():
    """`Customer Zipcode` is named like a place AND like an identifier. Both are the name
    layer, and a layer speaks once — so neither concept is acted on."""
    from aughor.tools.concept import resolve_concept
    verdict = resolve_concept(_name_witnesses("Customer Zip Code", "VARCHAR"))
    assert concept_of(verdict.concept, verdict.confidence) == ""


# ── the relationship consumer ────────────────────────────────────────────────

def _runner(rows):
    return lambda sql: rows


def test_a_zipcode_is_not_correlated_with_a_delay():
    """It casts, it correlates, it returns a coefficient and a p-value — and zip 90210 is
    not larger than zip 90209, so every part of that answer is well-formed and meaningless."""
    plan = plan_relationship(
        table="orders", left_column="delay_days", right_column="zip",
        left_label="delay", right_label="zip",
        col_types={"delay_days": "INTEGER", "zip": "INTEGER"},
        run=_runner([(100, 100)]),
        col_concepts={"zip": "key.identifier"},
    )
    assert plan.kind == "numeric_by_category"       # compared ACROSS zips, not against them
    assert "CORR" not in plan.sql


def test_without_a_concept_the_planner_behaves_exactly_as_before():
    """AT-7 must be inert where it has nothing to say — that is what makes it safe to add
    to a path six runs already depend on."""
    kwargs = dict(
        table="orders", left_column="delay_days", right_column="zip",
        left_label="delay", right_label="zip",
        col_types={"delay_days": "INTEGER", "zip": "INTEGER"},
        run=_runner([(100, 100)]),
    )
    assert plan_relationship(**kwargs).kind == "numeric_pair"
    assert plan_relationship(**kwargs, col_concepts={}).kind == "numeric_pair"
    assert plan_relationship(**kwargs, col_concepts={"zip": "count.quantity"}).kind == "numeric_pair"


def test_a_coordinate_is_still_allowed_on_a_side():
    """`never SUM/AVG` is not `not a number`. Refusing the correlation here would refuse
    the question the六 runs were about."""
    plan = plan_relationship(
        table="places", left_column="delay_days", right_column="latitude",
        left_label="delay", right_label="latitude",
        col_types={"delay_days": "INTEGER", "latitude": "DOUBLE"},
        run=_runner([(100, 100)]),
        col_concepts={"latitude": "geo.latitude"},
    )
    assert plan.kind == "numeric_pair"
    assert "CORR" in plan.sql


# ── the declared layer ───────────────────────────────────────────────────────

def test_a_human_declaration_wins_over_every_computed_layer(tmp_path, monkeypatch):
    from aughor.ontology.column_config import ColumnFlags, save_table_config

    monkeypatch.setenv("AUGHOR_COLUMN_CONFIG_ROOT", str(tmp_path))
    save_table_config("workspace", "default", "places", {
        "latitude": ColumnFlags(concept="money.amount", source="human"),
    })
    conn = _conn(_GEO_DDL, _geo_rows())
    conn._connection_id = "workspace"
    conn._schema_name = "default"
    _, cps = profile_connection(conn, ["places"], {})
    lat = cps["places.latitude"]
    assert lat.concept == "money.amount"
    assert lat.concept_confidence == 1.0
    assert lat.concept_evidence[0].startswith("declared: ")


def test_a_declaration_survives_a_yaml_round_trip(tmp_path, monkeypatch):
    from aughor.ontology.column_config import ColumnFlags, load_table_config, save_table_config

    monkeypatch.setenv("AUGHOR_COLUMN_CONFIG_ROOT", str(tmp_path))
    save_table_config("c", "s", "t", {"col": ColumnFlags(concept="geo.latitude", source="human")})
    assert load_table_config("c", "s", "t")["col"].concept == "geo.latitude"
    # and a config written before AT-4 reads back as "no declaration", not as a crash
    assert ColumnFlags().concept == ""


# ── the gap no concept can close ─────────────────────────────────────────────

def test_a_numeric_zipcode_is_not_correlated_even_though_no_concept_reaches_it():
    """`Customer Zipcode` holds `725` and `95125` — three- and five-digit numbers with no
    shape distinguishing them from any small integer, so no value witness can second the
    name and the column stays a HINT forever. It is also exactly the column that must never
    be correlated. The profiler has always typed it `key` from its name; that looser
    contract is the right one to read for the narrow question 'is this an identifier'."""
    plan = plan_relationship(
        table="orders", left_column="delay_days", right_column="zipcode",
        left_label="delay", right_label="zipcode",
        col_types={"delay_days": "INTEGER", "zipcode": "BIGINT"},
        run=_runner([(100, 100)]),
        col_concepts={},                                  # nothing confident — the real case
        col_semantic_types={"zipcode": "key"},
    )
    assert plan.kind == "numeric_by_category"
    assert "CORR" not in plan.sql


def test_a_confident_concept_still_overrules_the_semantic_type():
    """`_GEO_CODE_PATTERN` calls a latitude a key. Two agreeing layers say it is a
    coordinate, and a coordinate on a side of a correlation is the question the six runs
    were about — so the concept decides, in the permissive direction too."""
    plan = plan_relationship(
        table="places", left_column="delay_days", right_column="latitude",
        left_label="delay", right_label="latitude",
        col_types={"delay_days": "INTEGER", "latitude": "DOUBLE"},
        run=_runner([(100, 100)]),
        col_concepts={"latitude": "geo.latitude"},
        col_semantic_types={"latitude": "key"},
    )
    assert plan.kind == "numeric_pair"
    assert "CORR" in plan.sql


def test_a_measure_semantic_type_changes_nothing():
    plan = plan_relationship(
        table="orders", left_column="delay_days", right_column="revenue",
        left_label="delay", right_label="revenue",
        col_types={"delay_days": "INTEGER", "revenue": "DOUBLE"},
        run=_runner([(100, 100)]),
        col_semantic_types={"delay_days": "measure", "revenue": "measure"},
    )
    assert plan.kind == "numeric_pair"


def test_semantic_types_are_read_back_from_the_cache_for_the_deep_path():
    """The accessor the relationship scan actually calls — query-free, like load_concepts."""
    from aughor.tools.profile_cache import load_semantic_types

    conn = _conn(_GEO_DDL, _geo_rows())
    conn._connection_id = "sem-type-probe"
    profile_connection(conn, ["places"], {})
    from aughor.tools.profile_cache import save_profiles
    tps, cps = profile_connection(conn, ["places"], {})
    save_profiles("sem-type-probe", "fp", tps, cps)
    got = load_semantic_types("sem-type-probe")
    assert got[("places", "latitude")] == "measure"
    assert got[("places", "city")] == "dimension"


def test_the_newest_cached_fingerprint_wins():
    """One connection holds many fingerprints — fifteen for `workspace` — and the store
    keeps them newest-LAST. Reading with `setdefault` served whichever came first, so a
    profile rebuilt seconds ago was shadowed by one from a schema version that no longer
    exists. The postal fix landed and read as not working because of exactly this."""
    from aughor.tools.profile_cache import _store, load_concepts, load_semantic_types

    old = {"columns": {"t.zip": {"table": "t", "column": "zip", "semantic_type": "dimension",
                                 "concept": "geo.region", "concept_confidence": 0.9}},
           "tables": {}}
    new = {"columns": {"t.zip": {"table": "t", "column": "zip", "semantic_type": "key",
                                 "concept": "geo.postal_code", "concept_confidence": 0.9}},
           "tables": {}}
    _store.put("fp-order-probe:oldfp", old)
    _store.put("fp-order-probe:newfp", new)
    assert load_semantic_types("fp-order-probe")[("t", "zip")] == "key"
    assert load_concepts("fp-order-probe")[("t", "zip")] == "geo.postal_code"


# ── the percent scale ────────────────────────────────────────────────────────

_PCT_DDL = "CREATE TABLE m (discount_rate DOUBLE, failure_rate_pct DOUBLE, csat INTEGER, quantity INTEGER)"


def _pct_rows(n: int = 120) -> str:
    vals = ",".join(
        f"({round(i / (n * 4), 4)}, {round(7 + 22 * i / n, 2)}, {1 + i % 5}, {1 + i % 14})"
        for i in range(n))
    return f"INSERT INTO m VALUES {vals}"


_PCT_COLS = [("discount_rate", "DOUBLE"), ("failure_rate_pct", "DOUBLE"),
             ("csat", "INTEGER"), ("quantity", "INTEGER")]


def test_the_percent_SCALE_is_resolved_on_both_sides_of_one():
    """AT-0's Q6 ambiguity, answered. `0.81` and `81` can be the same measurement and
    reading one as the other is off by a hundred. The 0–1 case needs no name; the 0–100 case
    needs a narrow one, because the range there is shared with every small count."""
    profs = {p.column: p for p in
             build_column_profiles(_conn(_PCT_DDL, _pct_rows()), "m", _PCT_COLS, set(), 120)}

    frac = profs["discount_rate"]
    assert concept_of(frac.concept, frac.concept_confidence) == "percent.proportion"
    assert frac.unit == "percent_fraction"

    whole = profs["failure_rate_pct"]
    assert whole.unit == "percent_whole"
    assert "do NOT multiply by 100" in (whole.value_interpretation or "")


def test_a_rate_that_is_not_a_percentage_gets_no_whole_scale():
    """The narrowness that makes the 0–100 branch safe: only `percent` and `pct` assert a
    scale. `heart_rate` 40–100 is a rate and is not a percentage, and multiplying it by a
    hundred would be this fix causing the error it exists to prevent."""
    from aughor.tools.profiler import _value_interpretation

    for loose in ("heart_rate", "exchange_rate", "win_ratio", "market_share"):
        assert _value_interpretation(loose, (40.0, 100.0))[1] != "percent_whole", loose
    for strict in ("failure_rate_pct", "discount_percent", "margin_pct"):
        assert _value_interpretation(strict, (7.0, 29.0))[1] == "percent_whole", strict
    # …and in 0–1 the range is unambiguous, so every one of them resolves without a name
    for any_name in ("heart_rate", "failure_rate_pct", "anything_at_all"):
        assert _value_interpretation(any_name, (0.0, 0.8))[1] == "percent_fraction"


def test_the_0_to_100_branch_never_fires_without_a_confirmed_concept():
    """The 82 false positives. `csat` (1–5) and `quantity` (1–14) sit in the same band and
    no name calls them proportions, so nothing claims them."""
    profs = {p.column: p for p in
             build_column_profiles(_conn(_PCT_DDL, _pct_rows()), "m", _PCT_COLS, set(), 120)}
    for innocent in ("csat", "quantity"):
        assert profs[innocent].unit != "percent_whole", innocent
        assert concept_of(profs[innocent].concept, profs[innocent].concept_confidence) != "percent.proportion"


def test_a_percent_column_outside_both_bands_gets_no_scale():
    from aughor.tools.profiler import _value_interpretation

    assert _value_interpretation("x_pct", (0.0, 5000.0), concept="percent.proportion") == (None, None)
    # a confident concept is accepted as the same evidence as the narrow name token
    assert _value_interpretation("odd_name", (0.0, 100.0),
                                 concept="percent.proportion")[1] == "percent_whole"


def test_an_ip_column_can_now_reach_a_second_witness():
    """`net.ip_address` was the one grammar concept with no name rule, so it could only
    ever be a hint however clearly the values read as addresses."""
    from aughor.tools.concept import resolve_concept
    from aughor.tools.shape import value_witnesses

    assert any(w.concept == "net.ip_address" for w in _name_witnesses("client_ip", "VARCHAR"))
    values = [f"10.0.{i // 256}.{i % 256}" for i in range(120)]
    verdict = resolve_concept(_name_witnesses("client_ip", "VARCHAR") + value_witnesses(values))
    assert concept_of(verdict.concept, verdict.confidence) == "net.ip_address"


def test_the_ip_rule_does_not_match_every_word_containing_ip():
    """The separators are load-bearing on a token this short — and `zip` in particular is a
    postal code three rules further up."""
    for innocent in ("ship", "zip", "Customer Zipcode", "equipment", "recipient",
                     "tooltip", "shipping_mode", "Shipping Mode", "clip_id", "description"):
        assert not any(w.concept == "net.ip_address"
                       for w in _name_witnesses(innocent, "VARCHAR")), innocent
    for real in ("ip", "ip_address", "client_ip", "remote_addr", "ipv4", "IP Address"):
        assert any(w.concept == "net.ip_address"
                   for w in _name_witnesses(real, "VARCHAR")), real


# ── the bare-name collision ──────────────────────────────────────────────────

def test_two_tables_sharing_a_bare_name_profile_separately():
    """`luxexperience.customers` (7 columns, 35,136 rows) and `main.customers` (5 columns,
    59,430 rows) are different tables. Flattened to `customers`, the profiler ran
    `DESCRIBE customers`, got whichever the search path resolved, profiled it twice, and
    never profiled the other at all — one table's profile silently became another's."""
    c = DuckDBConnection.__new__(DuckDBConnection)
    c._path = Path(":memory:")
    c._conn = duckdb.connect(":memory:")
    c._connection_id = ""
    c._schema_name = None
    c._conn.execute("CREATE SCHEMA a; CREATE SCHEMA b")
    c._conn.execute("CREATE TABLE a.customers (id INT, region VARCHAR, tier VARCHAR)")
    c._conn.execute("CREATE TABLE b.customers (id INT, country VARCHAR)")
    c._conn.execute("INSERT INTO a.customers SELECT i, 'r'||(i%4), 't'||(i%3) FROM range(200) t(i)")
    c._conn.execute("INSERT INTO b.customers SELECT i, 'US' FROM range(50) t(i)")

    tps, cps = profile_connection(c, ["a.customers", "b.customers"], {})

    assert set(tps) == {"a.customers", "b.customers"}
    assert tps["a.customers"].row_count == 200
    assert tps["b.customers"].row_count == 50
    # …and the column profiles do not overwrite each other
    assert {p.column for p in cps.values() if p.table == "a.customers"} == {"id", "region", "tier"}
    assert {p.column for p in cps.values() if p.table == "b.customers"} == {"id", "country"}


def test_quirk_detection_survives_a_qualified_table_name():
    """`detect_schema_quirks` read the table out of the KEY with `split(".", 1)`, which on
    `schema.table.column` returns the SCHEMA — a lookup that silently matches nothing."""
    from aughor.tools.profiler import detect_schema_quirks

    c = DuckDBConnection.__new__(DuckDBConnection)
    c._path = Path(":memory:")
    c._conn = duckdb.connect(":memory:")
    c._connection_id = ""
    c._schema_name = None
    c._conn.execute("CREATE SCHEMA s")
    c._conn.execute("CREATE TABLE s.orders (order_id INT, customer_id INT, amount DOUBLE)")
    c._conn.execute(
        "INSERT INTO s.orders SELECT i, i % 40, i * 1.5 FROM range(300) t(i)")
    tps, cps = profile_connection(c, ["s.orders"], {})
    # the point is that it runs over a qualified key and can see the columns at all
    detect_schema_quirks(tps, cps)
    lookup = {(p.table, p.column) for p in cps.values()}
    assert ("s.orders", "order_id") in lookup
    assert ("s.orders", "customer_id") in lookup
