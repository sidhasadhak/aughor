"""Unit tests for the semantic operators (aughor/semops) — text detection, filter, extract.

The LLM is replaced by a deterministic fake provider that parses the ``[index] text`` listing the
operator builds and applies a test-supplied python rule, so these assert the operator *plumbing*
(batching, row subsetting, column appending, cap refusal, fail-open) without any model call.
"""
from __future__ import annotations

import re

import pytest

from aughor.agent.state import QueryResult
from aughor.semops import operators as ops
from aughor.semops.operators import (
    _Aggregation,
    _ExtractBatch,
    _ExtractedRow,
    _FilterBatch,
    _RowScore,
    _RowVerdict,
    _ScoreBatch,
    apply_step,
    detect_text_columns,
    semantic_aggregate,
    semantic_extract,
    semantic_filter,
    semantic_top_k,
)

_LINE = re.compile(r"^\[(\d+)\]\s?(.*)$", re.M)


class FakeProvider:
    """Parses the operator's row listing and applies a python rule per row."""

    def __init__(self, *, filter_fn=None, extract_fn=None, score_fn=None, aggregate_fn=None, fail=False):
        self.filter_fn = filter_fn
        self.extract_fn = extract_fn
        self.score_fn = score_fn
        self.aggregate_fn = aggregate_fn
        self.fail = fail
        self.calls = 0

    def complete(self, *, system, user, response_model):
        self.calls += 1
        if self.fail:
            raise RuntimeError("simulated LLM failure")
        items = [(int(i), t) for i, t in _LINE.findall(user)]
        if response_model is _FilterBatch:
            return _FilterBatch(verdicts=[_RowVerdict(index=i, keep=bool(self.filter_fn(t))) for i, t in items])
        if response_model is _ExtractBatch:
            return _ExtractBatch(rows=[_ExtractedRow(index=i, values=self.extract_fn(t)) for i, t in items])
        if response_model is _ScoreBatch:
            return _ScoreBatch(scores=[_RowScore(index=i, score=float(self.score_fn(t))) for i, t in items])
        if response_model is _Aggregation:
            return _Aggregation(answer=self.aggregate_fn([t for _, t in items]))
        raise AssertionError(f"unexpected response_model {response_model!r}")


@pytest.fixture
def patch_provider(monkeypatch):
    def _install(provider: FakeProvider):
        monkeypatch.setattr(ops, "get_provider", lambda role=None: provider)
        return provider
    return _install


def _qr(columns, rows, *, row_count=None, error=None) -> QueryResult:
    return QueryResult(
        hypothesis_id="t", sql="SELECT 1", columns=columns, rows=rows,
        row_count=row_count if row_count is not None else len(rows), error=error,
    )


# ── text detection ─────────────────────────────────────────────────────────────

def test_detect_text_columns_picks_only_free_text():
    qr = _qr(
        ["id", "amount", "created_at", "note"],
        [
            ["1001", "42.50", "2026-06-15", "server is down, customers cannot log in"],
            ["1002", "8.00", "2026-06-14 09:30", "refund requested for late delivery"],
            ["1003", "100", "2026-06-13", "duplicate charge on the invoice"],
        ],
    )
    assert detect_text_columns(qr) == ["note"]


def test_detect_text_columns_skips_ids_and_empty():
    qr = _qr(["uuid", "blank"], [["a1b2c3d4e5f6a7b8", "NULL"], ["00112233445566778899", ""]])
    assert detect_text_columns(qr) == []


# ── filter ─────────────────────────────────────────────────────────────────────

def test_semantic_filter_keeps_only_matching_rows(patch_provider):
    patch_provider(FakeProvider(filter_fn=lambda t: "open" in t.lower()))
    qr = _qr(["note"], [["open: server down"], ["closed: resolved"], ["open: timeout"]])

    out = semantic_filter(qr, "note", "the ticket is still open")

    assert out.output_rows == 2
    assert out.result.rows == [["open: server down"], ["open: timeout"]]
    assert out.result.row_count == 2
    assert out.input_rows == 3
    assert out.llm_calls == 1
    assert out.truncated is False
    assert "kept 2 of 3" in out.notes[0]


def test_semantic_filter_batches(patch_provider):
    p = patch_provider(FakeProvider(filter_fn=lambda t: True))
    qr = _qr(["note"], [[f"row {i}"] for i in range(5)])

    out = semantic_filter(qr, "note", "anything", batch=2)

    assert out.output_rows == 5
    assert p.calls == 3  # ceil(5/2)


