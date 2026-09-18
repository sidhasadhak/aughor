"""A cached prompt token must not be counted as a fresh one.

Measured 2026-09-18, chasing "Agent mode is burning tokens": `run_tool_loop` is 42.7% of all
prompt tokens — 321 calls averaging 6,998 input. The cause looked obvious. Its fixed prefix
is ~8,208 tokens, 94% of it the 37 tool schemas, and the loop re-sends the whole prefix on
every turn; a median loop is 3 turns and the tail reaches 24.

Then the premise broke. `_extract_usage` reads `prompt_tokens` and nothing else, and a
provider counts a CACHED prompt token there exactly like a fresh one. Gemini — the live
binding — is an `auto_prefix` backend (`control_plane/inference.py`), which means that prefix
is very likely already served from cache. So 42.7% is a COUNT, and whether it is a COST was
unknowable: the platform had no way to tell a cache hit from a cache miss.

Trimming 37 tool schemas to fix a bill that may not be charged is work spent on nothing. So
the first change is to make the spend visible, not smaller.

`None` is load-bearing throughout. "The backend did not report a cache figure" and "nothing
was cached" are opposite facts, and folding them into 0 makes every rate lie — the same
distinction `_record_llm_call` already draws for `prompt_tokens`.
"""
import pytest

from aughor.llm.provider import _extract_cached_tokens
from aughor.obs.usage import rollup


class _Obj:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _raw(usage):
    return _Obj(usage=usage)


class TestTheThreeVocabularies:
    def test_openai_compatible(self):
        assert _extract_cached_tokens(
            _raw(_Obj(prompt_tokens_details=_Obj(cached_tokens=1234)))) == 1234

    def test_openai_compatible_as_a_dict(self):
        """Some clients hand the details back as a plain dict."""
        assert _extract_cached_tokens(
            _raw(_Obj(prompt_tokens_details={"cached_tokens": 99}))) == 99

    def test_anthropic(self):
        assert _extract_cached_tokens(_raw(_Obj(cache_read_input_tokens=777))) == 777

    def test_gemini(self):
        """The live binding, and the one the whole measurement hinged on."""
        assert _extract_cached_tokens(_raw(_Obj(cached_content_token_count=4096))) == 4096


class TestAgainstTheRealSdkShape:
    """Not a hand-rolled double: the actual `openai` model, because Gemini — the live
    binding — is served through its OpenAI-COMPATIBLE endpoint
    (`generativelanguage.googleapis.com/v1beta/openai/`), so this is the object shape the
    extractor will really meet."""

    def test_it_reads_a_real_CompletionUsage(self):
        from openai.types.completion_usage import CompletionUsage, PromptTokensDetails

        class Raw:
            usage = CompletionUsage(
                prompt_tokens=8208, completion_tokens=120, total_tokens=8328,
                prompt_tokens_details=PromptTokensDetails(cached_tokens=7900))
        assert _extract_cached_tokens(Raw()) == 7900

    def test_the_details_block_may_be_absent(self):
        """Gemini's compatibility layer is not obliged to send it. Absent must read as
        'did not say', never as a cold cache — that is the difference between 'we cannot
        tell' and 'the prefix costs full price'."""
        from openai.types.completion_usage import CompletionUsage

        class Raw:
            usage = CompletionUsage(prompt_tokens=8208, completion_tokens=120,
                                    total_tokens=8328)
        assert _extract_cached_tokens(Raw()) is None


class TestSilenceIsNotZero:
    def test_a_backend_that_says_nothing_returns_None(self):
        assert _extract_cached_tokens(_raw(_Obj())) is None

    def test_no_usage_at_all_returns_None(self):
        assert _extract_cached_tokens(_Obj(usage=None)) is None
        assert _extract_cached_tokens(_Obj()) is None

    def test_a_reported_zero_is_kept_as_zero(self):
        """A cold cache is a real measurement and must not read as 'unreported'."""
        assert _extract_cached_tokens(_raw(_Obj(cache_read_input_tokens=0))) == 0

    def test_a_junk_value_does_not_raise(self):
        assert _extract_cached_tokens(_raw(_Obj(cache_read_input_tokens="lots"))) is None


def _ev(prompt, cached=None):
    p = {} if cached is None else {"cached_tokens": cached}
    return {"kind": "llm_call", "provider": "gemini", "model": "m", "ok": True,
            "duration_ms": 1.0, "prompt_tokens": prompt, "completion_tokens": 10,
            "total_tokens": prompt + 10, "payload": p}


class TestTheReportSeparatesCountFromCost:
    def test_the_hit_rate_uses_only_calls_that_answered(self):
        """Two calls report, one is silent. The silent one must not drag the rate down —
        that is exactly how a well-cached binding would be made to look expensive."""
        row = rollup([_ev(8000, 7000), _ev(8000, 7500), _ev(1000)], axes=("model",)).rows[0]
        assert row.calls == 3 and row.calls_reporting_cache == 2
        assert row.cached_tokens == 14500
        assert row.cache_hit_rate == pytest.approx(14500 / 17000)

    def test_no_call_reporting_gives_None_not_zero(self):
        row = rollup([_ev(8000), _ev(8000)], axes=("model",)).rows[0]
        assert row.calls_reporting_cache == 0
        assert row.cache_hit_rate is None, "an unmeasured cache must not read as a cold one"

    def test_a_measured_cold_cache_is_zero_not_None(self):
        row = rollup([_ev(8000, 0)], axes=("model",)).rows[0]
        assert row.calls_reporting_cache == 1
        assert row.cache_hit_rate == 0.0

    def test_it_survives_a_json_encoded_payload(self):
        e = _ev(8000, 7000)
        e["payload"] = '{"cached_tokens": 7000}'
        row = rollup([e], axes=("model",)).rows[0]
        assert row.cached_tokens == 7000

    def test_the_rate_is_capped_at_one(self):
        """A provider reporting more cached than prompt tokens must not produce >100%."""
        row = rollup([_ev(100, 500)], axes=("model",)).rows[0]
        assert row.cache_hit_rate == 1.0

    def test_it_reaches_the_serialised_row(self):
        d = rollup([_ev(8000, 7000)], axes=("model",)).rows[0].to_dict()
        assert d["cached_tokens"] == 7000 and d["calls_reporting_cache"] == 1
        assert d["cache_hit_rate"] == pytest.approx(0.875)

    def test_existing_totals_are_unchanged(self):
        """Additive only: every figure the report already produced must be untouched."""
        row = rollup([_ev(8000, 7000), _ev(1000)], axes=("model",)).rows[0]
        assert row.prompt_tokens == 9000 and row.completion_tokens == 20
        assert row.calls == 2 and row.failures == 0
