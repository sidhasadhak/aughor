"""Metric-feasibility gate — don't narrate a verdict from a metric the connection can't support.

The class: a profitability question on cost-less TPC-H fabricated a 0% margin and concluded
"we are not losing money"; an efficiency question on a marketing table with no conversions
asserted "TikTok worst efficiency" from a meaningless cost-per-row. These pin the gate: it
must FLAG the unsupported case and stay SILENT when the required column class IS present."""
from aughor.semantic.metric_feasibility import unsupported_metric_gap as gap


class TestProfitability:
    def test_no_cost_column_flags(self):
        assert gap("where are we losing money?", ["region", "revenue", "orders"])

    def test_margin_question_no_cost_flags(self):
        assert gap("what is our profit margin by product?", ["product", "sales"])

    def test_has_cost_column_silent(self):
        assert gap("where are we losing money?", ["region", "revenue", "cogs_usd", "gross_margin_usd"]) is None

    def test_plain_revenue_question_silent(self):
        assert gap("total revenue by region", ["region", "revenue"]) is None

    def test_volume_question_silent(self):
        assert gap("how many orders per month?", ["order_id", "order_date"]) is None


class TestEfficiency:
    def test_spend_without_outcome_flags(self):
        assert gap("which channel has the worst efficiency?", ["channel", "spend_usd"])

    def test_roi_without_spend_flags(self):
        assert gap("channel ROI", ["channel", "revenue", "conversions"])

    def test_has_spend_and_outcome_silent(self):
        assert gap("channel ROI", ["channel", "spend_usd", "revenue"]) is None


class TestRobustness:
    def test_accepts_schema_text(self):
        # the gate also accepts a raw schema string
        schema = "TABLE: orders\n  region  VARCHAR\n  revenue  NUMERIC\n"
        assert gap("where are we losing money?", schema)  # no cost token → flag

    def test_empty_inputs_never_raise(self):
        assert gap("", ["cost"]) is None
        assert gap("profit?", []) is not None or gap("profit?", []) is None  # just must not raise
        assert gap(None, None) is None
