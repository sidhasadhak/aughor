"""IP-3 — gate 4: a package measured on a named public dataset, with no model (ROADMAP §3.17).

"(4) Measured on public data, no model: every recipe inside its sane range, every claim tiered, every detection
query run." Gate 3 holds what a package says; this measures it:

- **the dataset** — the file a `datasets/*.yaml` names is read from a cache outside the repository
  (`AUGHOR_DATASET_CACHE`, else `~/.cache/aughor/datasets/<id>/`), downloaded only when a caller asks, and refused
  unless its size and SHA-256 are the ones the package states. Its load statements build a DuckDB file.
- **the recipes** — each metric the dataset measures is compiled from its formula over role attributes, through
  the dataset's binding, into one `SELECT … FROM <the role's table>`; its value must sit inside the metric's sane
  range. No model writes this SQL: a formula is already an expression, and the binding only names columns.
- **the goldens** — each golden on the dataset is the same recipe with its filter; the value must reproduce the
  figure its source published, within the stated tolerance.
- **the detections** — each data-quality play's detection runs and returns a count. A count is exposure, not a
  defect; a detection that cannot run is a finding.
- **the claims** — the dataset's tables are profiled and built into a structural ontology exactly as a connection's
  are (no model: `extract_structural_ontology`, joins verified, cardinality and lifecycles measured), and the
  package's ontology claims are tiered on it by `apply_core_claims`. A claim the data measures false is a finding;
  an `expected` one is reported with the reason it could not be measured.

`run_gate4` returns a report; `write_receipt` stores it as `measurements/<dataset>.json` inside the package, keyed
to the package's fingerprint so CI can tell a receipt that still describes the package from a stale one.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aughor.packs.gate3 import ROLE_ATTRIBUTE, roles_named
from aughor.packs.models import Pack, PackDataset, PackMetric

CACHE_ENV = "AUGHOR_DATASET_CACHE"
RECEIPTS_DIR = "measurements"
#: The files a measurement depends on — a change to any of them makes a receipt stale.
ANATOMY_FILES = ("pack.yaml", "sources.yaml", "entities.yaml", "ontology.yaml", "questions.yaml")
ANATOMY_DIRS = ("metrics", "playbooks", "evals", "datasets")


class Gate4Error(Exception):
    """The measurement could not run: the dataset is missing, the wrong file, or cannot be loaded."""


@dataclass
class MetricMeasure:
    metric: str
    value: Optional[float]
    sane_min: Optional[float]
    sane_max: Optional[float]
    in_range: bool
    sql: str
    error: str = ""


@dataclass
class GoldenMeasure:
    question: str
    metric: str
    where: str
    expected: float
    tolerance: float
    measured: Optional[float]
    ok: bool
    source: str
    error: str = ""


@dataclass
class DetectionMeasure:
    play: str
    metric: str
    count: Optional[int]
    error: str = ""


@dataclass
class Gate4Report:
    pack_id: str
    dataset_id: str
    dataset_sha256: str
    package_fingerprint: str
    measured_at: str
    rows: dict = field(default_factory=dict)
    metrics: list[MetricMeasure] = field(default_factory=list)
    goldens: list[GoldenMeasure] = field(default_factory=list)
    detections: list[DetectionMeasure] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)
    claims_by_tier: dict = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def to_json(self) -> dict:
        return {**asdict(self), "ok": self.ok}


# ── the dataset ────────────────────────────────────────────────────────────────────────────────────────────

def cache_root() -> Path:
    override = os.environ.get(CACHE_ENV, "").strip()
    return Path(override) if override else Path.home() / ".cache" / "aughor" / "datasets"


def archive_path(dataset: PackDataset) -> Path:
    return cache_root() / dataset.id / Path(dataset.url.split("?")[0]).name


def sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def fetch(dataset: PackDataset, *, download: bool = False) -> Path:
    """The dataset's data file, from the cache — downloaded only when `download` is set — after checking the
    archive is the one the package names (size and SHA-256). Returns the extracted member's path."""
    archive = archive_path(dataset)
    if not archive.is_file():
        if not download:
            raise Gate4Error(f"{dataset.id}: {archive} is not in the cache — run with --download to fetch "
                             f"{dataset.url} ({dataset.bytes:,} bytes)")
        archive.parent.mkdir(parents=True, exist_ok=True)
        partial = archive.with_suffix(archive.suffix + ".part")
        with urllib.request.urlopen(dataset.url, timeout=120) as response, open(partial, "wb") as out:
            shutil.copyfileobj(response, out, 1 << 20)
        partial.replace(archive)
    size = archive.stat().st_size
    if dataset.bytes and size != dataset.bytes:
        raise Gate4Error(f"{dataset.id}: {archive} is {size:,} bytes; the package states {dataset.bytes:,}")
    checksum = sha256_of(archive)
    if checksum != dataset.sha256:
        raise Gate4Error(f"{dataset.id}: {archive} has SHA-256 {checksum}; the package states {dataset.sha256}")
    if not zipfile.is_zipfile(archive):
        return archive
    member = dataset.member
    target = archive.parent / member
    if not target.is_file():
        with zipfile.ZipFile(archive) as zf:
            if member not in zf.namelist():
                raise Gate4Error(f"{dataset.id}: the archive holds no {member!r}")
            zf.extract(member, archive.parent)
    return target


