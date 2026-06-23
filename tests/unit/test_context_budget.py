"""Capability-aware context budgeting — Layer A (§5b.3).

The load-bearing test is `test_large_window_is_byte_identical_to_today`: on the shipped
binding (a 131k window) the intake caps must equal the legacy constants exactly, so this
change is provably a no-op on the default config and only ever *tightens* for a small
BYO-model window — never a token or grounding regression on the real ADA path.
"""
from __future__ import annotations

from aughor.llm.context_budget import (
    estimate_tokens,
    input_budget_tokens,
    schema_scan_char_limits,
)

_DEFAULTS = (20_000, 6_000)  # the legacy _SCHEMA_CHAR_LIMIT / _SCAN_CHAR_LIMIT


class TestEstimate:
    def test_monotonic_and_conservative(self):
        assert estimate_tokens("") >= 1
        assert estimate_tokens("a" * 400) == 100          # 4 chars/token
        assert estimate_tokens("x" * 800) > estimate_tokens("x" * 400)


class TestInputBudget:
    def test_scales_with_window_and_reserves_output(self):
        small = input_budget_tokens(8_192)
        big = input_budget_tokens(131_072)
        assert big > small
        assert small < 8_192                                # leaves room for completion
        assert input_budget_tokens(8_192) == int((8_192 - 4_096) * 0.85)

    def test_tiny_window_floored(self):
        assert input_budget_tokens(100) >= 512              # never returns a useless budget


class TestSchemaScanLimits:
    def test_large_window_is_byte_identical_to_today(self):
        # THE invariant: the shipped 131k binding gets exactly the legacy caps → no-op.
        assert schema_scan_char_limits(131_072) == _DEFAULTS

    def test_never_looser_than_defaults(self):
        for ctx in (4_096, 8_192, 16_384, 32_768, 131_072, 1_000_000):
            s, sc = schema_scan_char_limits(ctx)
            assert s <= _DEFAULTS[0] and sc <= _DEFAULTS[1]   # safe direction only

    def test_small_window_tightens_and_keeps_ratio(self):
        s, sc = schema_scan_char_limits(8_192)
        assert s < _DEFAULTS[0] and sc < _DEFAULTS[1]          # fits the smaller window
        assert s > sc                                          # schema still bigger than scan
        # roughly preserves the 20k:6k ≈ 3.33 ratio
        assert 2.5 < (s / sc) < 4.5

    def test_floors_protect_a_minimal_payload(self):
        s, sc = schema_scan_char_limits(2_048)
        assert s >= 2_000 and sc >= 800

    def test_respects_caller_supplied_defaults(self):
        # When the caller passes the live constants, a large window echoes them back.
        assert schema_scan_char_limits(131_072, default_schema=18_000, default_scan=5_000) == (18_000, 5_000)
