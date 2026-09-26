"""A3 — the report beside the approval ask.

The specimen these tests are shaped around was measured live on 2026-09-20 against theLook
(`8233e4fd`, BigQuery): metric ``return_rate``, ``status: draft``, ``version: 0``, formula
``SUM(CASE WHEN returned_at IS NOT NULL THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0)``,
``tables: []``, ``filters: []``, ``dimensions: []``, with ``wrong_usage_examples`` saying a
population still containing cancelled lines reads wrong. ``GET /metrics/return_rate/value``
answered ``400 Unrecognized name: returned_at`` — because with ``tables: []`` the query
`metrics.value_query` builds has no FROM at all. Its audit trail was two delete events, both
carrying ``sql: null``, so it has no predecessor and never had one.

Three properties are pinned here that a green tick could otherwise fake:

* a claim that could not be checked must SAY so — `UNAVAILABLE` and `CLEAN` must never collapse;
* the dropped-filter finding is proven by a NUMBER from a real table, not by asserting that the
  classifier said what the classifier was written to say;
* nothing in this feature's import graph can reach a function that holds a send.
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.db.connection import DuckDBConnection
from aughor.semantic.definition_report import (
    CLEAN, DEFECT, FINDINGS, FINGERPRINTED, NOT_APPLICABLE, PINNED, UNAVAILABLE,
    UNPINNABLE, Claim, Finding, Population, build_report, declaration_claim, execution_claim,
    population_of, predecessor_claim, segments_claim, _is_approved,
)
from aughor.semantic.metrics import MetricDefinition, value_query

# The specimen, transcribed from the live reading above. Kept as one object so a test that
# needs a variant derives it with `model_copy`, rather than hand-writing a shape that happens
# to satisfy the expectation sitting next to it.
RETURN_RATE = MetricDefinition(
    name="return_rate", label="Return rate",
    sql="SUM(CASE WHEN returned_at IS NOT NULL THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0)",
    tables=[], filters=[], dimensions=[],
    wrong_usage_examples=["Reading this over a population that still contains cancelled lines"],
    connection="8233e4fd", status="draft", version=0,
)


@pytest.fixture(autouse=True)
def isolated_metrics(tmp_path, monkeypatch):
    """Give THIS file its own metrics registry.

    `tests/conftest.py` points `AUGHOR_METRICS_PATH` at a throwaway temp COPY of
    `data/metrics.json` — which keeps writes away from live data, but the copy is
    SESSION-scoped and every test in the run shares it. Two tests here call `save_metric`
    through the real route, and without this fixture those rows stayed visible to every later
    file: `test_metric_dedup.py::test_raw_read_preserves_duplicates_for_the_management_ui`
    passed alone and failed when run after this one. Autouse rather than opt-in, because the
    next test added here will write too and the leak is silent until some unrelated file counts
    rows and gets a different answer.
    """
    path = tmp_path / "metrics.json"
    path.write_text("[]")
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(path))
    return path


@pytest.fixture
def items(tmp_path):
    """Five rows: two returned, two cancelled (never returned), one plain.

    The cancelled rows are what make a dropped filter VISIBLE as a number — 2/5 unfiltered
    against 2/3 filtered — so the test does not have to take the classifier's word for it.
    """
    path = tmp_path / "items.duckdb"
    w = duckdb.connect(str(path))
    try:
        w.execute("""
            CREATE TABLE order_items AS SELECT * FROM (VALUES
                (1, TIMESTAMP '2026-01-05 00:00:00', 'Complete'),
                (2, TIMESTAMP '2026-01-06 00:00:00', 'Complete'),
                (3, NULL,                            'Complete'),
                (4, NULL,                            'Cancelled'),
                (5, NULL,                            'Cancelled')
            ) AS t(id, returned_at, status)
        """)
    finally:
        w.close()
    db = DuckDBConnection(str(path))
    yield db
    db.close()


# ── The typed verdicts cannot be silently empty ───────────────────────────────

def test_an_unavailable_claim_must_say_why():
    """`X or {}` in another spelling: "checked, clean" and "could not check" must not be one
    value. The report's whole purpose is telling an approver which of those they are looking at."""
    with pytest.raises(ValueError, match="could not be checked"):
        Claim(UNAVAILABLE, "")
    assert Claim(UNAVAILABLE, "the warehouse refused the query").outcome == UNAVAILABLE


