"""The relationship primitive, and the guards that stop a metric explaining itself.

Every specimen here is from one live run — investigation `5dc26c2c`, "Is there a
correlation between shipping delay and customer location?" over the DataCo supply-chain
export. The report it produced led with a chart reading 100% / 0%, drew a "city-level
rates range from 73.21% to 81.32%" claim off the top 15 of 563 cities, and never computed
a correlation of any kind. The numbers below are that run's, so a regression here is the
same report coming back.
"""
import pytest

from aughor.agent.investigate import (_candidate_label, _drop_self_referential_segment,
                                      _finding_earns_place, _relationship_candidates,
                                      _rival_candidates_note,
                                      _hit_row_cap, _intake_relationship_pair,
                                      _is_saturated, _population_note,
                                      _ranking_noise_caveat)
from aughor.agent.relationship import (bare_column, numeric_expression, plan_relationship,
                                       read_relationship, self_referential_segment,
                                       side_expression, sql_columns)
from aughor.tools.stats import assess_correlation, assess_group_means

METRIC = "AVG(Late_delivery_risk)"
SEGMENT = "Late_delivery_risk = 1"
DELAY = '"Days for shipping (real)" - "Days for shipment (scheduled)"'
TABLE = "data_co.data_co_supplychain"
COL_TYPES = {"Latitude": "VARCHAR", "Customer State": "VARCHAR", "Customer City": "VARCHAR",
             "Late_delivery_risk": "BIGINT", "Days for shipping (real)": "BIGINT",
             "Days for shipment (scheduled)": "BIGINT"}


# ── 1. a driver segment may not be the metric wearing a CASE ─────────────────

def test_the_live_tautology_is_named():
    reason = self_referential_segment(METRIC, SEGMENT)
    assert reason and "late_delivery_risk" in reason


def test_qualification_does_not_hide_the_overlap():
    """The metric and the condition are written by different prompts, so one side may
    qualify the column and the other may not. Comparing qualified strings would blind the
    guard exactly when the two sides came from different places."""
    assert self_referential_segment("AVG(s.Late_delivery_risk)", "t.Late_delivery_risk = 1")


def test_a_real_driver_survives():
    assert self_referential_segment(METRIC, "\"Shipping Mode\" = 'Same Day'") is None
    assert self_referential_segment("SUM(revenue)", "is_new_customer") is None


def test_an_unreadable_side_claims_nothing():
    """A guard that cannot parse its input must not claim a verdict about it — dropping a
    legitimate driver contrast is the same size of mistake as keeping a tautological one."""
    assert sql_columns(")))not sql(((") == set()
    assert self_referential_segment(METRIC, ")))not sql(((") is None


class _Intake:
    def __init__(self, metric_sql, segment_sql, label="late vs on-time"):
        self.metric_sql = metric_sql
        self.comparison_segment_sql = segment_sql
        self.comparison_segment_label = label
        self.intake_notes = "original notes"


def test_the_contrast_is_dropped_with_a_receipt():
    intake = _Intake(METRIC, SEGMENT)
    assert _drop_self_referential_segment(intake)
    assert intake.comparison_segment_sql == ""
    assert intake.comparison_segment_label == ""
    # The reason has to reach the reader: a contrast that silently disappears is as hard
    # to debug as one that lies.
    assert "DRIVER CONTRAST DROPPED" in intake.intake_notes
    assert "original notes" in intake.intake_notes


def test_a_good_contrast_is_left_alone():
    intake = _Intake(METRIC, "\"Shipping Mode\" = 'Same Day'")
    assert _drop_self_referential_segment(intake) is None
    assert intake.comparison_segment_sql == "\"Shipping Mode\" = 'Same Day'"
    assert intake.intake_notes == "original notes"


# ── 2/3. typing the two sides ────────────────────────────────────────────────

def test_a_name_is_quoted_and_an_expression_is_not():
    """Quoting an expression produces one absurd identifier and the binder rejects it with
    the whole expression as the missing column name — the first thing that broke live."""
    assert side_expression("Customer State", COL_TYPES) == '"Customer State"'
    assert side_expression(DELAY, COL_TYPES) == DELAY
    assert bare_column(DELAY, COL_TYPES) is None


def test_a_column_name_with_spaces_is_recognised_from_the_schema():
    """`Customer State` parses as two tokens and `Days for shipping (real)` parses as a
    function call, so the parser alone cannot tell either from an expression. The schema
    already knows they are columns."""
    assert bare_column("Customer State", COL_TYPES) == "Customer State"
    assert bare_column("Days for shipping (real)", COL_TYPES) == "Days for shipping (real)"
    assert bare_column('"Customer State"', COL_TYPES) == "Customer State"
    assert bare_column("Customer State", None) is None


