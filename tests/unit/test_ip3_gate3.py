"""IP-3 — gate 3, the static gate: a package is held to its anatomy before anything measures it.

ROADMAP §3.17: "schema, a source per sane range, roles not tables, no alias collision, every play bound". Each test
plants one violation in an otherwise passing package and asserts the rule that names it fires — a gate proven only
on a passing package cannot fail.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from aughor.packs.gate3 import expression_findings, run_gate3
from aughor.packs.loader import PacksError, load_pack
from aughor.packs.validate import validate_pack

SHA = "a" * 64


def _package() -> dict:
    """A minimal package that passes gate 3 — every part the anatomy needs, one of each."""
    return {
        "pack.yaml": {"id": "rail", "name": "Rail", "anatomy": 1, "status": "draft"},
        "sources.yaml": {"sources": [{
            "id": "reg-2019", "title": "Rail punctuality 2019", "publisher": "The Rail Regulator",
            "url": "https://example.org/rail-2019", "published": "2020-02-01", "retrieved": "2026-09-17",
            "figures": [{"label": "Trains on time, 2019", "value": 91.2, "unit": "percent",
                         "quote": "91.2 percent of trains arrived on time"}]}]},
        "entities.yaml": {"roles": {"train": {"description": "a scheduled train service", "expects": {"kind": "event"},
                                              "attributes": {"late": {"type": "flag"},
                                                             "cancelled": {"type": "flag"},
                                                             "run_date": {"type": "date"}}}}},
        "metrics/punctuality.yaml": {
            "name": "punctuality", "title": "Punctuality", "unit": "ratio", "aliases": ["on-time rate"],
            "formula": "SUM(CASE WHEN {{role.train.late}} = 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0)",
            "binds": {"required": ["train"]},
            "sane_range": {"min": 0.8, "max": 0.97, "basis": "national operators, annual, 2019",
                           "sources": ["reg-2019"]}},
        "ontology.yaml": {"objects": [{"name": "Train"}, {"name": "Station"}],
                          "links": [{"from_object": "Train", "to_object": "Station", "cardinality": "N:1"}],
                          "lifecycles": [{"object": "Train", "states": ["scheduled", "arrived", "cancelled"],
                                          "terminal_states": ["arrived", "cancelled"]}]},
        "playbooks/late-trains.yaml": {"id": "punctuality-falls", "kind": "diagnostic",
                                       "trigger_metric": "punctuality",
                                       "trigger_condition": "punctuality falls",
                                       "recommendation": "Split late trains by cause.", "sources": ["reg-2019"]},
        "playbooks/impossible-late.yaml": {"id": "late-and-cancelled", "kind": "data_quality",
                                           "trigger_metric": "punctuality",
                                           "trigger_condition": "a cancelled train counted late",
                                           "recommendation": "Exclude cancelled trains from the late count.",
                                           "detection": "SUM(CASE WHEN {{role.train.cancelled}} = 1 AND "
                                                        "{{role.train.late}} = 1 THEN 1 ELSE 0 END)"},
        "questions.yaml": {"canonical": ["How punctual were trains last month?"], "intent_tags": ["punctuality"]},
        "evals/goldens.yaml": [{"question": "What was punctuality in 2019?",
                                "expect": {"metric": "punctuality", "dataset": "rail-2019", "value": 0.912,
                                           "tolerance": 0.001, "source": "reg-2019",
                                           "where": "{{role.train.run_date}} BETWEEN '2019-01-01' AND '2019-12-31'"}}],
        "datasets/rail-2019.yaml": {"id": "rail-2019", "title": "Train movements 2019", "source": "reg-2019",
                                    "url": "https://example.org/rail-2019.zip", "bytes": 1024, "sha256": SHA,
                                    "load": ["CREATE TABLE trains AS SELECT * FROM read_csv_auto('{data}')"],
                                    "binding": {"train": {"table": "trains",
                                                          "columns": {"late": "is_late", "cancelled": "is_cancelled",
                                                                      "run_date": "run_date"}}},
                                    "measures": ["punctuality"]},
    }


def _write(root: Path, files: dict) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
    return root


def _findings(tmp_path: Path, files: dict) -> list[str]:
    return run_gate3(load_pack(_write(tmp_path / "rail", files))).lines()


def test_a_package_with_every_part_passes(tmp_path):
    assert _findings(tmp_path, _package()) == []
    assert validate_pack(tmp_path / "rail").ok


def _mutate(path: str, change):
    files = _package()
    change(files[path] if path else files)
    return files


PLANTED = [
    ("no sane range", "metrics/punctuality.yaml", lambda m: m.pop("sane_range"),
     "[sane_range] metric punctuality: has no sane_range"),
    ("a band without a source", "metrics/punctuality.yaml", lambda m: m["sane_range"].update(sources=[]),
     "a band without a source fails"),
    ("a band citing an undeclared source", "metrics/punctuality.yaml",
     lambda m: m["sane_range"].update(sources=["blog"]), "cites 'blog', which sources.yaml does not declare"),
    ("a band with no basis", "metrics/punctuality.yaml", lambda m: m["sane_range"].update(basis=""),
     "has no basis"),
    ("no unit", "metrics/punctuality.yaml", lambda m: m.pop("unit"), "unit '' not in"),
    ("a formula naming a column", "metrics/punctuality.yaml",
     lambda m: m.update(formula="SUM(trains.is_late) / COUNT(*)"), "'trains' names a table or a column directly"),
    ("a formula reading a table", "metrics/punctuality.yaml",
     lambda m: m.update(formula="COUNT(*) FROM trains"), "'FROM' is not allowed"),
    ("an undeclared attribute", "metrics/punctuality.yaml",
     lambda m: m.update(formula="SUM({{role.train.delay_minutes}})"), "declares no attribute 'delay_minutes'"),
    ("a role the metric does not bind", "metrics/punctuality.yaml",
     lambda m: m["binds"].update(required=[]), "names role 'train', which the metric does not bind"),
    ("a bare template token", "metrics/punctuality.yaml",
     lambda m: m.update(formula="SUM({{role.train}})"), "is not a role attribute"),
    ("an alias shared by two metrics", "", lambda files: files.update({
        "metrics/cancellations.yaml": {**copy.deepcopy(files["metrics/punctuality.yaml"]), "name": "cancellations",
                                       "title": "Cancellations", "aliases": ["On time rate"]}}),
     "[alias_collision] metric punctuality: 'on-time rate' is also a name of metric 'cancellations'"),
    ("a play on an undeclared metric", "playbooks/late-trains.yaml",
     lambda p: p.update(trigger_metric="dwell_time"), "triggers on 'dwell_time', which is not a declared metric"),
    ("a play with no kind", "playbooks/late-trains.yaml", lambda p: p.pop("kind"), "kind '' not in"),
    ("a detection on a practice play", "playbooks/late-trains.yaml",
     lambda p: p.update(detection="COUNT(*)"), "only a data_quality play carries a detection"),
    ("a detection naming a column", "playbooks/impossible-late.yaml",
     lambda p: p.update(detection="SUM(is_cancelled)"), "'is_cancelled' names a table or a column directly"),
    ("a dataset without its checksum", "datasets/rail-2019.yaml", lambda d: d.update(sha256=""),
     "states no SHA-256"),
    ("a dataset that cannot measure what it claims", "datasets/rail-2019.yaml",
     lambda d: d["binding"]["train"]["columns"].pop("late"), "measures 'punctuality' but does not bind train.late"),
    ("a dataset binding an undeclared role", "datasets/rail-2019.yaml",
     lambda d: d["binding"].update(station={"table": "stations", "columns": {}}),
     "binds role 'station', which entities.yaml does not declare"),
    ("a golden without its source", "", lambda files: files["evals/goldens.yaml"][0]["expect"].pop("source"),
     "cites None, which sources.yaml does not declare"),
    ("a golden with no tolerance", "", lambda files: files["evals/goldens.yaml"][0]["expect"].pop("tolerance"),
     "states a tolerance of zero or more"),
    ("a golden filter naming a column", "",
     lambda files: files["evals/goldens.yaml"][0]["expect"].update(where="run_year = 2019"),
     "'run_year' names a table or a column directly"),
    ("a source with no retrieval date", "sources.yaml", lambda s: s["sources"][0].pop("retrieved"),
     "retrieved is not an ISO date"),
    ("a figure without its words", "sources.yaml", lambda s: s["sources"][0]["figures"][0].pop("quote"),
     "a figure needs a label, a value and the words it was published in"),
    ("no questions", "", lambda files: files.pop("questions.yaml"), "anatomy 1 needs questions.yaml"),
    ("a link to an undeclared object", "ontology.yaml",
     lambda o: o["links"].append({"from_object": "Train", "to_object": "Depot"}), "'Depot' is not a declared object"),
    ("a terminal state that is not a state", "ontology.yaml",
     lambda o: o["lifecycles"][0]["terminal_states"].append("scrapped"), "terminal states ['scrapped'] are not states"),
]


@pytest.mark.parametrize("label, path, change, expected", PLANTED, ids=[p[0] for p in PLANTED])
def test_each_rule_fires_on_its_planted_violation(tmp_path, label, path, change, expected):
    lines = _findings(tmp_path, _mutate(path, change))
    assert any(expected in line for line in lines), (label, lines)


def test_an_unquoted_yaml_date_is_read_as_the_date_it_names(tmp_path):
    root = _write(tmp_path / "rail", _package())
    text = (root / "sources.yaml").read_text(encoding="utf-8").replace("'2020-02-01'", "2020-02-01")
    (root / "sources.yaml").write_text(text, encoding="utf-8")
    assert load_pack(root).sources[0].published == "2020-02-01"
    assert run_gate3(load_pack(root)).ok


def test_a_pack_before_the_anatomy_is_not_held(tmp_path):
    files = _package()
    files["pack.yaml"]["anatomy"] = 0
    files.pop("sources.yaml")
    assert _findings(tmp_path, files) == []


def test_the_roster_reports_a_gate_failure(tmp_path):
    root = _write(tmp_path / "rail", _mutate("metrics/punctuality.yaml", lambda m: m.pop("sane_range")))
    report = validate_pack(root)
    assert not report.ok and any("has no sane_range" in e for e in report.errors)


def test_a_malformed_file_is_a_load_error_not_a_crash(tmp_path):
    files = _package()
    files["ontology.yaml"]["links"][0]["cardinality"] = "many"
    with pytest.raises(PacksError, match="invalid pack file"):
        load_pack(_write(tmp_path / "rail", files))


@pytest.mark.parametrize("expression, ok", [
    ("SUM({{role.train.late}}) / NULLIF(COUNT(*), 0)", True),
    ("AVG(CASE WHEN {{role.train.cancelled}} = 1 THEN 1.0 ELSE 0.0 END)", True),
    ("{{role.train.run_date}} >= DATE '2019-01-01'", True),
    ("COUNT(DISTINCT trains.id)", False),
    ("SUM({{role.train.late}}); DROP TABLE trains", False),
])
def test_an_expression_names_only_role_attributes_and_sql(tmp_path, expression, ok):
    pack = load_pack(_write(tmp_path / "rail", _package()))
    assert (expression_findings(expression, pack, "test") == []) is ok


# ── every shipped package that declares the anatomy — the population read from packs/, not listed here ────────

REPO_PACKS = Path(__file__).resolve().parents[2] / "packs"


def _anatomy_packages() -> list[Path]:
    found = []
    for manifest in sorted(REPO_PACKS.glob("*/pack.yaml")):
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        if int(data.get("anatomy") or 0) >= 1:
            found.append(manifest.parent)
    return found


def test_at_least_one_shipped_package_declares_the_anatomy():
    """Without this, the test below passes over an empty population."""
    assert [p.name for p in _anatomy_packages()], "no package in packs/ declares anatomy: 1"


@pytest.mark.parametrize("package", _anatomy_packages(), ids=lambda p: p.name)
def test_every_shipped_anatomy_package_passes_gate3(package):
    report = run_gate3(load_pack(package))
    assert report.ok, report.lines()