def test_a_findings_claim_must_carry_findings():
    with pytest.raises(ValueError, match="at least one finding"):
        Claim(FINDINGS, "three things need your eye")


def test_a_finding_must_carry_its_evidence():
    """A finding a reader cannot check is one they must take on faith."""
    with pytest.raises(ValueError, match="no evidence"):
        Finding("x", DEFECT, "something is wrong", "   ")


def test_an_unpinnable_population_must_carry_its_reason():
    """The field that would otherwise be permanently null on BigQuery and read as 'nothing moved'."""
    with pytest.raises(ValueError, match="reason it cannot be pinned"):
        Population(UNPINNABLE)
    with pytest.raises(ValueError, match="must carry its token"):
        Population(FINGERPRINTED)


def test_fingerprinted_is_not_reproducible():
    """A fingerprint tells you AFTERWARDS that something moved. Only PINNED can be re-taken,
    and conflating them is what would let the report promise reproducibility it does not have."""
    assert Population(PINNED, token="dl:7").reproducible is True
    assert Population(FINGERPRINTED, token="fp:abc").reproducible is False
    assert Population(UNPINNABLE, reason="bigquery has no seam here").reproducible is False


# ── The specimen's three findings ─────────────────────────────────────────────

def test_the_specimen_is_reported_as_undeclared_not_merely_broken():
    claim = declaration_claim(RETURN_RATE)
    codes = {f.code for f in claim.findings}
    assert claim.outcome == FINDINGS
    assert "no_table_named" in codes
    assert "documented_caution_unenforced" in codes
    assert {f.severity for f in claim.findings if f.code == "no_table_named"} == {DEFECT}


def test_a_dropped_filter_is_proven_by_the_number_not_by_the_classifier(items):
    """The mutation-resistant half.

    `metrics.value_query` appends WHERE only INSIDE its `if metric.tables` branch, so a metric
    that declares filters and no table loses them silently. This asserts the CONSEQUENCE against
    a real table — 2/5 unfiltered vs 2/3 filtered — so the test still fails if the finding's
    prose is reworded, and still fails if someone decides the finding is cosmetic.
    """
    filtered_only = RETURN_RATE.model_copy(update={"filters": ["status <> 'Cancelled'"]})
    assert "WHERE" not in value_query(filtered_only), "the filter reached the query after all"

    bound = filtered_only.model_copy(update={"tables": ["order_items"]})
    with_filter = execution_claim(bound, items)
    without_filter = execution_claim(
        bound.model_copy(update={"filters": []}), items)

    assert with_filter.detail["value"] == pytest.approx(2 / 3)
    assert without_filter.detail["value"] == pytest.approx(2 / 5)
    assert with_filter.detail["value"] != without_filter.detail["value"]

    findings = {f.code for f in declaration_claim(filtered_only).findings}
    assert "filters_silently_dropped" in findings


# A schema built to DISCRIMINATE, not to agree with the expectation beside it. It carries:
#   `returned_at` on BOTH tables            → genuinely ambiguous, must be reported
#   `sale_price` and `order_id` on ONE each → unambiguous, must NOT be reported
#   `order` on BOTH tables, never referenced by the formula except as a SUBSTRING of
#           `order_id`/`order_items` → must NOT be reported
# The first version of this fixture had no single-carrier column at all, so `len(carriers) > 1`
# and `> 0` produced identical output and a mutant that dropped the condition survived.
AMBIGUOUS_SCHEMA = {
    "order_items": ["id", "returned_at", "sale_price", "order"],
    "orders": ["order_id", "returned_at", "order"],
}
TWO_CARRIER_METRIC = RETURN_RATE.model_copy(update={
    "sql": "SUM(CASE WHEN returned_at IS NOT NULL THEN sale_price ELSE 0.0 END) "
           "/ NULLIF(COUNT(order_id), 0)",
})


