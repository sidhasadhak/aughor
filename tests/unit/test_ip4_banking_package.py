"""IP-4 — the banking package measured with no model: its recipes are the FDIC's, held to hand-computed banks.

Hermetic: four banks in the FDIC BankFind API's own column layout, written to a temporary cache, so nothing is
downloaded. The banking package is copied and pointed at them — its load statements, binding, formulas, group filters
and detections run unchanged. Every expected value below was worked out by hand from the four rows, as the FDIC defines
the ratio: the numerators summed over the banks, divided by the summed denominators, a quarter's income times four.
The last test holds the receipt committed for the FDIC's real June 30, 2025 data to the package it measured.
"""
from __future__ import annotations

import csv
import hashlib
import io
import shutil
from pathlib import Path

import pytest
import yaml

from aughor.packs import gate4
from aughor.packs.gate3 import run_gate3
from aughor.packs.loader import load_pack

BANKING = Path(__file__).resolve().parents[2] / "packs" / "banking"
DATASET_ID = "fdic-financials-2025-q2"

# Amounts in thousands of dollars, as the FDIC reports them.
#   1  credit card bank, $12B at June 30 (the $10B–$250B band), averaging $10B over the quarter
#   2  commercial lender, $600M
#   3  commercial lender under $100M that grew from a $60M average to $90M, and recovered more than it charged off
#   4  mortgage lender whose average earning assets are missing although it earned interest
BANKS = [
    dict(CERT=1, SPECGRP=3, ASSET=12_000_000, ASSET2=10_000_000, ERNAST2=9_000_000, LNLSGR2=8_000_000, EQ2=1_200_000,
         INTINQ=180_000, EINTXQ=56_250, NONIIQ=60_000, NONIXQ=120_000, EAMINTQ=10_000, ELNATQ=50_000, NETINCQ=40_000,
         DRLNLSQ=70_000, CRLNLSQ=10_000, DEP=9_000_000, LNLSGR=8_400_000, LNLSNET=8_000_000, LNATRES=400_000,
         NCLNLS=140_000, P3LNLS=120_000, EQ=1_300_000),
    dict(CERT=2, SPECGRP=4, ASSET=600_000, ASSET2=600_000, ERNAST2=550_000, LNLSGR2=400_000, EQ2=60_000,
         INTINQ=8_250, EINTXQ=2_750, NONIIQ=1_000, NONIXQ=4_000, EAMINTQ=0, ELNATQ=200, NETINCQ=1_500,
         DRLNLSQ=300, CRLNLSQ=100, DEP=500_000, LNLSGR=410_000, LNLSNET=405_000, LNATRES=5_000,
         NCLNLS=4_000, P3LNLS=2_000, EQ=62_000),
    dict(CERT=3, SPECGRP=4, ASSET=90_000, ASSET2=60_000, ERNAST2=55_000, LNLSGR2=40_000, EQ2=9_000,
         INTINQ=825, EINTXQ=275, NONIIQ=100, NONIXQ=450, EAMINTQ=0, ELNATQ=20, NETINCQ=150,
         DRLNLSQ=10, CRLNLSQ=30, DEP=75_000, LNLSGR=45_000, LNLSNET=44_500, LNATRES=500,
         NCLNLS=400, P3LNLS=200, EQ=9_500),
    dict(CERT=4, SPECGRP=5, ASSET=2_000_000, ASSET2=2_000_000, ERNAST2=0, LNLSGR2=1_500_000, EQ2=180_000,
         INTINQ=20_000, EINTXQ=8_000, NONIIQ=2_000, NONIXQ=7_000, EAMINTQ=0, ELNATQ=100, NETINCQ=4_000,
         DRLNLSQ=200, CRLNLSQ=50, DEP=1_600_000, LNLSGR=1_500_000, LNLSNET=1_490_000, LNATRES=10_000,
         NCLNLS=8_000, P3LNLS=5_000, EQ=185_000),
]

# By hand. Interest income 209,075 less interest expense 67,275 is 141,800 a quarter, 567,200 a year, over 9,605,000 of
# average earning assets (bank 4's income counts; its missing balance does not — the data-quality play says so).
EXPECTED = {
    "net_interest_margin": 567_200 / 9_605_000,
    "yield_on_earning_assets": 836_300 / 9_605_000,
    "cost_of_funding_earning_assets": 269_100 / 9_605_000,
    "return_on_assets": 182_600 / 12_660_000,
    "return_on_equity": 182_600 / 1_449_000,
    "efficiency_ratio": 121_450 / 204_900,
    "net_charge_off_rate": 241_320 / 9_940_000,
    "noncurrent_loan_rate": 152_400 / 10_355_000,
    "past_due_and_nonaccrual_rate": 279_600 / 10_355_000,
    "reserve_coverage_ratio": 415_500 / 152_400,
    "loans_to_deposits_ratio": 9_939_500 / 11_175_000,
    "equity_capital_ratio": 1_556_500 / 14_690_000,
}

ROLE = "{{role.financial_period.%s}}"
GOLDENS = [
    {"question": "Net interest margin, all banks?",
     "expect": {"metric": "net_interest_margin", "dataset": DATASET_ID, "value": 0.05905, "tolerance": 0.00005,
                "source": "fdic-qbp-2025-q2"}},
    {"question": "Return on assets, commercial lenders?",   # (1,500 + 150) × 4 over 660,000
     "expect": {"metric": "return_on_assets", "dataset": DATASET_ID, "value": 0.01, "tolerance": 0.00005,
                "source": "fdic-qbp-2026-q2", "where": f"{ROLE % 'peer_group'} = '4'"}},
    {"question": "Equity capital ratio, banks under $100 million?",   # 9,500 over 90,000
     "expect": {"metric": "equity_capital_ratio", "dataset": DATASET_ID, "value": 0.1056, "tolerance": 0.00005,
                "source": "fdic-qbp-2026-q2", "where": f"{ROLE % 'total_assets'} < 100000"}},
    {"question": "Net charge-off rate, banks of $10 billion to $250 billion?",   # (70,000 − 10,000) × 4 over 8,000,000
     "expect": {"metric": "net_charge_off_rate", "dataset": DATASET_ID, "value": 0.03, "tolerance": 0.00005,
                "source": "fdic-qbp-2026-q2",
                "where": f"{ROLE % 'total_assets'} >= 10000000 AND {ROLE % 'total_assets'} <= 250000000"}},
]