def test_a_declared_number_needs_no_probe():
    calls = []

    def _run(sql):
        calls.append(sql)
        return [[1, 1]]

    assert numeric_expression("Days for shipping (real)", "BIGINT", TABLE, _run,
                              COL_TYPES) == '"Days for shipping (real)"'
    assert calls == []


def test_a_text_column_holding_numbers_is_reachable():
    """Latitude lands as VARCHAR from the local upload and as a float from BigQuery. A
    type-only test makes the same analysis reachable on one warehouse and invisible on
    the other — a property of the loader, not of the question."""
    expr = numeric_expression("Latitude", "VARCHAR", TABLE, lambda _s: [[180519, 180519]],
                              COL_TYPES)
    assert expr == 'TRY_CAST("Latitude" AS DOUBLE)'


def test_a_text_column_holding_words_is_not_a_number():
    assert numeric_expression("Customer City", "VARCHAR", TABLE, lambda _s: [[180519, 0]],
                              COL_TYPES) is None


@pytest.mark.parametrize("runner", [None, lambda _s: None, lambda _s: [[0, 0]]])
def test_an_unanswerable_probe_reports_not_a_number(runner):
    """A dialect without TRY_CAST, a dead connection and a genuinely non-numeric column
    must all land on the same narrow answer. Failing open would run CORR over an all-NULL
    cast and report a confident zero."""
    assert numeric_expression("Latitude", "VARCHAR", TABLE, runner, COL_TYPES) is None


def test_a_raising_probe_is_not_an_exception():
    def _boom(_sql):
        raise RuntimeError("no TRY_CAST in this dialect")

    assert numeric_expression("Latitude", "VARCHAR", TABLE, _boom, COL_TYPES) is None


# ── 2. the query shape follows the pair's types ──────────────────────────────

def _castable(_sql):
    return [[180519, 180519]]


def _not_castable(_sql):
    return [[180519, 0]]


def test_two_measured_quantities_get_a_correlation():
    plan = plan_relationship(table=TABLE, left_column=DELAY, right_column="Latitude",
                             left_label="shipping delay", right_label="customer latitude",
                             col_types=COL_TYPES, run=_castable)
    assert plan.kind == "numeric_pair"
    assert "CORR(" in plan.sql
    assert "GROUP BY" not in plan.sql


def test_a_quantity_against_a_category_gets_group_means():
    def _run(sql):
        return _castable(sql) if "Days for shipping" in sql else _not_castable(sql)

    plan = plan_relationship(table=TABLE, left_column=DELAY, right_column="Customer State",
                             left_label="shipping delay", right_label="customer state",
                             col_types=COL_TYPES, run=_run)
    assert plan.kind == "numeric_by_category"
    assert "STDDEV_SAMP(" in plan.sql and "GROUP BY 1" in plan.sql
    assert '"Customer State"' in plan.sql


def test_two_categories_still_get_the_joint_distribution():
    plan = plan_relationship(table=TABLE, left_column="Customer State",
                             right_column="Customer City", left_label="state",
                             right_label="city", col_types=COL_TYPES, run=_not_castable)
    assert plan.kind == "category_pair"
    assert "GROUP BY 1, 2" in plan.sql


def test_one_column_against_itself_is_not_a_relationship():
    plan = plan_relationship(table=TABLE, left_column="Late_delivery_risk",
                             right_column="Late_delivery_risk", left_label="a",
                             right_label="b", col_types=COL_TYPES, run=_castable)
    assert plan.kind == "" and plan.skipped


# ── 2. reading the executed result ───────────────────────────────────────────

def test_the_live_correlation_reads_as_no_relationship():
    plan = plan_relationship(table=TABLE, left_column=DELAY, right_column="Latitude",
                             left_label="shipping delay", right_label="customer latitude",
                             col_types=COL_TYPES, run=_castable)
    reading = read_relationship(
        plan, ["correlation", "n_records"], [["0.00045019980020974507", "180519"]])
    assert "uncorrelated" in reading.interpretation
    assert "180,519" in reading.interpretation
    assert "r = 0.0005" in reading.technical
    assert reading.effect < 1e-6          # r-squared, the scale rival candidates are ranked on


def test_a_null_correlation_is_an_answer_not_a_dropped_finding():
    """Result rows arrive stringified, so a SQL NULL is the four characters "NULL". Read
    as unparseable it returned None and the finding vanished — the report then fell back
    to rankings with nothing saying why."""
    plan = plan_relationship(table=TABLE, left_column=DELAY, right_column="Latitude",
                             left_label="shipping delay", right_label="customer latitude",
                             col_types=COL_TYPES, run=_castable)
    out = read_relationship(plan, ["correlation", "n_records"], [["NULL", "180519"]])
    assert out is not None
    assert "undefined" in out.interpretation