def test_only_a_column_carried_by_more_than_one_table_is_ambiguous():
    """Kills the mutant that reports every referenced column: `sale_price` and `order_id` each
    live on exactly one table, so naming them would be noise, not a grain question."""
    findings = declaration_claim(TWO_CARRIER_METRIC, table_cols=AMBIGUOUS_SCHEMA).findings
    grain = [f for f in findings if f.code == "undeclared_grain"]
    reported = {f.evidence.split(" appears")[0] for f in grain}
    assert reported == {"returned_at"}, f"expected only returned_at, got {sorted(reported)}"
    assert "order_items" in grain[0].evidence and "orders" in grain[0].evidence


def test_undeclared_grain_matches_by_token_not_substring():
    """The JD-2 lesson one layer down: matching by substring would count `order` as referenced
    on the strength of `order_id` — an error in the direction that flatters the report.

    `order` is carried by BOTH tables here, so a substring matcher would report it as ambiguous.
    A token matcher never sees it, because the formula contains no `order` token.
    """
    grain = [f for f in declaration_claim(TWO_CARRIER_METRIC, table_cols=AMBIGUOUS_SCHEMA).findings
             if f.code == "undeclared_grain"]
    assert not [f for f in grain if f.evidence.startswith("order ")], \
        "`order` was reported, so matching is by substring rather than identifier token"


def test_a_skipped_grain_check_says_it_was_skipped():
    """The HTTP door cannot supply a schema — `get_schema_cached` BUILDS on a miss, and a read
    that builds once hung `GET /ontology`. So the check is genuinely skipped there, and a skip
    that does not announce itself is indistinguishable from a check that found nothing."""
    skipped = declaration_claim(RETURN_RATE, table_cols=None)
    assert skipped.detail["grain_checked"] is False
    assert "no schema was supplied" in skipped.detail["grain_skipped_because"]
    assert not [f for f in skipped.findings if f.code == "undeclared_grain"]

    ran = declaration_claim(TWO_CARRIER_METRIC, table_cols=AMBIGUOUS_SCHEMA)
    assert ran.detail["grain_checked"] is True
    assert ran.detail["grain_skipped_because"] == ""


def test_a_with_statement_is_a_statement_and_names_no_missing_from():
    """A metric's SQL is a statement, CTEs allowed (2026-09-26). The report used to test for
    a leading SELECT only, so a `WITH … SELECT` was reported as having no FROM clause."""
    cted = RETURN_RATE.model_copy(update={
        "sql": "WITH r AS (SELECT returned_at FROM order_items) "
               "SELECT SUM(CASE WHEN returned_at IS NOT NULL THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0) AS return_rate FROM r"})
    codes = {f.code for f in declaration_claim(cted).findings}
    assert "no_table_named" not in codes
    assert "filters_silently_dropped" not in codes


def test_a_definition_that_names_its_table_has_no_grain_finding():
    """The negative control. Without this, `undeclared_grain` could fire on everything and the
    tests above would still pass."""
    bound = TWO_CARRIER_METRIC.model_copy(update={"tables": ["order_items"]})
    codes = {f.code for f in declaration_claim(bound, table_cols=AMBIGUOUS_SCHEMA).findings}
    assert "undeclared_grain" not in codes
    assert "no_table_named" not in codes


def test_a_metric_that_names_its_table_does_not_report_dropped_filters():
    """The negative control the dropped-filter guard was missing entirely.

    Every earlier case had `tables=[]`, so a mutant that forgot the no-table condition changed
    no output and survived. A metric that names its table keeps its filters — `value_query`
    appends the WHERE — so reporting them as dropped would be a false alarm on the common case.
    """
    bound = RETURN_RATE.model_copy(update={
        "tables": ["order_items"], "filters": ["status <> 'Cancelled'"]})
    assert "WHERE" in value_query(bound), "the filter did not reach the query"
    codes = {f.code for f in declaration_claim(bound).findings}
    assert "filters_silently_dropped" not in codes


# ── Execution: three outcomes that must stay distinguishable ──────────────────