def test_semantic_filter_missing_column_is_noop(patch_provider):
    p = patch_provider(FakeProvider(filter_fn=lambda t: False))
    qr = _qr(["note"], [["x"]])

    out = semantic_filter(qr, "nope", "p")

    assert out.output_rows == 1            # unchanged
    assert p.calls == 0
    assert "not in the result" in out.notes[0]


def test_semantic_filter_refuses_over_cap(patch_provider):
    p = patch_provider(FakeProvider(filter_fn=lambda t: False))
    qr = _qr(["note"], [["a"], ["b"]], row_count=5000)  # true count far over the cap

    out = semantic_filter(qr, "note", "p", max_rows=200)

    assert out.truncated is True
    assert out.output_rows == 5000         # untouched
    assert p.calls == 0
    assert "exceeds the semantic-operator cap" in out.notes[0]


def test_semantic_filter_override_cap_processes(patch_provider):
    p = patch_provider(FakeProvider(filter_fn=lambda t: "keep" in t))
    qr = _qr(["note"], [["keep me"], ["drop me"]], row_count=5000)

    out = semantic_filter(qr, "note", "p", max_rows=1, override_cap=True)

    assert out.truncated is False
    assert out.output_rows == 1
    assert p.calls == 1
    # surfaced: only the materialized rows were processed
    assert any("materialized" in n for n in out.notes)


def test_semantic_filter_fail_open_on_llm_error(patch_provider):
    patch_provider(FakeProvider(fail=True))
    qr = _qr(["note"], [["a"], ["b"]])

    out = semantic_filter(qr, "note", "p")

    assert out.output_rows == 2            # nothing silently dropped
    assert out.llm_calls == 0
    assert any("failed" in n for n in out.notes)


def test_semantic_filter_fail_open_on_missing_verdict(patch_provider):
    # model returns verdicts only for even indices → odd rows must be kept (fail-open)
    class Partial(FakeProvider):
        def complete(self, *, system, user, response_model):
            self.calls += 1
            items = [(int(i), t) for i, t in _LINE.findall(user)]
            return _FilterBatch(verdicts=[_RowVerdict(index=i, keep=False) for i, t in items if i % 2 == 0])

    patch_provider(Partial())
    qr = _qr(["note"], [["r0"], ["r1"], ["r2"], ["r3"]])

    out = semantic_filter(qr, "note", "p")

    assert out.result.rows == [["r1"], ["r3"]]  # evens dropped, odds kept by fail-open


def test_semantic_filter_upstream_error_is_noop(patch_provider):
    p = patch_provider(FakeProvider(filter_fn=lambda t: True))
    qr = _qr([], [], error="syntax error near FROM")

    out = semantic_filter(qr, "note", "p")

    assert p.calls == 0
    assert "upstream SQL error" in out.notes[0]


# ── extract ────────────────────────────────────────────────────────────────────

def test_semantic_extract_appends_columns(patch_provider):
    patch_provider(FakeProvider(
        extract_fn=lambda t: {"severity": "high" if "down" in t else "low", "component": "db"}
    ))
    qr = _qr(["id", "note"], [["1", "server down"], ["2", "minor glitch"]])

    out = semantic_extract(qr, "note", [("severity", "how bad"), ("component", "subsystem")])

    assert out.result.columns == ["id", "note", "severity", "component"]
    assert out.result.rows[0] == ["1", "server down", "high", "db"]
    assert out.result.rows[1] == ["2", "minor glitch", "low", "db"]
    assert out.result.row_count == 2
    assert out.llm_calls == 1


def test_semantic_extract_uniquifies_colliding_field_name(patch_provider):
    patch_provider(FakeProvider(extract_fn=lambda t: {"note": "summary"}))
    qr = _qr(["note"], [["the full text"]])

    out = semantic_extract(qr, "note", [("note", "a summary")])

    assert out.result.columns == ["note", "note_2"]
    assert out.result.rows[0] == ["the full text", "summary"]


def test_semantic_extract_blank_on_llm_error(patch_provider):
    patch_provider(FakeProvider(fail=True))
    qr = _qr(["note"], [["x"], ["y"]])

    out = semantic_extract(qr, "note", [("a", ""), ("b", "")])

    assert out.result.columns == ["note", "a", "b"]
    assert out.result.rows[0] == ["x", "", ""]   # fields blank, original kept
    assert out.result.rows[1] == ["y", "", ""]