def _edit(path: Path, change) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture()
def synthetic(tmp_path, monkeypatch):
    """The banking package, copied, measured on the four banks through a temporary cache."""
    columns = ["CERT", "REPDTE", "NAME", "BKCLASS", "SPECGRP", "SPECGRPDESC", *[k for k in BANKS[0] if k not in
                                                                              ("CERT", "SPECGRP")]]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, quoting=csv.QUOTE_NONNUMERIC)
    writer.writeheader()
    for bank in BANKS:
        writer.writerow({**bank, "REPDTE": 20250630, "NAME": f"Bank {bank['CERT']}", "BKCLASS": "NM",
                         "SPECGRPDESC": f"GROUP {bank['SPECGRP']}"})
    cache = tmp_path / "cache"
    data = cache / DATASET_ID / "financials"
    data.parent.mkdir(parents=True)
    data.write_text(buffer.getvalue(), encoding="utf-8")
    monkeypatch.setenv(gate4.CACHE_ENV, str(cache))

    pack_dir = tmp_path / "banking"
    shutil.copytree(BANKING, pack_dir, ignore=shutil.ignore_patterns("measurements"))
    _edit(pack_dir / "datasets" / f"{DATASET_ID}.yaml",
          lambda d: d.update(bytes=data.stat().st_size, sha256=hashlib.sha256(data.read_bytes()).hexdigest()))
    (pack_dir / "evals" / "goldens.yaml").write_text(yaml.safe_dump(GOLDENS, sort_keys=False), encoding="utf-8")
    return pack_dir


def test_the_banking_package_is_measured_with_no_model(synthetic):
    pack = load_pack(synthetic)
    assert run_gate3(pack).ok
    report = gate4.run_gate4(pack)
    assert report.ok, report.findings
    assert report.rows == {"call_reports": 4, "institutions": 4}
    assert {m.metric: m.value for m in report.metrics} == pytest.approx(EXPECTED)
    assert [(g.question, g.ok) for g in report.goldens] == [(g["question"], True) for g in GOLDENS]
    assert {d.play: d.count for d in report.detections} == {
        "income-without-an-average-balance": 1, "noncurrent-loans-above-the-loan-book": 0,
        "period-end-balance-read-as-the-average": 1, "recoveries-above-charge-offs-stay-in-the-sum": 1}
    tiers = {(c["kind"], c["subject"]): c["tier"] for c in report.claims}
    assert tiers[("object", "Institution")] == tiers[("object", "CallReport")] == "measured-true"
    assert report.claims_by_tier["measured-false"] == 0


def test_an_average_of_the_banks_margins_is_not_the_published_margin(synthetic):
    """The FDIC's ratio is a weighted average. Averaging each bank's own margin reads 4.50% on these banks, not 5.905%."""
    _edit(synthetic / "metrics" / "net_interest_margin.yaml", lambda m: m.update(formula=(
        f"AVG(({ROLE % 'interest_income'} - {ROLE % 'interest_expense'}) * {ROLE % 'periods_per_year'}"
        f" / NULLIF({ROLE % 'average_earning_assets'}, 0))")))
    report = gate4.run_gate4(load_pack(synthetic))
    assert any("Net interest margin, all banks?" in f and "published 0.05905" in f for f in report.findings)


def test_a_quarter_read_without_annualizing_fails_its_figure_and_its_band(synthetic):
    _edit(synthetic / "datasets" / f"{DATASET_ID}.yaml",
          lambda d: d.update(load=[s.replace("4 AS periods_per_year", "1 AS periods_per_year") for s in d["load"]]))
    report = gate4.run_gate4(load_pack(synthetic))
    assert any("Return on assets, commercial lenders?" in f for f in report.findings)
    assert any(f.startswith("metric net_interest_margin:") and "outside its sane range" in f for f in report.findings)


# ── the receipt committed for the FDIC's real June 30, 2025 data ────────────────────────────────────────────────

def test_the_banking_receipt_reproduces_every_published_figure():
    pack = load_pack(BANKING)
    receipt = gate4.read_receipt(pack, DATASET_ID)
    assert receipt is not None, "no receipt: run `aughor packs measure banking --write` on the cached FDIC file"
    assert receipt["package_fingerprint"] == gate4.package_fingerprint(BANKING), \
        "the package changed since it was measured: run `aughor packs measure banking --write`"
    assert receipt["ok"] and receipt["findings"] == []
    assert receipt["rows"] == {"call_reports": 4421, "institutions": 4421}
    measured = {g["question"]: g for g in receipt["goldens"]}
    assert set(measured) == {g.question for g in pack.evals} and len(measured) == 51
    assert all(g["ok"] and abs(g["measured"] - g["expected"]) <= g["tolerance"] for g in measured.values())
    dataset = next(d for d in pack.datasets if d.id == DATASET_ID)
    assert {m["metric"] for m in receipt["metrics"] if m["in_range"]} == set(dataset.measures)
    assert receipt["claims_by_tier"]["measured-false"] == 0