def test_could_not_run_is_not_ran_and_found_nothing(items):
    """A failure and a healthy empty must not both render as 'no value'. `compute_value` already
    distinguishes them; this pins that the report does not flatten them back together."""
    broken = RETURN_RATE.model_copy(update={"tables": ["no_such_table"]})
    assert execution_claim(broken, items).outcome == UNAVAILABLE

    empty = MetricDefinition(name="none", label="None", sql="SUM(id)",
                             tables=["order_items"], filters=["id < 0"])
    empty_claim = execution_claim(empty, items)
    assert empty_claim.outcome == FINDINGS
    assert {f.code for f in empty_claim.findings} == {"matched_no_rows"}


def test_no_connection_is_unavailable_with_a_sentence():
    claim = execution_claim(RETURN_RATE, None)
    assert claim.outcome == UNAVAILABLE and claim.summary.strip()


# ── Predecessor: first approval is a state, not an empty panel ────────────────

def test_first_approval_says_so_rather_than_rendering_an_empty_diff():
    """An empty diff panel and 'nothing changed' look identical and mean opposite things. The
    specimen's own audit trail is two deletes with no formula, which is the common case here."""
    deletes = [{"action": "delete", "sql": None}, {"action": "delete", "sql": None}]
    claim = predecessor_claim(RETURN_RATE, deletes)
    assert claim.outcome == NOT_APPLICABLE
    assert "First approval" in claim.summary
    assert claim.detail["audit_events"] == 2 and claim.detail["with_formula"] == 0


def test_an_unchanged_formula_is_clean_and_a_changed_one_is_a_finding():
    prior = [{"action": "approve", "sql": RETURN_RATE.sql}]
    assert predecessor_claim(RETURN_RATE, prior).outcome == CLEAN
    moved = RETURN_RATE.model_copy(update={"sql": "COUNT(*)"})
    claim = predecessor_claim(moved, prior)
    assert claim.outcome == FINDINGS
    assert {f.code for f in claim.findings} == {"formula_changed"}
    assert claim.detail["was"] != claim.detail["now"]


# ── Segments: the honest empty column ─────────────────────────────────────────

def test_no_dimensions_is_stated_not_ticked():
    """"What regressed" has no mechanism in this tree and the specimen declares no dimensions.
    A green tick here would be a guard that passes because it never looked."""
    claim = segments_claim(RETURN_RATE)
    assert claim.outcome == NOT_APPLICABLE
    assert "no dimensions" in claim.summary
    assert claim.detail["dimensions"] == []


# ── Population ────────────────────────────────────────────────────────────────

def test_a_plain_duckdb_fingerprints_but_cannot_pin(items):
    """DuckLake time travel is what PINNED requires; a plain file can only be fingerprinted."""
    pop = population_of(items, ["order_items"])
    assert pop.mode == FINGERPRINTED and pop.token and pop.reproducible is False


def test_a_definition_with_no_tables_is_unpinnable_with_a_reason(items):
    pop = population_of(items, [])
    assert pop.mode == UNPINNABLE
    assert "no table" in pop.reason


# ── Advisory only ─────────────────────────────────────────────────────────────

def test_the_report_cannot_reach_anything_that_holds_a_send():
    """Two readers of the drafting study recommended modelling this on `govern.departure`'s
    `Measurement`, whose `blocking_caveats` makes the departure gate return HOLDS. Following
    that would have violated the one constraint this slice was given, so it is pinned here
    rather than left to reviewer memory."""
    import ast
    import inspect
    from aughor.semantic import definition_report

    # Parsed, NOT grepped. The first version of this test searched the source TEXT and failed on
    # the module docstring — which names `gate_departure` precisely to explain why it is not
    # used. A guard that reads prose is a guard that fires on the explanation of itself, so this
    # walks the AST and looks only at real Import/ImportFrom nodes, including the function-local
    # ones this module uses.
    tree = ast.parse(inspect.getsource(definition_report))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)

    assert imported, "parsed no imports at all — the guard would pass vacuously"
    offenders = [m for m in imported if m.startswith("aughor.govern")]
    assert not offenders, f"A3 must not import govern — it is advisory, never a gate: {offenders}"
    assert build_report(RETURN_RATE).advisory is True