def test_a_single_record_group_is_not_silently_discarded():
    """STDDEV_SAMP of one row is NULL. Reading that as unparseable dropped the group whole
    — mean, count and all — which is a silent exclusion of real data."""
    plan = plan_relationship(table=TABLE, left_column=DELAY, right_column="Customer State",
                             left_label="shipping delay", right_label="customer state",
                             col_types=COL_TYPES,
                             run=lambda s: _castable(s) if "Days for shipping" in s else _not_castable(s))
    cols = ["customer_state", "mean_value", "sd_value", "n_records"]
    rows = [["PR", "0.56", "1.49", "69373"], ["CA", "0.57", "1.50", "40000"],
            ["91732", "0.0", "NULL", "1"]]
    reading = read_relationship(plan, cols, rows)
    assert "109,374 records" in reading.interpretation and "3 groups" in reading.interpretation
    assert "excluded" not in reading.interpretation


# ── 2. significance is not the same claim as "it matters" ────────────────────

def test_a_tiny_correlation_over_a_large_table_is_not_a_finding():
    verdict = assess_correlation(0.00045, 180519, "shipping delay", "latitude")
    assert verdict.strength == "none"
    assert "uncorrelated" in verdict.interpretation


def test_a_real_correlation_is_reported_as_a_lead_not_a_cause():
    verdict = assess_correlation(0.62, 5000, "discount depth", "return rate")
    assert verdict.strength == "strong"
    assert "not a demonstrated cause" in verdict.interpretation


def test_an_undefined_correlation_has_no_verdict():
    assert assess_correlation(None, 100, "a", "b") is None
    assert assess_correlation(0.5, 2, "a", "b") is None


def test_a_significant_f_with_a_negligible_effect_does_not_differ():
    """The live shape: shipping delay by customer state is significant at p ~ 1e-18 over
    180k rows and explains 0.1% of the variation. Leading with the p-value would report a
    geographic driver that does not exist."""
    # Shaped after the live run: 45 groups of ~4,000 records, means spread across a fifth
    # of a day, and a within-group SD of 1.49 days that dwarfs it.
    groups = [(f"S{i}", 0.55 + i * 0.0045, 1.49, 4000) for i in range(45)]
    verdict = assess_group_means(groups, "shipping delay", "customer state")
    assert verdict.p_value < 0.05
    assert verdict.eta_squared < 0.01
    assert verdict.differs is False
    assert "does not meaningfully differ" in verdict.interpretation


def test_a_real_group_difference_is_reported():
    groups = [("Same Day", 0.1, 0.5, 3000), ("Standard Class", 3.4, 0.6, 3000)]
    verdict = assess_group_means(groups, "shipping delay", "shipping mode")
    assert verdict.differs is True
    assert "does differ" in verdict.interpretation


def test_one_group_is_no_comparison():
    assert assess_group_means([("only", 1.0, 0.5, 10)], "m", "d") is None


# ── 1b/4. a saturated exhibit never reaches the reader ───────────────────────

TAUTOLOGY = {"columns": ["segment", "Late Delivery Rate"],
             "rows": [["Late", "1.0"], ["On-time", "0.0"]],
             "interpretation": "Query executed."}


def test_the_hundred_percent_versus_zero_chart_is_dropped():
    """It survived `_is_zero_variance_ranking` because 100-vs-0 is the MAXIMUM spread a
    ranking can have — the uniformity drop is the opposite test."""
    assert _is_saturated(TAUTOLOGY["columns"], TAUTOLOGY["rows"]) is True
    assert _finding_earns_place(TAUTOLOGY) is False


def test_a_real_ranking_still_earns_its_place():
    real = {"columns": ["Customer State", "Late Delivery Rate"],
            "rows": [["NM", "0.6027"], ["DE", "0.6022"], ["IN", "0.5611"]],
            "interpretation": "The rate is tightly clustered."}
    assert _is_saturated(real["columns"], real["rows"]) is False
    assert _finding_earns_place(real) is True


# ── 4. a capped, noisy ranking says so ───────────────────────────────────────

class _Result:
    def __init__(self, sql, row_count):
        self.sql = sql
        self.row_count = row_count


def test_a_full_limit_is_recognised_as_a_slice():
    assert _hit_row_cap(_Result("SELECT a FROM t GROUP BY 1 ORDER BY 2 DESC LIMIT 15", 15))
    assert not _hit_row_cap(_Result("SELECT a FROM t GROUP BY 1 ORDER BY 2 DESC LIMIT 15", 4))
    assert not _hit_row_cap(_Result("SELECT a FROM t GROUP BY 1", 15))


