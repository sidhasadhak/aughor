"""An industry text resolves to a curated KB by whole words, and a generic alias never lends its KB across industries.

The substring test this replaced gave "Retail Banking" the retail KB, "Telecommunications subscription" the SaaS
KB and "Online Travel Marketplace" the food-delivery KB (measured 2026-09-14 over 25 industry names). For an
industry no curated KB covers, nothing curated is better than another industry's recipes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import aughor.business_profile.store as profile_store
import aughor.orgsettings as orgsettings
from aughor.business_profile.metric_kb import (
    _UNCURATED_INDUSTRY_TERMS,
    _words,
    industry_id,
    industry_scope,
    kb_entry_industry,
    load_industry_kbs,
)

_KB_ROOT = Path(__file__).resolve().parents[2] / "data" / "kb"


@pytest.mark.parametrize("text, expected", [
    # a specific alias names the industry
    ("Commercial Aviation", "airline"),
    ("Airline / Commercial Aviation", "airline"),
    ("Freight Forwarding", "logistics"),
    ("Luxury Fashion E-commerce", "retail"),
    ("DTC/online retail (e-commerce) — B2C/B2B office products catalog", "retail"),
    ("SaaS / Subscription Software", "saas"),
    ("Food Delivery / On-Demand Marketplace", "food_delivery"),
    ("Manufacturing / Industrial Production", "manufacturing"),
    # a generic alias alone, and nothing names another industry
    ("Retail", "retail"),
    ("Grocery Retail", "retail"),
    ("Franchise Specialty Food Retail (global ingredient-sourced confectionery/snacks)", "retail"),
    # a generic alias beside an industry no KB covers: the measured wrong matches
    ("Retail Banking", ""),
    ("Telecommunications subscription", ""),
    ("Streaming Media subscription", ""),
    ("Online Travel Marketplace", ""),
    ("B2B Wholesale Marketplace", ""),
    # a generic alias two KBs share is a tie, and a tie abstains
    ("Online Marketplace", ""),
    ("Carrier", ""),
    # whole words only: "oem" is not in "poems"
    ("Poems", ""),
    ("", ""),
])
def test_industry_text_resolves_to_its_curated_kb(text, expected):
    assert industry_id(text) == expected


def _kbs() -> dict[str, dict]:
    return {kb["id"]: kb for kb in load_industry_kbs()}


def test_every_generic_alias_is_one_of_the_kbs_aliases():
    for kb_id, kb in _kbs().items():
        assert set(kb.get("generic_aliases", [])) <= set(kb.get("aliases", [])), kb_id


def test_no_uncurated_industry_word_is_a_specific_alias_of_a_curated_kb():
    """When a KB lands for one of those industries, its words move from the list into that KB's aliases."""
    uncurated = {tuple(_words(t)) for t in _UNCURATED_INDUSTRY_TERMS}
    for kb_id, kb in _kbs().items():
        generic = {tuple(_words(a)) for a in kb.get("generic_aliases", [])}
        specific = {tuple(_words(a)) for a in kb.get("aliases", [])} - generic
        assert not specific & uncurated, (kb_id, specific & uncurated)


def _entry_ids(path: Path) -> list[str]:
    data = json.loads(path.read_text())
    return [e["id"] for e in (data if isinstance(data, list) else [data]) if isinstance(e, dict) and e.get("id")]


def test_every_kb_file_an_industry_claims_exists_and_has_one_owner():
    owner: dict[str, str] = {}
    for kb_id, kb in _kbs().items():
        for stem in kb.get("kb_files", []):
            assert (_KB_ROOT / f"{stem}.json").is_file(), (kb_id, stem)
            assert stem not in owner, (stem, owner.get(stem), kb_id)
            owner[stem] = kb_id


def test_an_unclaimed_kb_file_carries_no_claimed_industry_prefix():
    """An ec_*.json no industry claims would reach every industry's playbook. The prefixes come from the
    claimed files' own entry ids, so the check holds no list of its own."""
    claimed = {stem for kb in _kbs().values() for stem in kb.get("kb_files", [])}
    prefixes = {i.split("_")[0] + "_" for stem in claimed for i in _entry_ids(_KB_ROOT / f"{stem}.json")}
    assert prefixes
    for path in sorted(_KB_ROOT.glob("*.json")):
        if path.stem not in claimed:
            stray = [i for i in _entry_ids(path) if any(i.startswith(p) for p in prefixes)]
            assert not stray, (path.name, stray[:3])


def test_a_kb_entry_belongs_to_the_industry_that_claims_its_file():
    assert kb_entry_industry("air_load_factor") == "airline"
    assert kb_entry_industry("ec_gmv") == "retail"
    assert kb_entry_industry("saas_mrr") == "saas"
    assert kb_entry_industry("fin_gross_margin") == ""      # a finance entry: every industry reads it
    assert kb_entry_industry(None) == ""


# ── industry_scope: which industry a connection reads ────────────────────────────────────────────────

@pytest.fixture
def stored(monkeypatch):
    """Point the scope at a stored profile industry and a declared org industry, without touching a store."""
    state = {"profiled": "", "declared": ""}
    monkeypatch.setattr(profile_store, "load_raw",
                        lambda conn, schema=None: {"profile": {"industry": state["profiled"]}})
    monkeypatch.setattr(orgsettings, "resolve_industry",
                        lambda profiled="", workspace_id=None: state["declared"] or profiled)
    return state


def test_scope_is_none_when_no_industry_is_known(stored):
    assert industry_scope("conn") is None


def test_scope_follows_the_stored_profile(stored):
    stored["profiled"] = "Luxury Fashion E-commerce"
    assert industry_scope("conn", "luxexperience") == "retail"


def test_a_declared_industry_wins_and_an_uncurated_one_scopes_to_shared_knowledge(stored):
    stored["profiled"] = "Luxury Fashion E-commerce"
    stored["declared"] = "Retail Banking"
    assert industry_scope("conn") == ""


def test_a_resolved_industry_skips_the_stores(monkeypatch):
    def _no_read(*a, **k):
        raise AssertionError("an explicit industry must not read the stores")
    monkeypatch.setattr(profile_store, "load_raw", _no_read)
    assert industry_scope("conn", industry="Commercial Aviation") == "airline"
    assert industry_scope("conn", industry="") is None


def test_a_failed_read_leaves_knowledge_unscoped(monkeypatch):
    def _broken(*a, **k):
        raise OSError("store unavailable")
    monkeypatch.setattr(profile_store, "load_raw", _broken)
    assert industry_scope("conn") is None
