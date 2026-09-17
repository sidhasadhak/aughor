"""IP-1 — the move into packages is UNCHANGED, measured.

`tests/fixtures/ip1_kb_parity.json` was measured on main `4c4358b6` with the PRE-MOVE loaders
reading `data/kb` — before a single file moved. Every number and digest in it is what the four
readers produced then: the plays the seeder builds (by kind and by industry, and their
content), the entries the retriever indexes (tiers, ids, embed text, payloads), the fact-table
stems the profiler derives, the curated industries (aliases, claimed files, metric recipes),
which industry owns which entry, and each industry's metric vocabulary.

These tests recompute all of it through the package resolver. A digest that moves is a move
that changed something — fix the move, never the fixture (it cannot be re-measured: the old
loaders are gone).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pytest

BASELINE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "ip1_kb_parity.json")
                      .read_text(encoding="utf-8"))


def _sha(lines) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def plays():
    from aughor.playbook import builder
    out = []
    for entry in builder._load_all_kb():
        if builder._has_causal_data(entry):
            out.extend(builder._build_entries_for_kb(entry))
    return out


def test_the_seeder_builds_the_same_plays(plays):
    from aughor.business_profile.metric_kb import kb_entry_industry
    from aughor.playbook.retriever import is_data_quality

    by = Counter()
    content = []
    for p in plays:
        kind = "data_quality" if is_data_quality(p) else "diagnostic"
        by[f"{kind}|{kb_entry_industry(p.source_kb_id) or 'shared'}"] += 1
        content.append(json.dumps({k: v for k, v in p.model_dump().items()
                                   if k not in ("id", "updated_at", "receipt")}, sort_keys=True))
    assert len(plays) == BASELINE["plays_total"] == 878
    assert dict(sorted(by.items())) == BASELINE["plays_by_kind_industry"]
    assert _sha(sorted(p.id.rsplit("_", 1)[0] for p in plays)) == BASELINE["play_keys_sha"]
    assert _sha(sorted(content)) == BASELINE["play_content_sha"]


def test_the_retriever_indexes_the_same_entries():
    from aughor.semantic.kb_loader import load_package_kb_entries

    entries = load_package_kb_entries()
    assert len(entries) == BASELINE["retriever_entries"]
    assert dict(sorted(Counter(str(e.tier) for e in entries).items())) == BASELINE["retriever_tiers"]
    digest = _sha(sorted(
        f"{e.source_file}::{e.pattern_id}::{e.tier}::"
        f"{hashlib.sha256(e.embed_text.encode()).hexdigest()}::{json.dumps(e.payload, sort_keys=True)}"
        for e in entries))
    assert digest == BASELINE["retriever_content_sha"]


def test_the_profiler_derives_the_same_fact_table_stems():
    """Compared as a SET: the alternation order of the old pattern followed an unsorted glob."""
    from aughor.tools.profiler import _build_fact_signals

    def stems(pattern: str) -> set[str]:
        inner = re.fullmatch(r"\^\((.*)\)", pattern).group(1)
        return {re.sub(r"\\(.)", r"\1", s) for s in inner.split("|")}

    assert stems(_build_fact_signals().pattern) == stems(BASELINE["fact_signal_pattern"])


def test_the_curated_industries_are_the_same():
    from aughor.business_profile.metric_kb import load_industry_kbs

    kbs = load_industry_kbs()
    got = {kb["id"]: {"industry": kb.get("industry"), "aliases": kb.get("aliases"),
                      "generic_aliases": kb.get("generic_aliases"),
                      "kb_files": kb.get("kb_files", []),
                      "metrics_sha": _sha([json.dumps(m, sort_keys=True) for m in kb.get("metrics", [])])}
           for kb in kbs}
    assert got == BASELINE["industry_kbs"]
    assert [kb["id"] for kb in kbs] == sorted(BASELINE["industry_kbs"])


def test_every_entry_belongs_to_the_same_industry():
    from aughor.business_profile.metric_kb import kb_entry_industry

    for entry_id, industry in BASELINE["entry_industry"].items():
        assert kb_entry_industry(entry_id) == industry, entry_id


def test_each_industrys_metric_vocabulary_is_the_same():
    from aughor.business_profile.metric_kb import metric_vocabulary

    for industry, digest in BASELINE["vocabulary_sha"].items():
        text = "" if industry == "_all" else industry
        assert _sha([json.dumps(t) for t in metric_vocabulary(text)]) == digest, industry