#: The live top-15 of 563 customer cities: below-median volume, 73-81%, and reported in
#: the reader-facing summary as the range of city-level rates. The true range across all
#: cities is 27.6%-81.3%, and cities with 200+ records average 54.6% — the overall rate.
_TOP_CITIES = [["Denton", 0.8131, 91], ["Marion", 0.7941, 34], ["Medina", 0.7866, 75],
               ["Sumner", 0.7857, 28], ["Garland", 0.7727, 88], ["Roseville", 0.7723, 123],
               ["Revere", 0.7692, 39], ["Lithonia", 0.7540, 61], ["Arlington", 0.7424, 66],
               ["Lawton", 0.7380, 42], ["Tustin", 0.7355, 208], ["Waukegan", 0.7352, 68],
               ["Decatur", 0.7340, 94], ["Flushing", 0.7338, 124], ["Tulare", 0.7321, 56]]


def test_the_noisy_city_slice_carries_its_own_numbers():
    caveat = _ranking_noise_caveat(["Customer City", "late_rate", "n"], _TOP_CITIES, True)
    assert caveat
    assert "not distinguishable from sampling noise" in caveat
    assert "28–208 records" in caveat
    assert "not the population's range" in caveat


def test_an_uncapped_scan_makes_no_truncation_claim():
    caveat = _ranking_noise_caveat(["Customer City", "late_rate", "n"], _TOP_CITIES, False)
    assert caveat and "capped scan" not in caveat


def test_a_ranking_with_real_separation_gets_no_caveat():
    rows = [["Same Day", 0.95, 5000], ["Second Class", 0.55, 5000], ["Standard", 0.10, 5000]]
    assert _ranking_noise_caveat(["mode", "late_rate", "n"], rows, True) is None


def test_a_result_with_no_denominator_is_left_alone():
    """Without a count column the interval cannot be drawn, so there is no verdict to
    give — silence, not a guess."""
    rows = [["a", 0.81], ["b", 0.79], ["c", 0.73]]
    assert _ranking_noise_caveat(["city", "late_rate"], rows, True) is None


# ── 4. the population note follows the sort order ────────────────────────────

def test_the_note_matches_a_descending_scan():
    """`_direction_plan` flips the scan to DESC whenever a higher value is the worse
    outcome; the note under the results did not flip and kept calling the top fifteen of
    563 cities "the BOTTOM of the distribution"."""
    note = _population_note(True, True)
    assert "HIGHEST-ranked" in note and "BOTTOM" in note
    assert "Do NOT state a RANGE" in note


def test_the_note_matches_an_ascending_scan():
    note = _population_note(False, True)
    assert "LOWEST-ranked" in note and "TOP" in note


def test_both_interpret_prompts_accept_the_note():
    """The note is a placeholder in both templates now — a KeyError here is the phase
    failing to interpret at all."""
    from aughor.agent.prompts_investigate import (CROSS_SECTION_INTERPRET_PROMPT,
                                                  CROSS_SECTION_RATIO_INTERPRET_PROMPT)
    for template in (CROSS_SECTION_INTERPRET_PROMPT, CROSS_SECTION_RATIO_INTERPRET_PROMPT):
        out = template.format(question="q", metric_label="m", results_text="rows",
                              population_note=_population_note(True, True))
        assert "HIGHEST-ranked" in out


# ── 2. intake names the two sides ────────────────────────────────────────────

def test_intake_supplies_the_pair_the_question_words_could_not_reach():
    """`_dimensions_named_in_question` needs every word of the column name in the
    question, so "customer location" reaches neither `Customer City` nor `Customer State`
    and "shipping delay" reaches no column at all. On the live run it matched nothing and
    no scan ran."""
    pair = _intake_relationship_pair({
        "relationship_left_sql": DELAY, "relationship_left_label": "shipping delay (days)",
        "relationship_right_sql": "Customer State", "relationship_right_label": "customer state"})
    assert pair == (DELAY, "Customer State", "shipping delay (days)", "customer state")


@pytest.mark.parametrize("data", [
    {},
    {"relationship_left_sql": DELAY},
    {"relationship_left_sql": "Customer State", "relationship_right_sql": "Customer State"},
])
def test_an_incomplete_pair_falls_back_to_the_old_matching(data):
    assert _intake_relationship_pair(data) is None


# ── 4b. the same defect on a MEAN, after the metric fix moved it there ───────