def test_the_mirrored_approval_check_agrees_with_the_gates_own():
    """`_is_approved` mirrors `govern.departure.metric_is_approved` rather than importing it, to
    keep the import graph clean. Mirroring risks a second vocabulary, so the two are pinned to
    agree on every lifecycle state instead of being trusted to."""
    from aughor.govern.departure import metric_is_approved

    for status in ("draft", "proposed", "approved", "deprecated", ""):
        m = RETURN_RATE.model_copy(update={"status": status})
        assert _is_approved(m) == metric_is_approved(m), f"disagreed on {status!r}"

    legacy = RETURN_RATE.model_copy(update={"status": "", "approved_by": "Finance"})
    assert _is_approved(legacy) == metric_is_approved(legacy)


# ── The whole screen ──────────────────────────────────────────────────────────

# ── The door ──────────────────────────────────────────────────────────────────

def test_the_door_refuses_to_report_on_another_connections_definition(client):
    """The live defect this route was written NOT to have.

    `get_metric` falls back to the GLOBAL definition when a connection has none of its own, so
    `/metrics/{name}/value`, `/validate` and `/freshness` — all of which call `get_metric(name)`
    with no connection — answer for whichever definition happens to match the name first. On
    this deployment that means `GET /metrics/revenue/value?conn_id=8233e4fd` returns the formula
    of a connection that no longer exists, at HTTP 200, with nothing naming whose it was.

    The first assertion proves the fallback is real, so the second is testing the route's own
    check rather than an absence.
    """
    from aughor.semantic.metrics import GLOBAL_CONNECTION, MetricDefinition, get_metric, save_metric

    save_metric(MetricDefinition(name="ghost", label="Ghost", sql="COUNT(*)",
                                 tables=["t"], connection=GLOBAL_CONNECTION, status="approved"))

    # The fallback exists: asking scoped to a connection that has no `ghost` still returns one.
    assert get_metric("ghost", connection_id="no_such_conn") is not None

    r = client.get("/metrics/ghost/definition-report?conn_id=no_such_conn")
    assert r.status_code == 404, "the door reported on a definition belonging to someone else"
    assert "no_such_conn" in r.json()["detail"]


def test_the_door_keeps_every_typed_word_on_the_wire(client, items, monkeypatch):
    """`unavailable` and `unpinnable` must survive serialisation as WORDS. Flattening them to a
    null value or an absent field is the collapse the dataclasses refuse to make in memory, and
    a payload that undoes it there would put the whole report back where it started."""
    from aughor.routers import metrics as router_mod
    from aughor.semantic.metrics import save_metric

    save_metric(RETURN_RATE.model_copy(update={"connection": "c1"}))
    monkeypatch.setattr(router_mod, "open_connection_for", lambda _c: items, raising=False)
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda _c: items,
                        raising=False)

    r = client.get("/metrics/return_rate/definition-report?conn_id=c1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["advisory"] is True
    # Specific tokens, not "one of the allowed values" — the first version of this assertion
    # listed every outcome the enum has, which is a check that cannot fail. The specimen names
    # no table, so the query has no FROM and the engine cannot bind its column: DuckDB says
    # "Binder Error: Referenced column …", BigQuery says "400 Unrecognized name" — the same
    # answer in two dialects, and `unavailable` is what both must serialise to.
    assert body["execution"]["outcome"] == UNAVAILABLE
    assert "returned_at" in body["execution"]["detail"]["error"]
    assert body["population"]["mode"] == UNPINNABLE
    assert body["population"]["reason"].strip()
    assert body["population"]["reproducible"] is False
    assert body["predecessor"]["outcome"] == NOT_APPLICABLE
    assert "no_table_named" in body["defects"]
    assert body["declaration"]["detail"]["grain_checked"] is False


def test_the_specimen_report_tells_an_approver_something_actionable(items):
    """A3's falsifier is "if the report changes no decision, it is ceremony". On the specimen
    the report says: it cannot run, it names no table, and it documents a caution it does not
    enforce — three things the bare ask shows none of."""
    report = build_report(RETURN_RATE, items, connection_id="8233e4fd",
                          audit_events=[{"action": "delete", "sql": None}])
    assert report.status == "draft" and report.version == 0
    assert report.execution.outcome == UNAVAILABLE
    assert report.predecessor.outcome == NOT_APPLICABLE
    assert {f.code for f in report.defects} >= {"no_table_named"}
    assert report.population.mode == UNPINNABLE
    assert report.advisory is True