def test_semantic_extract_no_fields_is_noop(patch_provider):
    p = patch_provider(FakeProvider(extract_fn=lambda t: {}))
    qr = _qr(["note"], [["x"]])

    out = semantic_extract(qr, "note", [])

    assert p.calls == 0
    assert out.result.columns == ["note"]
    assert "no fields" in out.notes[0]


# ── apply_step dispatcher ────────────────────────────────────────────────────────

def test_apply_step_dispatches_filter(patch_provider):
    patch_provider(FakeProvider(filter_fn=lambda t: "keep" in t))
    qr = _qr(["note"], [["keep this"], ["drop that"]])

    out = apply_step(qr, "filter", "note", predicate="p")

    assert out.operator == "filter"
    assert out.result.rows == [["keep this"]]


def test_apply_step_dispatches_extract(patch_provider):
    patch_provider(FakeProvider(extract_fn=lambda t: {"k": "v"}))
    qr = _qr(["note"], [["x"]])

    out = apply_step(qr, "extract", "note", fields=[("k", "the k")])

    assert out.operator == "extract"
    assert out.result.columns == ["note", "k"]


def test_apply_step_unknown_operator_raises():
    qr = _qr(["note"], [["x"]])
    with pytest.raises(ValueError, match="unknown semantic operator"):
        apply_step(qr, "summarize", "note")


def test_apply_step_dispatches_top_k(patch_provider):
    patch_provider(FakeProvider(score_fn=lambda t: len(t)))
    qr = _qr(["note"], [["aa"], ["aaaa"], ["a"]])
    out = apply_step(qr, "top_k", "note", criterion="longest", k=2)
    assert out.operator == "top_k"
    assert out.result.rows == [["aaaa"], ["aa"]]


def test_apply_step_dispatches_aggregate(patch_provider):
    patch_provider(FakeProvider(aggregate_fn=lambda texts: f"{len(texts)} rows"))
    qr = _qr(["note"], [["a"], ["b"]])
    out = apply_step(qr, "aggregate", "note", instruction="count")
    assert out.operator == "aggregate"
    assert out.result.rows == [["2 rows"]]


# ── top_k ─────────────────────────────────────────────────────────────────────

def test_semantic_top_k_ranks_and_truncates(patch_provider):
    # score = text length → longest first
    patch_provider(FakeProvider(score_fn=lambda t: len(t)))
    qr = _qr(["note"], [["short"], ["the longest one here"], ["mid length"]])

    out = semantic_top_k(qr, "note", "longest", 2)

    assert out.output_rows == 2
    assert out.result.rows == [["the longest one here"], ["mid length"]]
    assert out.result.row_count == 2
    assert out.llm_calls == 1
    assert "kept top 2" in out.notes[0]


def test_semantic_top_k_k_ge_n_returns_all_sorted(patch_provider):
    patch_provider(FakeProvider(score_fn=lambda t: float(t)))
    qr = _qr(["note"], [["1"], ["3"], ["2"]])

    out = semantic_top_k(qr, "note", "biggest", 10)

    assert out.output_rows == 3
    assert out.result.rows == [["3"], ["2"], ["1"]]


def test_semantic_top_k_invalid_k_is_noop(patch_provider):
    p = patch_provider(FakeProvider(score_fn=lambda t: 1.0))
    qr = _qr(["note"], [["a"], ["b"]])

    out = semantic_top_k(qr, "note", "c", 0)

    assert out.output_rows == 2
    assert p.calls == 0
    assert "k must be >= 1" in out.notes[0]


def test_semantic_top_k_fail_open_scores_neutral(patch_provider):
    # batch fails → all rows neutral → original order preserved (stable), nothing dropped from contention
    patch_provider(FakeProvider(fail=True))
    qr = _qr(["note"], [["a"], ["b"], ["c"]])

    out = semantic_top_k(qr, "note", "x", 2)

    assert out.output_rows == 2
    assert out.result.rows == [["a"], ["b"]]   # stable top-2 of all-neutral
    assert any("failed" in n for n in out.notes)


def test_semantic_top_k_refuses_over_cap(patch_provider):
    p = patch_provider(FakeProvider(score_fn=lambda t: 1.0))
    qr = _qr(["note"], [["a"]], row_count=5000)

    out = semantic_top_k(qr, "note", "x", 5, max_rows=200)

    assert out.truncated is True
    assert p.calls == 0


# ── aggregate ─────────────────────────────────────────────────────────────────

