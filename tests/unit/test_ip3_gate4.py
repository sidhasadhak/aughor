"""IP-3 — gate 4: a package measured on a named public dataset, with no model.

Hermetic: the dataset is a 100-flight file in BTS's own column layout, zipped into a temporary cache, so nothing is
downloaded. The airline package is copied and pointed at it — its load statements, binding, formulas, detections
and ontology run unchanged — and every failure the gate names is planted once. The last tests hold the receipt
committed for the real BTS January 2019 file to the package it measured.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest
import yaml

from aughor.packs import gate4
from aughor.packs.gate3 import run_gate3
from aughor.packs.loader import load_pack

AIRLINE = Path(__file__).resolve().parents[2] / "packs" / "airline"
DATASET_ID = "bts-marketing-ontime-2019-01"
MEMBER = "synthetic_on_time.csv"
COLUMNS = ["FlightDate", "Marketing_Airline_Network", "Operating_Airline", "Tail_Number", "Origin", "Dest",
           "Cancelled", "CancellationCode", "Diverted", "ArrDel15"]


def _flights() -> list[dict]:
    """100 flights: AA 60 (2 cancelled, 1 diverted, 9 late), DL 40 (1 cancelled, 7 late).
    On time 80 of 100; cancelled 3; completion 97 of 100. AA on time 48/60, DL 32/40."""
    rows = []
    for carrier, count, cancelled, diverted, late in (("AA", 60, 2, 1, 9), ("DL", 40, 1, 0, 7)):
        for i in range(count):
            state = ("cancelled" if i < cancelled else "diverted" if i < cancelled + diverted
                     else "late" if i < cancelled + diverted + late else "on_time")
            rows.append({
                "FlightDate": f"2019-01-{(i % 28) + 1:02d}", "Marketing_Airline_Network": carrier,
                "Operating_Airline": carrier, "Tail_Number": "" if state == "cancelled" else f"N{i % 7}{carrier}",
                "Origin": ["JFK", "ATL", "ORD"][i % 3], "Dest": ["LAX", "SEA", "DFW"][i % 3],
                "Cancelled": "1.00" if state == "cancelled" else "0.00",
                "CancellationCode": "B" if state == "cancelled" else "",
                "Diverted": "1.00" if state == "diverted" else "0.00",
                "ArrDel15": "" if state in ("cancelled", "diverted") else ("1.00" if state == "late" else "0.00"),
            })
    return rows


GOLDENS = [
    {"question": "On time, all carriers?", "expect": {"metric": "on_time_arrival_rate", "dataset": DATASET_ID,
                                                      "value": 0.80, "tolerance": 0.0005, "source": "bts-atcr-2019-01"}},
    {"question": "Cancelled, all carriers?", "expect": {"metric": "cancellation_rate", "dataset": DATASET_ID,
                                                        "value": 0.03, "tolerance": 0.0005, "source": "bts-atcr-2019-01"}},
    {"question": "On time, DL?", "expect": {"metric": "on_time_arrival_rate", "dataset": DATASET_ID, "value": 0.80,
                                            "tolerance": 0.0005, "source": "bts-atcr-2019-01",
                                            "where": "{{role.flight.marketing_carrier}} = 'DL'"}},
]


@pytest.fixture()
def synthetic(tmp_path, monkeypatch):
    """The airline package, copied, measured on the synthetic file through a temporary cache."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(_flights())
    cache = tmp_path / "cache"
    archive = cache / DATASET_ID / "synthetic.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(MEMBER, buffer.getvalue())
    monkeypatch.setenv(gate4.CACHE_ENV, str(cache))

    pack_dir = tmp_path / "airline"
    shutil.copytree(AIRLINE, pack_dir, ignore=shutil.ignore_patterns("measurements"))
    dataset_file = pack_dir / "datasets" / f"{DATASET_ID}.yaml"
    dataset = yaml.safe_load(dataset_file.read_text(encoding="utf-8"))
    dataset.update(url="https://example.invalid/synthetic.zip", bytes=archive.stat().st_size, member=MEMBER,
                   sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    dataset_file.write_text(yaml.safe_dump(dataset, sort_keys=False), encoding="utf-8")
    (pack_dir / "evals" / "goldens.yaml").write_text(yaml.safe_dump(GOLDENS, sort_keys=False), encoding="utf-8")
    return pack_dir


def _edit(path: Path, change) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_the_package_is_measured_with_no_model(synthetic):
    pack = load_pack(synthetic)
    assert run_gate3(pack).ok
    report = gate4.run_gate4(pack)
    assert report.ok, report.findings
    assert report.rows == {"aircraft": 14, "airports": 6, "carriers": 2, "flights": 100}
    values = {m.metric: m.value for m in report.metrics}
    assert values == pytest.approx({"on_time_arrival_rate": 0.80, "cancellation_rate": 0.03, "completion_factor": 0.97})
    assert [(g.question, g.ok) for g in report.goldens] == [(g["question"], True) for g in GOLDENS]
    assert {d.play: d.count for d in report.detections} == {
        "cancellation-without-a-reason": 0, "cancelled-and-diverted-stay-in-the-denominator": 4,
        "late-flag-on-a-flight-that-never-arrived": 0}
    tiers = {(c["kind"], c["subject"]): c["tier"] for c in report.claims}
    assert tiers[("object", "Flight")] == "measured-true"
    assert tiers[("link", "Flight → Carrier")] == "measured-true"
    assert report.claims_by_tier["measured-false"] == 0


def test_a_golden_that_does_not_reproduce_its_figure_fails(synthetic):
    goldens = copy_goldens()
    goldens[2]["expect"]["value"] = 0.9
    (synthetic / "evals" / "goldens.yaml").write_text(yaml.safe_dump(goldens), encoding="utf-8")
    report = gate4.run_gate4(load_pack(synthetic))
    assert not report.ok
    assert any("On time, DL?" in f and "published 0.9" in f for f in report.findings)


def test_a_recipe_outside_its_sane_range_fails(synthetic):
    _edit(synthetic / "metrics" / "cancellation_rate.yaml", lambda m: m["sane_range"].update(min=0.04))
    report = gate4.run_gate4(load_pack(synthetic))
    assert any("metric cancellation_rate: measured 0.03" in f and "outside its sane range" in f
               for f in report.findings)


def test_a_detection_that_cannot_run_is_named(synthetic):
    _edit(synthetic / "datasets" / f"{DATASET_ID}.yaml",
          lambda d: d["binding"]["flight"]["columns"].pop("cancellation_code"))
    report = gate4.run_gate4(load_pack(synthetic))
    assert any(f.startswith("detection cancellation-without-a-reason: could not run") for f in report.findings)


def test_a_claim_the_data_contradicts_fails(synthetic):
    _edit(synthetic / "ontology.yaml", lambda o: o["links"][0].update(cardinality="1:1"))
    report = gate4.run_gate4(load_pack(synthetic))
    assert any(f.startswith("claim link Flight → Carrier: measured false") for f in report.findings)


def test_a_file_that_is_not_the_named_dataset_is_refused(synthetic):
    _edit(synthetic / "datasets" / f"{DATASET_ID}.yaml", lambda d: d.update(sha256="0" * 64))
    with pytest.raises(gate4.Gate4Error, match="has SHA-256"):
        gate4.run_gate4(load_pack(synthetic))


def test_nothing_is_downloaded_unless_asked(synthetic, tmp_path, monkeypatch):
    monkeypatch.setenv(gate4.CACHE_ENV, str(tmp_path / "empty-cache"))
    with pytest.raises(gate4.Gate4Error, match="run with --download"):
        gate4.run_gate4(load_pack(synthetic))


def copy_goldens() -> list[dict]:
    return json.loads(json.dumps(GOLDENS))


# ── the receipt committed for the real BTS January 2019 file ─────────────────────────────────────────────────

def test_the_airline_receipt_still_describes_the_package():
    """A change to a formula, a band, a golden, a play, the ontology or the dataset makes this fail until
    `aughor packs measure airline --write` is run again on the real file."""
    pack = load_pack(AIRLINE)
    receipt = gate4.read_receipt(pack, DATASET_ID)
    assert receipt is not None, "no receipt: run `aughor packs measure airline --download --write`"
    assert receipt["package_fingerprint"] == gate4.package_fingerprint(AIRLINE), \
        "the package changed since it was measured: run `aughor packs measure airline --write`"
    dataset = next(d for d in pack.datasets if d.id == DATASET_ID)
    assert receipt["dataset_sha256"] == dataset.sha256


def test_the_airline_receipt_passes_and_reproduces_every_published_figure():
    pack = load_pack(AIRLINE)
    receipt = gate4.read_receipt(pack, DATASET_ID)
    assert receipt["ok"] and receipt["findings"] == []
    assert receipt["rows"]["flights"] == 638649
    measured = {g["question"]: g for g in receipt["goldens"]}
    assert set(measured) == {g.question for g in pack.evals if g.expect.get("dataset") == DATASET_ID}
    assert all(g["ok"] and abs(g["measured"] - g["expected"]) <= g["tolerance"] for g in measured.values())
    dataset = next(d for d in pack.datasets if d.id == DATASET_ID)
    assert {m["metric"] for m in receipt["metrics"] if m["in_range"]} == set(dataset.measures)
    assert receipt["claims_by_tier"]["measured-false"] == 0


@pytest.mark.parametrize("package", sorted(
    p.parent for p in (Path(__file__).resolve().parents[2] / "packs").glob("*/pack.yaml")
    if int((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("anatomy") or 0) >= 1), ids=lambda p: p.name)
def test_every_anatomy_package_has_a_current_passing_receipt_for_each_dataset(package):
    pack = load_pack(package)
    fingerprint = gate4.package_fingerprint(package)
    for dataset in pack.datasets:
        receipt = gate4.read_receipt(pack, dataset.id)
        assert receipt is not None, f"{pack.id}: no receipt for {dataset.id} — run `aughor packs measure {pack.id} --write`"
        assert receipt["package_fingerprint"] == fingerprint, f"{pack.id}: {dataset.id} receipt is stale"
        assert receipt["dataset_sha256"] == dataset.sha256 and receipt["ok"], receipt["findings"]