#: The live second run (`8f83b1b4`) after the metric became a delay in days. Top 15 of
#: 1,089 order states by average delay: 6.3 records each against a median state of 41, and
#: 16 states hold exactly one record. States with 200+ records average 0.559 days against a
#: global 0.566 — so "highly variable at city and state levels" reached the headline off a
#: ranking made of handfuls.
_TOP_STATES = [["Ilam", 3.2, 1.0, 5], ["Vest-Agder", 3.09, 0.9, 11], ["Isparta", 3.0, 0.0, 1],
               ["Ar Raqa", 3.0, 0.0, 1], ["Tlemcen", 3.0, 0.0, 2], ["Bitola", 3.0, 0.0, 1],
               ["Olomouc", 3.0, 0.8, 4], ["Suceava", 3.0, 0.0, 1], ["Luxembourg", 2.9, 1.1, 9],
               ["Ecuatoria Central", 2.2, 1.2, 7]]
_STATE_COLS = ["Order State", "metric_total", "sd", "n"]


def test_a_mean_ranking_over_tiny_groups_is_caveated():
    """The rate branch cannot see this: 3.2 days is not a proportion, so
    `assess_rate_uniformity` never fires. Fixing the metric moved the defect here."""
    caveat = _ranking_noise_caveat(_STATE_COLS, _TOP_STATES, True)
    assert caveat
    assert "1–11 records" in caveat
    assert "not the population's range" in caveat


def test_a_mean_ranking_with_real_separation_gets_no_caveat():
    rows = [["Same Day", 0.1, 0.4, 4000], ["Second Class", 1.8, 0.5, 4000],
            ["Standard Class", 3.4, 0.6, 4000]]
    assert _ranking_noise_caveat(["mode", "metric_total", "sd", "n"], rows, True) is None


def test_without_a_spread_column_the_volume_fact_still_lands():
    """A scan that did not carry STDDEV can run no test at all — but "over half these rows
    hold fewer than 30 records" is a fact about the query, not a statistic."""
    rows = [[r[0], r[1], r[3]] for r in _TOP_STATES]
    caveat = _ranking_noise_caveat(["Order State", "metric_total", "n"], rows, True)
    assert caveat and "too small to average" in caveat


def test_a_flat_but_well_powered_ranking_is_still_called_noise():
    """Plenty of records and no real gap is the OTHER way a ranking misleads: nothing is
    too small here, and the order still means nothing. The caveat says why without
    reaching for the volume language."""
    rows = [[f"S{i}", 0.5, 1.4, 4000] for i in range(5)]
    rows[0][1] = 0.52
    caveat = _ranking_noise_caveat(["state", "metric_total", "sd", "n"], rows, False)
    assert caveat and "inside the spread within each group" in caveat
    assert "too small to average" not in caveat
    assert "capped scan" not in caveat


# ── 2b. one concept, several columns ─────────────────────────────────────────

def test_every_column_of_the_concept_is_a_candidate():
    """"Customer location" is city, state, country and region. Testing only the one the
    question's words reached answers a narrower question — country has two values and
    cannot see anything city would show."""
    data = {"relationship_right_sql": "Customer City",
            "relationship_right_alternatives": ["Customer State", "Customer Country",
                                                "Order Region", "Order State", "Market"]}
    got = _relationship_candidates(data, "Customer City")
    assert got == ["Customer City", "Customer State", "Customer Country", "Order Region"]


def test_the_primary_is_never_duplicated_and_no_alternatives_is_fine():
    data = {"relationship_right_alternatives": ["Customer City", "Customer State"]}
    assert _relationship_candidates(data, "Customer City") == ["Customer City", "Customer State"]
    assert _relationship_candidates({}, "Customer City") == ["Customer City"]


def test_an_alternative_is_named_by_its_own_column():
    """The primary keeps intake's label; an alternative must say WHICH reading of the
    concept the verdict is about, or a country result reads as "location"."""
    assert _candidate_label("Customer City", "Customer City", "customer location") == "customer location"
    assert _candidate_label("Order Region", "Customer City", "customer location") == "Order Region"


def test_the_losing_candidates_are_named_so_a_null_covers_the_concept():
    class _P:
        def __init__(self, label):
            self.right_label = label

    scored = [(0.031, "c", _P("customer city"), None, None),
              (0.001, "s", _P("customer state"), None, None),
              (0.0000, "k", _P("customer country"), None, None)]
    note = _rival_candidates_note(scored)
    assert "customer state (0.1%)" in note and "customer country (0.0%)" in note
    assert _rival_candidates_note(scored[:1]) == ""


def test_a_driver_truncated_result_says_so():
    """`MAX_ROWS` (500) caps the result BELOW this module's own SQL limit, so the SQL cap
    never fires and a 563-value dimension is tested on 500 groups. The prose that came back
    was self-consistent — "across 500 groups and 177,421 records" — which is exactly what
    makes an unsaid truncation read as the whole population."""
    plan = plan_relationship(table=TABLE, left_column=DELAY, right_column="Customer City",
                             left_label="shipping delay", right_label="customer city",
                             col_types=COL_TYPES,
                             run=lambda s: _castable(s) if "Days for shipping" in s else _not_castable(s))
    cols = ["customer_city", "mean_value", "sd_value", "n_records"]
    rows = [[f"C{i}", 0.5, 1.4, 400] for i in range(500)]
    assert "not exhaustive" not in read_relationship(plan, cols, rows).interpretation
    assert "not exhaustive" in read_relationship(plan, cols, rows, truncated=True).interpretation