def build_database(dataset: PackDataset, data_path: Path, db_path: Path) -> dict:
    """Run the dataset's load statements into a fresh DuckDB file; returns each table's row count."""
    import duckdb

    if db_path.exists():
        db_path.unlink()
    literal = str(data_path).replace("'", "''")
    con = duckdb.connect(str(db_path))
    try:
        for statement in dataset.load:
            con.execute(statement.replace("{data}", literal))
        tables = [row[0] for row in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' ORDER BY 1").fetchall()]
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        con.close()


# ── compiling a package expression through a binding ─────────────────────────────────────────────────────────

def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def bind_expression(text: str, dataset: PackDataset) -> str:
    """A package expression with every `{{role.<role>.<attribute>}}` replaced by the bound column."""
    def column(match: re.Match) -> str:
        role, attribute = match.group(1), match.group(2)
        bound = dataset.binding.get(role)
        if bound is None or attribute not in bound.columns:
            raise Gate4Error(f"{dataset.id} does not bind {role}.{attribute}")
        return _quote(bound.columns[attribute])
    return ROLE_ATTRIBUTE.sub(column, text or "")


def role_table(text: str, dataset: PackDataset, *, fallback: str = "") -> str:
    roles = roles_named(text) or ({fallback} if fallback else set())
    if len(roles) != 1:
        raise Gate4Error(f"an expression must name exactly one role to be measured, found {sorted(roles)}")
    role = next(iter(roles))
    bound = dataset.binding.get(role)
    if bound is None:
        raise Gate4Error(f"{dataset.id} does not bind role {role!r}")
    return bound.table


def compile_metric(metric: PackMetric, dataset: PackDataset, where: str = "") -> str:
    table = role_table(metric.formula, dataset)
    sql = f"SELECT {bind_expression(metric.formula, dataset).strip()} AS value FROM {_quote(table)}"
    if where.strip():
        sql += f" WHERE {bind_expression(where, dataset).strip()}"
    return sql


# ── the gate ───────────────────────────────────────────────────────────────────────────────────────────────

def package_fingerprint(pack_dir: Path) -> str:
    """SHA-256 over the package's anatomy files (paths and bytes), so a receipt names the package it measured."""
    hasher = hashlib.sha256()
    files = [pack_dir / name for name in ANATOMY_FILES if (pack_dir / name).is_file()]
    for folder in ANATOMY_DIRS:
        files.extend(sorted((pack_dir / folder).glob("*.yaml")))
    for path in sorted(files, key=lambda p: p.relative_to(pack_dir).as_posix()):
        hasher.update(path.relative_to(pack_dir).as_posix().encode())
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def run_gate4(pack: Pack, dataset_id: str = "", *, download: bool = False) -> Gate4Report:
    """Measure `pack` on one of its datasets (the first when none is named)."""
    datasets = {d.id: d for d in pack.datasets}
    if not datasets:
        raise Gate4Error(f"{pack.id} names no dataset")
    dataset = datasets.get(dataset_id) if dataset_id else next(iter(datasets.values()))
    if dataset is None:
        raise Gate4Error(f"{pack.id} names no dataset {dataset_id!r}; it names {sorted(datasets)}")

    data_path = fetch(dataset, download=download)
    report = Gate4Report(pack_id=pack.id, dataset_id=dataset.id, dataset_sha256=dataset.sha256,
                         package_fingerprint=package_fingerprint(Path(pack.path)),
                         measured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    workdir = Path(tempfile.mkdtemp(prefix=f"aughor-gate4-{pack.id}-"))
    try:
        db_path = workdir / f"{dataset.id}.duckdb"
        try:
            report.rows = build_database(dataset, data_path, db_path)
        except Exception as exc:
            raise Gate4Error(f"{dataset.id}: its load statements failed: {exc}") from exc
        from aughor.db.connection import open_connection

        db = open_connection("duckdb", str(db_path), connection_id=f"gate4-{pack.id}")
        try:
            _measure_metrics(pack, dataset, db, report)
            _measure_goldens(pack, dataset, db, report)
            _run_detections(pack, dataset, db, report)
            _tier_claims(pack, db, report)
        finally:
            db.close()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return report


def receipt_path(pack: Pack, dataset_id: str) -> Path:
    return Path(pack.path) / RECEIPTS_DIR / f"{dataset_id}.json"


def write_receipt(pack: Pack, report: Gate4Report) -> Path:
    path = receipt_path(pack, report.dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_json(), indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path


def read_receipt(pack: Pack, dataset_id: str) -> Optional[dict]:
    path = receipt_path(pack, dataset_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


# ── the measurements ─────────────────────────────────────────────────────────────────────────────────────────

def _scalar(db, sql: str, label: str) -> Optional[float]:
    result = db.execute(label, sql)
    if result.error:
        raise Gate4Error(result.error)
    if not result.rows or result.rows[0][0] in (None, "NULL", ""):
        return None
    return float(result.rows[0][0])


def _measure_metrics(pack: Pack, dataset: PackDataset, db, report: Gate4Report) -> None:
    metrics = {m.name: m for m in pack.metrics}
    for name in dataset.measures:
        metric = metrics[name]
        band = metric.sane_range
        low, high = (band.min, band.max) if band else (None, None)
        sql, value, error = "", None, ""
        try:
            sql = compile_metric(metric, dataset)
            value = _scalar(db, sql, "__gate4_metric__")
        except Gate4Error as exc:
            error = str(exc)
        in_range = value is not None and (low is None or value >= low) and (high is None or value <= high)
        report.metrics.append(MetricMeasure(metric=name, value=value, sane_min=low, sane_max=high,
                                            in_range=in_range, sql=sql, error=error))
        if error:
            report.findings.append(f"metric {name}: could not be measured — {error}")
        elif not in_range:
            report.findings.append(f"metric {name}: measured {value} is outside its sane range [{low}, {high}]")


def _measure_goldens(pack: Pack, dataset: PackDataset, db, report: Gate4Report) -> None:
    metrics = {m.name: m for m in pack.metrics}
    for golden in pack.evals:
        expect = golden.expect or {}
        if expect.get("dataset") != dataset.id:
            continue
        where = str(expect.get("where") or "")
        measured, error = None, ""
        try:
            measured = _scalar(db, compile_metric(metrics[expect["metric"]], dataset, where), "__gate4_golden__")
        except Gate4Error as exc:
            error = str(exc)
        expected, tolerance = float(expect["value"]), float(expect["tolerance"])
        ok = measured is not None and abs(measured - expected) <= tolerance + 1e-12
        report.goldens.append(GoldenMeasure(question=golden.question, metric=expect["metric"], where=where,
                                            expected=expected, tolerance=tolerance, measured=measured, ok=ok,
                                            source=str(expect.get("source") or ""), error=error))
        if not ok:
            report.findings.append(f"golden {golden.question!r}: measured {measured} where the source published "
                                   f"{expected} (±{tolerance})" + (f" — {error}" if error else ""))


def _run_detections(pack: Pack, dataset: PackDataset, db, report: Gate4Report) -> None:
    for play in pack.playbooks:
        if not play.detection.strip():
            continue
        count, error = None, ""
        try:
            sql = (f"SELECT {bind_expression(play.detection, dataset).strip()} AS count "
                   f"FROM {_quote(role_table(play.detection, dataset))}")
            value = _scalar(db, sql, "__gate4_detection__")
            count = int(value) if value is not None else 0
        except Gate4Error as exc:
            error = str(exc)
        report.detections.append(DetectionMeasure(play=play.id, metric=play.trigger_metric, count=count, error=error))
        if error:
            report.findings.append(f"detection {play.id}: could not run — {error}")


def _tier_claims(pack: Pack, db, report: Gate4Report) -> None:
    if pack.ontology is None:
        return
    from aughor.db.schema_render import parse_schema_tables, render_raw_schema
    from aughor.ontology.builder import apply_join_verifications, extract_structural_ontology
    from aughor.ontology.cardinality import apply_cardinality_measurements
    from aughor.ontology.lifecycle import apply_lifecycle_measurements
    from aughor.packs.ontology_map import apply_core_claims
    from aughor.sql.join_guard import verify_join_edges
    from aughor.tools.profiler import profile_connection
    from aughor.tools.schema import compute_join_map

    label = f"gate4-{pack.id}"
    schema = render_raw_schema(db._conn, None, label)
    tables = parse_schema_tables(schema)
    join_map = compute_join_map(tables)
    fk_hints: dict[str, set] = {t: set() for t in tables}
    for join in join_map.get("joins", []):
        fk_hints.setdefault(join["t1"], set()).add(join["c1"])
    table_profiles, column_profiles = profile_connection(db, list(tables), fk_hints)
    graph = extract_structural_ontology(label, "main", report.dataset_sha256, table_profiles, column_profiles,
                                        join_map, {})
    verified, rejected = verify_join_edges(db, join_map.get("joins", []))
    apply_join_verifications(graph, verified, rejected)
    apply_cardinality_measurements(graph, db)
    apply_lifecycle_measurements(graph, db)
    claims = apply_core_claims(graph, pack.ontology, pack.id, db)
    report.claims_by_tier = claims.by_tier()
    for claim in claims.claims:
        report.claims.append({"kind": claim.kind, "subject": claim.subject, "tier": claim.tier,
                              "measured": getattr(claim, "measured", None), "note": claim.note})
        if claim.tier == "measured-false":
            report.findings.append(f"claim {claim.kind} {claim.subject}: measured false — {claim.note}")
