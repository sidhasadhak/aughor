"""A golden on a public dataset is reported from gate 4's receipt — never scored as passing unmeasured.

`check_expectation` skipped every expectation key it did not know, so IP-3's goldens (`metric`, `dataset`, `value`,
`tolerance`, `source`, `where`) scored as passing wherever the evaluate and status doors ran them: the packs screen
read 14 of 14 for airline and 51 of 51 for banking while nothing had been computed — and each one had cost a planner
pass on the connection first.

What holds now: the checker refuses a golden it cannot judge, the runner reads the receipt `aughor packs measure`
committed, and a receipt that is missing, stale or failing is reported as exactly that. The door downloads nothing,
builds nothing and calls no model.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from aughor.packs.evalrunner import check_expectation, run_pack_evals
from aughor.packs.loader import load_pack

PACKS = Path(__file__).resolve().parents[2] / "packs"
AIRLINE_DATASET = "bts-marketing-ontime-2019-01"


def _never_asked(question: str) -> dict:
    raise AssertionError(f"a golden on a public dataset must not reach the engine: {question}")


@pytest.fixture()
def airline(tmp_path) -> Path:
    shutil.copytree(PACKS / "airline", tmp_path / "airline")
    return tmp_path / "airline"


def _receipt_path(pack_dir: Path) -> Path:
    return pack_dir / "measurements" / f"{AIRLINE_DATASET}.json"


def test_the_shipped_goldens_report_what_gate_4_measured_and_never_reach_the_engine():
    for pack_id, count in (("airline", 14), ("banking", 51)):
        pack = load_pack(PACKS / pack_id)
        results = run_pack_evals(pack, _never_asked)
        assert len(results) == count
        assert all(r.passed for r in results), [r.detail for r in results if not r.passed]
        assert all("reproduced on" in r.detail and "by gate 4 on" in r.detail for r in results)


def test_a_golden_whose_figure_was_changed_is_not_reported_as_passing(airline):
    """The receipt is keyed to the package: edit what a golden claims was published and the receipt no longer
    describes this package, so the door says so instead of reporting a pass."""
    path = airline / "evals" / "goldens.yaml"
    goldens = yaml.safe_load(path.read_text(encoding="utf-8"))
    goldens[0]["expect"]["value"] = 0.99
    path.write_text(yaml.safe_dump(goldens, sort_keys=False), encoding="utf-8")

    results = run_pack_evals(load_pack(airline), _never_asked)
    assert not any(r.passed for r in results)
    assert all("the package changed since" in r.detail and "aughor packs measure airline" in r.detail
               for r in results)


def test_a_package_with_no_receipt_reports_that_and_names_the_command(airline):
    shutil.rmtree(airline / "measurements")
    results = run_pack_evals(load_pack(airline), _never_asked)
    assert not any(r.passed for r in results)
    assert all("carries no receipt" in r.detail and "aughor packs measure airline" in r.detail for r in results)


def test_a_figure_the_receipt_says_did_not_reproduce_is_not_a_pass(airline):
    receipt = json.loads(_receipt_path(airline).read_text(encoding="utf-8"))
    receipt["goldens"][0].update(ok=False, measured=0.5, error="")
    _receipt_path(airline).write_text(json.dumps(receipt), encoding="utf-8")

    results = run_pack_evals(load_pack(airline), _never_asked)
    failed = [r for r in results if not r.passed]
    assert len(failed) == 1
    assert "did not reproduce on" in failed[0].detail and "measured 0.5" in failed[0].detail


def test_a_question_the_receipt_does_not_carry_is_not_a_pass(airline):
    receipt = json.loads(_receipt_path(airline).read_text(encoding="utf-8"))
    receipt["goldens"] = receipt["goldens"][1:]
    _receipt_path(airline).write_text(json.dumps(receipt), encoding="utf-8")

    results = run_pack_evals(load_pack(airline), _never_asked)
    failed = [r for r in results if not r.passed]
    assert len(failed) == 1 and "does not carry this question" in failed[0].detail


def test_the_checker_refuses_every_expectation_it_cannot_judge():
    ok, detail = check_expectation({}, {"metric": "on_time_arrival_rate", "dataset": AIRLINE_DATASET,
                                        "value": 0.784, "tolerance": 0.0005, "source": "bts-atcr-2019-01"})
    assert not ok and "gate 4" in detail and AIRLINE_DATASET in detail

    ok, detail = check_expectation({"recipe_used": "retention"}, {"mood": "confident"})
    assert not ok and "'mood'" in detail

    # what an engine run does answer is still judged, both ways
    assert check_expectation({"recipe_used": "retention"}, {"uses_recipe": "retention"}) == (True, "")
    assert not check_expectation({"recipe_used": "churn"}, {"uses_recipe": "retention"})[0]
