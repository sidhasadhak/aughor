"""Phase 6 of the 2027 study (§P) — the kernel's industry-noun ratchet, and the kernel with no pack installed.

"What never enters the kernel: an industry noun — order, patient, loan, shipment." The test is one the repo
knows how to write (`test_vocabulary_ratchet.py`): a count of industry nouns in the kernel's source, at a
MEASURED baseline that may fall and never rise. A pack is data over one kernel and cannot add a store, a
screen type or a code path; the words of an industry live in packs and in the organisation's own
declarations, never in the code every industry runs.

The kernel, by the study's own list: the ledger and its envelope, the settle clock, the definition store,
the inquiry engine, decision and outcome records, the scenario ladder's interface, the action gateway and
authority, policy and the departure gate, the attention budget, scoring and calibration, principals and
grants, and the pack loader (the loader, its models and the map's matcher — not the packs).

Counting is by regex over the code with the ENGLISH and SQL senses stripped first ("ORDER BY", "in the
order it runs", "orders of magnitude", "a flag is a loan", "auto-promotion"), because a ratchet that fires
on a sort order gets silenced instead of fixed. What remains is the industry's word — an example in a
docstring counts too, and may be rewritten to lower the number; a baseline is lowered when a count is
lowered and never raised. A new noun is added at its measured count, with the phrases it is stripped of.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: The kernel's source, by the study's list. A directory is every .py under it; a file is itself.
KERNEL_ROOTS: tuple[str, ...] = (
    "aughor/kernel", "aughor/record", "aughor/govern", "aughor/actions", "aughor/settling", "aughor/rbac",
    "aughor/security", "aughor/packs/loader.py", "aughor/packs/models.py", "aughor/packs/priors.py",
    "aughor/packs/roots.py", "aughor/packs/ontology_map.py", "aughor/semantic/metrics.py",
)

#: The English and SQL senses stripped BEFORE counting, so the count is the industry's word alone.
_ENGLISH = re.compile(
    r"(?i)\border\s+by\b|\bin\s+(?:the\s+)?order\b|\border\s+of\b|\borders\s+of\s+magnitude\b|\bsort\s+order\b"
    r"|\bkey\s+order\b|\breplay\s+order\b|\binsertion\s+order\b|\bMRU\s+order\b|\bhint\s+order\b|\bpreference\s+order\b"
    r"|\bcatalog\s+order\b|\bdeterministic\s+order\b|\bstable\s+order\b|\bcaller'?s\s+order\b|\bseed\s+order\b"
    r"|\bthe\s+order\s+(?:it|they|is|matters)\b|\bthis\s+order\b|\bthe\s+same\s+order\b|\border\s+(?:matters|kept)\b"
    r"|\border-(?:stable|independent)\b|\bordered\b|\bordering\b|\border\s+to\s+try\b|\bgate'?s\s+order\b|\bone\s+order\b"
    r"|\border\s*=\s*\{|\border\.get\b"                       # a local named `order` holding a ranking
    r"|\bregistration\s+order\b|\btheir\s+order\b|\bpriority\s+order\b"
    r"|\bis\s+a\s+loan\b|\bauto-promotion\b|\bpromotion\.py\b|\bchurn\s+with\b|\bby-product\b|\bproduct\s+(?:behaviour|decision|name)\b"
    r"|\bthis\s+product\b|\bthe\s+product\b|\bproduct-of-sums\b|\bproduct'?s\s+own\b"
)

#: noun → the pattern counted after stripping. Spellings an industry uses for one thing count as one noun.
NOUNS: dict[str, str] = {
    "order": r"(?i)\borders?\b",
    "customer": r"(?i)\bcustomers?\b",
    "patient": r"(?i)\bpatients?\b",
    "loan": r"(?i)\bloans?\b",
    "shipment": r"(?i)\bshipments?\b",
    "invoice": r"(?i)\binvoices?\b",
    "product": r"(?i)\bproducts?\b",
    "sku": r"(?i)\bskus?\b",
    "refund": r"(?i)\brefunds?\b",
    "merchant": r"(?i)\bmerchants?\b",
    "carrier": r"(?i)\bcarriers?\b",
    "promotion": r"(?i)\bpromotions?\b",
    "deposit": r"(?i)\bdeposits?\b",
    "passenger": r"(?i)\bpassengers?\b",
    "revenue": r"(?i)\brevenues?\b",
    "gross margin": r"(?i)\bgross\s+margins?\b",
    "churn": r"(?i)\bchurn\w*\b",
}

#: Measured 2026-10-05 on `claude/platform-2027-study` with phase 6 built (order 25 · customer 3 · shipment 1 ·
#: product 1 · refund 5 · revenue 14 — docstrings, every one), and counted down the same day by the close-out's C8:
#: the executor's object-parameter examples, the overlay's annotation example, the gate's two live anchors, the
#: metric store's grain examples, the row-policy example and the settling anchors were reworded to the kernel's own
#: words (parent row, line, object, total). What remains is the one line in `packs/models.py` that names the
#: FUNCTION knowledge layers (finance, marketing, product, customer) — the layers' own ids, not an industry's word.
BASELINE: dict[str, int] = {
    "order": 0, "customer": 1, "patient": 0, "loan": 0, "shipment": 0, "invoice": 0, "product": 1, "sku": 0,
    "refund": 0, "merchant": 0, "carrier": 0, "promotion": 0, "deposit": 0, "passenger": 0, "revenue": 0,
    "gross margin": 0, "churn": 0,
}


def _repo_content() -> frozenset[str] | None:
    try:
        out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, text=True, timeout=60, check=True).stdout
    except Exception:  # noqa: BLE001 — no git: scan the tree
        return None
    return frozenset(p for p in out.split("\0") if p)


def kernel_files() -> list[tuple[str, Path]]:
    content = _repo_content()
    out: list[tuple[str, Path]] = []
    for root in KERNEL_ROOTS:
        base = REPO / root
        paths = [base] if base.is_file() else sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts) if base.is_dir() else []
        for p in paths:
            rel = p.relative_to(REPO).as_posix()
            if content is not None and rel not in content:
                continue
            out.append((rel, p))
    return out


def count(noun: str, files: list[tuple[str, Path]] | None = None) -> int:
    rx = re.compile(NOUNS[noun])
    return sum(len(rx.findall(_ENGLISH.sub(" ", path.read_text(errors="ignore")))) for _, path in (files or kernel_files()))


def where(noun: str, files: list[tuple[str, Path]] | None = None) -> dict[str, int]:
    rx = re.compile(NOUNS[noun])
    out = {}
    for rel, path in (files or kernel_files()):
        n = len(rx.findall(_ENGLISH.sub(" ", path.read_text(errors="ignore"))))
        if n:
            out[rel] = n
    return out


@pytest.fixture(scope="module")
def files() -> list[tuple[str, Path]]:
    return kernel_files()


def test_the_scan_reaches_the_kernel(files):
    assert len(files) > 60, f"only {len(files)} kernel files scanned — the walk is broken"
    assert any(rel.startswith("aughor/kernel/") for rel, _ in files) and any(rel.startswith("aughor/record/") for rel, _ in files)


def test_no_industry_noun_grew_in_the_kernel(files):
    """The ratchet. A noun that rose names where; lower it at the cause, never by raising the number."""
    grew = {}
    for noun, limit in BASELINE.items():
        now = count(noun, files)
        if now > limit:
            grew[noun] = (limit, now, where(noun, files))
    assert not grew, "\n".join(
        f"'{noun}' rose {was} → {now} in the kernel ({', '.join(f'{f} ×{n}' for f, n in sorted(spots.items(), key=lambda kv: -kv[1])[:5])}). "
        f"An industry's words live in a pack or in the organisation's declarations, never in the code every industry runs "
        f"(the 2027 study §P)."
        for noun, (was, now, spots) in sorted(grew.items()))


def test_baselines_are_not_stale(files):
    """A baseline above the real count buys room to regress: when a count falls, lower it in the same PR."""
    slack = {noun: (limit, count(noun, files)) for noun, limit in BASELINE.items() if limit - count(noun, files) > 3}
    assert not slack, "\n".join(f"'{noun}' baseline {was} but only {now} remain — lower it to {now}" for noun, (was, now) in sorted(slack.items()))


def test_every_noun_has_a_baseline():
    assert set(NOUNS) == set(BASELINE)


def test_the_ratchet_can_fire_and_the_english_senses_do_not(tmp_path):
    probe = "ORDER BY ts; in the order it runs; orders of magnitude; a flag is a loan; auto-promotion"
    assert all(len(re.compile(NOUNS[n]).findall(_ENGLISH.sub(" ", probe))) == 0 for n in ("order", "loan", "promotion"))
    industry = "the customer's order shipped; a refund on the loan; the carrier lost the shipment"
    assert sum(len(re.compile(NOUNS[n]).findall(_ENGLISH.sub(" ", industry))) for n in NOUNS) == 6


def test_the_kernel_runs_with_no_pack_installed(tmp_path, monkeypatch):
    """The study's other half of the test: the kernel passes with no pack installed — its doors answer,
    and say that nothing declared what to expect."""
    monkeypatch.setenv("AUGHOR_PACKS_DIR", str(tmp_path / "authored"))
    monkeypatch.setenv("AUGHOR_IMPORTED_PACKS_DIR", str(tmp_path / "imported"))
    from aughor.packs.roots import all_pack_ids
    assert all_pack_ids() == []
    from aughor.govern import attention
    from aughor.record import corrections, mission, scenario
    from aughor.packs import onboarding
    assert mission.bearing("conn-none", metric="revenue")["score"] == 0.0
    assert attention.score(kind="analysis", size=0.2)["terms"]["mission"] == 0.0
    assert scenario.project("identity", formula="a * b", inputs={"a": 2, "b": 3}).value == 6.0
    assert set(corrections.corrections(conn_id="conn-none")["counts"]) == set(corrections.KINDS)
    day_one = onboarding.onboarding("conn-none", "s", graph=None)
    assert day_one["packs"] == [] and day_one["shopping_list"] == [] and "no pack is bound" in day_one["shopping_note"]
    assert day_one["coverage"]["note"].startswith("no ontology is built")