def test_semantic_aggregate_synthesizes_one_row(patch_provider):
    patch_provider(FakeProvider(aggregate_fn=lambda texts: f"summary of {len(texts)}: " + "; ".join(texts)))
    qr = _qr(["note"], [["billing issue"], ["login bug"], ["billing again"]])

    out = semantic_aggregate(qr, "note", "summarize the themes")

    assert out.result.columns == ["answer"]
    assert out.result.row_count == 1
    assert out.result.rows[0][0].startswith("summary of 3:")
    assert out.input_rows == 3
    assert out.output_rows == 1
    assert out.llm_calls == 1


def test_semantic_aggregate_custom_out_column(patch_provider):
    patch_provider(FakeProvider(aggregate_fn=lambda texts: "ok"))
    qr = _qr(["note"], [["a"]])

    out = semantic_aggregate(qr, "note", "x", out_column="themes")

    assert out.result.columns == ["themes"]


def test_semantic_aggregate_fail_open_keeps_raw(patch_provider):
    patch_provider(FakeProvider(fail=True))
    qr = _qr(["note"], [["a"], ["b"]])

    out = semantic_aggregate(qr, "note", "x")

    assert out.result.rows == [["a"], ["b"]]    # raw result kept, not replaced
    assert out.llm_calls == 0
    assert any("aggregation failed" in n for n in out.notes)


def test_semantic_aggregate_missing_column_is_noop(patch_provider):
    p = patch_provider(FakeProvider(aggregate_fn=lambda texts: "x"))
    qr = _qr(["note"], [["a"]])

    out = semantic_aggregate(qr, "nope", "x")

    assert p.calls == 0
    assert "not in the result" in out.notes[0]


# ── Guarded extraction: deterministic value validation + gleaning re-extract ──────

@pytest.mark.parametrize("value,typ,valid", [
    ("2024", "year", True), ("24", "year", False), ("two thousand", "year", False), ("", "year", True),
    ("2024-01-31", "date", True), ("31/01/2024", "date", True), ("Jan 31, 2024", "date", True),
    ("sometime in 2024", "date", False), ("", "date", True),
    ("a@b.com", "email", True), ("not-an-email", "email", False),
    ("1,234.5", "number", True), ("$99", "number", True), ("42%", "number", True),
    ("a lot", "number", False), ("", "number", True),
])
def test_validate_value(value, typ, valid):
    assert (ops._validate_value(value, typ) is None) == valid


@pytest.mark.parametrize("name,desc,typ", [
    ("pub_year", "publication year", "year"),
    ("filed", "the date it was filed", "date"),
    ("contact", "customer email address", "email"),
    ("price", "listed price in dollars", "number"),
    ("summary", "a one-line description", None),   # untyped free text
])
def test_infer_expected_type(name, desc, typ):
    assert ops._infer_expected_type(name, desc) == typ


def test_guarded_extract_off_by_default_no_extra_calls(patch_provider):
    """validate=False (the default) is byte-identical to the un-guarded operator: one call, value kept."""
    p = patch_provider(FakeProvider(extract_fn=lambda t: {"pub_year": "long ago"}))
    qr = _qr(["blurb"], [["a classic novel"]])

    out = semantic_extract(qr, "blurb", [("pub_year", "publication year")])

    assert out.result.rows[0][-1] == "long ago"   # off-type value kept untouched
    assert p.calls == 1
    assert not any("guarded" in n for n in out.notes)


class _BadThenGood:
    """Returns an off-type value on the first extract, a corrected value on the re-extract round."""
    def __init__(self, bad, good, field):
        self.bad, self.good, self.field, self.calls = bad, good, field, 0

    def complete(self, *, system, user, response_model):
        self.calls += 1
        items = [(int(i), t) for i, t in re.findall(r"^\[(\d+)\]\s?(.*)$", user, re.M)]
        val = self.good if "WRONG format" in user else self.bad
        return _ExtractBatch(rows=[_ExtractedRow(index=i, values={self.field: val}) for i, _ in items])


def test_guarded_extract_reextracts_offtype_value(patch_provider):
    patch_provider(_BadThenGood(bad="two thousand", good="2024", field="pub_year"))
    qr = _qr(["blurb"], [["a classic novel"]])

    out = semantic_extract(qr, "blurb", [("pub_year", "publication year")], validate=True)

    assert out.result.rows[0][-1] == "2024"       # corrected by the gleaning round
    assert out.llm_calls == 2                      # initial + one re-extract
    assert any("re-extracted in 1 round" in n for n in out.notes)