# ── 3 fixes from the third live run (`3bfce2ee`) ─────────────────────────────

def test_one_column_written_three_ways_is_one_candidate():
    """Intake names the primary and the alternatives in separate fields and does not spell
    them identically. A raw-string dedup let the winner through twice, so the report said
    the question "was also asked of Customer City (1.1%)" under the Customer City verdict."""
    data = {"relationship_right_alternatives": [
        '"Customer City"', "data_co.data_co_supplychain.Customer City", "customer  city",
        "Customer State"]}
    assert _relationship_candidates(data, "Customer City") == ["Customer City", "Customer State"]


def test_a_real_but_tiny_effect_is_not_reported_as_a_driver():
    """eta-squared = 0.0109 cleared the small-effect floor, the verdict read "does differ",
    and the report escalated that to "correlated with geography, driven by localized
    state-level bottlenecks"."""
    groups = [(f"C{i}", 0.5 + (i % 40) * 0.02, 1.4, 320) for i in range(560)]
    verdict = assess_group_means(groups, "shipping delay", "customer city")
    assert verdict.differs is True                      # it IS distinguishable
    assert 0.01 <= verdict.eta_squared < 0.06
    assert "too little to treat as a driver" in verdict.interpretation
    assert "does differ by" not in verdict.interpretation


def test_a_material_effect_still_reads_as_one():
    groups = [("Same Day", 0.1, 0.5, 3000), ("Standard Class", 3.4, 0.6, 3000)]
    verdict = assess_group_means(groups, "shipping delay", "shipping mode")
    assert verdict.eta_squared >= 0.06
    assert "does differ" in verdict.interpretation


# ── the verdict must reach the thing that writes the headline ────────────────

def _noise_phase():
    return [{"phase_name": "Cross-Sectional", "findings": [{
        "sql": 'SELECT "Order State", AVG(d) FROM t GROUP BY 1 ORDER BY 2 DESC LIMIT 15',
        "columns": ["Order State", "metric_total", "n"],
        "rows": [["Ilam", "3.2", "5"], ["Vest-Agder", "3.09", "11"], ["Suceava", "3.0", "1"]],
        "row_count": 15, "error": None, "interpretation": "…",
        "stat_note": ("This ordering is not evidence of a difference: the gaps between these "
                      "averages are inside the spread within each group. The shown groups hold "
                      "1–21 records each."),
        "trust_caveat": None, "key_numbers": [], "chart_type": "bar_horizontal",
        "is_significant": False}]}]


def test_the_evidence_block_carries_the_verdict():
    """It carried SQL and rows and nothing else, so the model writing the headline saw
    `Ilam | 3.2 | 5` with every statistic computed for it withheld."""
    from aughor.agent.investigate import _one_phase_evidence
    block = _one_phase_evidence(_noise_phase()[0])
    assert "STATISTICAL VERDICT" in block
    assert "not evidence of a difference" in block
    assert block.index("STATISTICAL VERDICT") < block.index("Ilam")   # before the rows it governs


def test_a_condensed_phase_keeps_its_verdict():
    """The phases that overflow the budget are the ones most likely to be cited loosely."""
    from aughor.agent.investigate import _condense_phase_evidence
    assert "STATISTICAL VERDICT" in _condense_phase_evidence(_noise_phase()[0])


class _Synth:
    def __init__(self, headline, summary=""):
        self.headline = headline
        self.executive_summary = summary
        self.closing_summary = ""
        self.attribution_waterfall = []
        self.data_gaps = []


def test_a_noise_level_standout_in_the_headline_is_a_violation():
    from aughor.agent.report_checks import run_report_checks
    synth = _Synth("Shipping delay is driven by localized state-level bottlenecks",
                   "Order State Ilam records the highest average delay at 3.2 days.")
    violations = run_report_checks(synth, "does location matter?", "evidence", _noise_phase())
    assert any("Ilam" in v and "not evidence of a difference" in v for v in violations)


def test_an_honest_report_over_the_same_findings_is_clean():
    from aughor.agent.report_checks import run_report_checks
    synth = _Synth("Shipping delay is not explained by geography",
                   "No location group is distinguishable from the rest once group size is taken "
                   "into account.")
    assert run_report_checks(synth, "does location matter?", "evidence", _noise_phase()) == []


