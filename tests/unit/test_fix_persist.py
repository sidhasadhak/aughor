"""Persist-a-fix helpers — see aughor/explorer/fix_persist.py.
(The full persist_fixed_finding path is DB+LLM integration, live-verified separately.)"""
from aughor.explorer.fix_persist import _parse_think, _is_domain_intel


def test_parse_phase8_think():
    d, a, q = _parse_think("Domain Finance | angle=receivables | What is the distribution of X?")
    assert d == "Finance"
    assert a == "receivables"
    assert q == "What is the distribution of X?"


def test_parse_think_with_retry_prefix():
    # the explorer labels retries "[retry 1] Domain ... | angle=... | ..."
    d, a, q = _parse_think("[retry 1] Domain Commerce | angle=volume | how many orders")
    assert d == "Commerce" and a == "volume" and q == "how many orders"


def test_parse_non_phase8_think():
    d, a, q = _parse_think("null check on orders.deleted_at")
    assert d is None and a is None and q == "null check on orders.deleted_at"


def test_parse_empty():
    assert _parse_think("") == (None, None, "")


def test_is_domain_intel_by_phase():
    assert _is_domain_intel("domain_intel", "") is True
    assert _is_domain_intel("domain_intelligence", "") is True


def test_is_domain_intel_by_think():
    assert _is_domain_intel("", "Domain X | angle=y | q") is True


def test_is_not_domain_intel():
    assert _is_domain_intel("null_meaning", "null check on t.c") is False
    assert _is_domain_intel("join_verification", "orphan check") is False