def test_guarded_extract_bounds_rounds_and_keeps_value(patch_provider):
    """A value that never validates costs exactly max_rounds re-extracts and is surfaced, never dropped."""
    patch_provider(_BadThenGood(bad="nope", good="still nope", field="pub_year"))
    qr = _qr(["blurb"], [["x"]])

    out = semantic_extract(qr, "blurb", [("pub_year", "year")], validate=True, max_rounds=1)

    assert out.result.rows[0][-1] == "still nope"  # kept, not blanked
    assert out.llm_calls == 2                       # initial + exactly one bounded round
    assert any("still off-type" in n for n in out.notes)


def test_guarded_extract_empty_value_is_valid_no_reextract(patch_provider):
    """An absent (empty) field must never trigger a re-extract — we don't pressure invention."""
    p = patch_provider(FakeProvider(extract_fn=lambda t: {"pub_year": ""}))
    qr = _qr(["blurb"], [["no year here"]])

    out = semantic_extract(qr, "blurb", [("pub_year", "year")], validate=True)

    assert out.result.rows[0][-1] == ""
    assert p.calls == 1                              # no corrective round
    assert out.llm_calls == 1


def test_guarded_extract_untyped_field_skips_validation(patch_provider):
    """A purely textual field infers no type, so validate=True is a no-op (no extra calls)."""
    p = patch_provider(FakeProvider(extract_fn=lambda t: {"summary": "whatever"}))
    qr = _qr(["blurb"], [["some prose"]])

    out = semantic_extract(qr, "blurb", [("summary", "a short description")], validate=True)

    assert p.calls == 1
    assert not any("guarded" in n for n in out.notes)


def test_apply_step_threads_validate_flag(patch_provider):
    patch_provider(_BadThenGood(bad="two thousand", good="2024", field="pub_year"))
    qr = _qr(["blurb"], [["a novel"]])

    out = apply_step(qr, "extract", "blurb", fields=[("pub_year", "publication year")], validate=True)

    assert out.result.rows[0][-1] == "2024"
    assert out.llm_calls == 2


# ── Champion cascade on semantic_filter (Rec 5 / Palimpzest-LOTUS lineage) ─────────

def _patch_by_role(monkeypatch, cheap, champion):
    """get_provider('coder') -> champion, anything else -> cheap."""
    monkeypatch.setattr(ops, "get_provider", lambda role="fast", **kw: champion if role == "coder" else cheap)


def _alt_rows(n=10):
    """Rows where even indices say 'keep', odd say 'drop'."""
    return [[f"keep {i}"] if i % 2 == 0 else [f"drop {i}"] for i in range(n)]


def test_champion_cascade_off_by_default_no_champion_calls(monkeypatch):
    cheap = FakeProvider(filter_fn=lambda t: True)              # cheap keeps everything
    champ = FakeProvider(filter_fn=lambda t: "keep" in t)
    _patch_by_role(monkeypatch, cheap, champ)

    out = semantic_filter(_qr(["note"], _alt_rows()), "note", "keepers")   # validate_sample=0 default

    assert out.result.row_count == 10       # cheap verdict stands, byte-identical to before
    assert champ.calls == 0                  # champion never consulted


def test_champion_cascade_agreement_trusts_cheap(monkeypatch):
    cheap = FakeProvider(filter_fn=lambda t: "keep" in t)
    champ = FakeProvider(filter_fn=lambda t: "keep" in t)       # agrees with cheap on the sample
    _patch_by_role(monkeypatch, cheap, champ)

    out = semantic_filter(_qr(["note"], _alt_rows()), "note", "keepers", validate_sample=8)

    assert out.result.row_count == 5         # the correct "keep" rows
    assert champ.calls == 1                  # one sample-validation call, no escalation
    assert any("trusted" in n for n in out.notes)


def test_champion_cascade_disagreement_escalates(monkeypatch):
    cheap = FakeProvider(filter_fn=lambda t: True)             # cheap is wrong: keeps all
    champ = FakeProvider(filter_fn=lambda t: "keep" in t)      # champion is right
    _patch_by_role(monkeypatch, cheap, champ)

    out = semantic_filter(_qr(["note"], _alt_rows()), "note", "keepers", validate_sample=8)

    assert out.result.row_count == 5         # escalation applied the champion's correct verdicts
    assert champ.calls == 2                  # sample + full-batch escalation
    assert any("escalated" in n for n in out.notes)