def test_a_finding_with_a_real_verdict_never_gates_the_report():
    from aughor.agent.report_checks import run_report_checks
    phases = _noise_phase()
    phases[0]["findings"][0]["stat_note"] = "one-way ANOVA F(3,900) = 44.1, p = 1e-26"
    synth = _Synth("Ilam is the slowest destination", "Ilam averages 3.2 days.")
    assert run_report_checks(synth, "q", "evidence", phases) == []


# ── the verdict must also reach the FINDING narrator (run 4: `54df16fa`) ─────

class _QR:
    def __init__(self, columns, rows, sql="SELECT a FROM t GROUP BY 1 ORDER BY 2 DESC LIMIT 15"):
        self.columns, self.rows, self.sql = columns, rows, sql
        self.error, self.row_count = None, len(rows)
        self.stats = []


def test_the_narrator_sees_the_verdict_before_it_writes():
    """It wrote the phase's findings from rows alone — the verdict was computed afterwards
    and only stamped onto the finished finding — so a card read "the significantly higher
    delay in Oklahoma suggests a localized performance issue" above a stat_note saying the
    ordering was not evidence of a difference at p = 0.072."""
    from aughor.agent.investigate import _results_text_with_verdicts
    r = _QR(_STATE_COLS, [[x[0], x[1], x[2], x[3]] for x in _TOP_STATES] * 2)
    text = _results_text_with_verdicts([r], max_rows=20)
    assert "STATISTICAL VERDICT" in text
    assert "Do NOT call any value here significant" in text.replace("\n", " ")
    assert text.index("STATISTICAL VERDICT") < text.index("Ilam")


def test_a_clean_result_gets_no_verdict_banner():
    from aughor.agent.investigate import _results_text_with_verdicts
    r = _QR(["mode", "metric_total", "sd", "n"],
            [["Same Day", 0.1, 0.4, 4000], ["Standard", 3.4, 0.6, 4000]])
    assert "STATISTICAL VERDICT" not in _results_text_with_verdicts([r], max_rows=20)


def test_a_contradicting_interpretation_is_led_by_the_verdict():
    from aughor.agent.investigate import _lead_with_verdict
    f = {"interpretation": "The significantly higher delay in Oklahoma suggests a localized "
                           "performance issue.", "is_significant": True}
    _lead_with_verdict(f, "This ordering is not evidence of a difference.")
    assert f["interpretation"].startswith("This ordering is not evidence of a difference.")
    assert "Oklahoma" in f["interpretation"]          # the model's sentence is kept, not deleted
    assert f["is_significant"] is False


def test_a_descriptive_interpretation_is_left_alone():
    """Saying what the rows contain is not overclaiming."""
    from aughor.agent.investigate import _lead_with_verdict
    f = {"interpretation": "Marion shows the highest average delay of the cities shown, and the "
                           "values are tightly clustered.", "is_significant": False}
    before = f["interpretation"]
    _lead_with_verdict(f, "This ordering is not evidence of a difference.")
    assert f["interpretation"] == before


def test_the_verdict_is_not_stacked_twice():
    from aughor.agent.investigate import _lead_with_verdict
    v = "This ordering is not evidence of a difference: the gaps are inside the spread."
    f = {"interpretation": f"{v} The phase narrator wrote: Oklahoma is significantly higher.",
         "is_significant": False}
    before = f["interpretation"]
    _lead_with_verdict(f, v)
    assert f["interpretation"] == before


# ── "not significant" may not stand in for "immaterial" ──────────────────────

def _significant_phase():
    return [{"phase_name": "Cross-Sectional", "findings": [{
        "sql": "SELECT 1", "columns": ["customer_city", "mean_value", "sd_value", "n_records"],
        "rows": [["Marion", "1.29", "1.4", "34"]], "row_count": 1, "error": None,
        "interpretation": "…", "trust_caveat": None, "key_numbers": [],
        "chart_type": "bar_horizontal", "is_significant": True,
        "stat_note": "one-way ANOVA F(562,179956) = 3.518, p = 2.376e-155, eta-squared = 0.0109"}]}]


def test_calling_an_overwhelmingly_significant_test_insignificant_is_a_violation():
    """The right conclusion under a false reason: "variations … are not significant
    (p > 0.05)" over a finding carrying p = 2.376e-155."""
    from aughor.agent.report_checks import run_report_checks
    synth = _Synth("Shipping delay is uniform across all customer locations",
                   "Variations across cities, states and regions are not significant (p > 0.05).")
    violations = run_report_checks(synth, "q", "evidence", _significant_phase())
    assert any("p = 2.38e-155" in v and "immaterial" in v for v in violations)


def test_saying_significant_but_immaterial_is_clean():
    from aughor.agent.report_checks import run_report_checks
    synth = _Synth("Location does not explain shipping delay",
                   "Customer city is statistically distinguishable but accounts for 1.1% of the "
                   "variation, too little to act on.")
    assert run_report_checks(synth, "q", "evidence", _significant_phase()) == []


def test_a_genuinely_null_run_may_say_not_significant():
    from aughor.agent.report_checks import run_report_checks
    phases = _significant_phase()
    phases[0]["findings"][0]["stat_note"] = "one-way ANOVA F(14,80) = 0.6357, p = 0.8274"
    synth = _Synth("No geographic effect", "The differences are not significant (p > 0.05).")
    assert run_report_checks(synth, "q", "evidence", phases) == []


# ── a narrator that AGREES with the verdict is left alone (run 5: `c88a3baf`) ─

#: The two live sentences the backstop wrongly "corrected" — both agree with their verdict.
_AGREEING = [
    "Across order regions, average shipping delays range from 0.65 days in Central Asia to "
    "0.56 days in South America. The variation across these regions is minimal and does not "
    "suggest a significant performance issue.",
    "Order states show a wider range of average shipping delays, from 3.2 days in Ilam to 2.2 "
    "days in Ecuatoria Central. However, these results are based on very small sample sizes and "
    "are not statistically significant, meaning no state stands out.",
    "The differences between these cities are statistically insignificant, indicating a tight "
    "and healthy distribution.",
    "There is no outlier here and no single driver of delay; nothing is a bottleneck.",
]


@pytest.mark.parametrize("text", _AGREEING)
def test_a_negated_claim_is_agreement_not_contradiction(text):
    """A substring scan flagged good reasoning as contamination — the failure this repo has
    hit before. The word `significant` under a negation is the narrator saying what the
    verdict says."""
    from aughor.agent.investigate import _lead_with_verdict, _makes_unnegated_standout_claim
    assert _makes_unnegated_standout_claim(text) is False
    f = {"interpretation": text, "is_significant": False}
    _lead_with_verdict(f, "This ordering is not evidence of a difference.")
    assert f["interpretation"] == text


@pytest.mark.parametrize("text", [
    "The significantly higher delay in Oklahoma suggests a localized performance issue.",
    "Ilam is a clear outlier and the main driver of delay.",
    "These states are bottlenecks; the variation is not small.",   # negation elsewhere, claim stands
])
def test_an_affirmative_claim_is_still_caught(text):
    from aughor.agent.investigate import _makes_unnegated_standout_claim
    assert _makes_unnegated_standout_claim(text) is True


# ── a LABEL is a word; the report check is about CLAIMS (run 6: `34932b1f`) ──

def _region_noise_phase():
    return [{"phase_name": "Cross-Sectional", "findings": [{
        "sql": "SELECT 1", "columns": ["Order Region", "metric_total", "sd", "n"],
        "rows": [["Central Asia", "0.65", "1.5", "553"], ["Central Africa", "0.64", "1.5", "1100"],
                 ["South Asia", "0.60", "1.5", "9000"]],
        "row_count": 15, "error": None, "interpretation": "…", "trust_caveat": None,
        "key_numbers": [], "chart_type": "bar_horizontal", "is_significant": False,
        "stat_note": ("This ordering is not evidence of a difference: the gaps between these "
                      "averages are inside the spread within each group (p = 0.1253).")}]}]


def test_naming_a_label_in_a_stable_range_is_not_a_violation():
    """The live sentence. It names Central Asia as one END of a range it calls stable — a
    description, not a standout claim. The old check matched the word and shipped a
    violation that no retry could clear, knocking a correct report from HIGH to MEDIUM."""
    from aughor.agent.report_checks import run_report_checks
    synth = _Synth("Shipping delays are consistent across all customer locations",
                   "Average delays remain stable, ranging from 0.56 days in South America to "
                   "0.65 days in Central Asia.")
    assert run_report_checks(synth, "q", "evidence", _region_noise_phase()) == []


def test_naming_the_same_label_as_a_bottleneck_still_is():
    from aughor.agent.report_checks import run_report_checks
    synth = _Synth("Central Asia is the regional bottleneck driving shipping delay",
                   "Central Asia is a clear outlier at 0.65 days.")
    violations = run_report_checks(synth, "q", "evidence", _region_noise_phase())
    assert any("Central Asia" in v for v in violations)


def test_the_claim_must_be_in_the_sentence_that_names_the_label():
    """A standout word elsewhere in the summary does not convict a label it never touches."""
    from aughor.agent.report_checks import run_report_checks
    synth = _Synth("Delays are uniform by region",
                   "Delays range from 0.56 days in South America to 0.65 days in Central Asia. "
                   "Separately, Second Class shipping is the significant driver of lateness.")
    assert run_report_checks(synth, "q", "evidence", _region_noise_phase()) == []
