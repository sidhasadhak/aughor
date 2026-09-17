"""IP-3 — gate 3, the static gate: what a package must be before anything measures it (ROADMAP §3.17).

"(3) The static gate, in CI: schema, a source per sane range, roles not tables, no alias collision, every play
bound." It holds a package that declares `anatomy: 1` in pack.yaml; a pack written before the anatomy (anatomy 0) is
not held to it. No connection, no network, no model — the loaded files only.

The rules, each a `Finding.rule`:

- **anatomy** — every part is there: cited sources, entity roles with attributes, metrics, an ontology, plays,
  questions, goldens and at least one named dataset to measure on.
- **sources** — a source has an id, a title, a publisher, an http(s) url, and ISO dates for when it was published and
  when it was read; a figure it publishes carries the words it was published in.
- **sane_range** — every metric states its unit and a band with a lower or upper bound, the population and period
  it holds for, and at least one declared source. A band without a source fails (§3.17's law).
- **roles_not_tables** — a formula, a golden's filter and a play's detection are expressions over
  `{{role.<role>.<attribute>}}` and SQL's functions and keywords only: any other name is a table or a column the
  package would be naming directly, and `FROM`, `JOIN`, `SELECT` and `;` are refused outright — a dataset's binding
  supplies the table. Every role a formula names is one the metric binds. `datasets/*.yaml` is the one place a
  package names tables.
- **alias_collision** — no two metrics share a name, a title or an alias once case and punctuation are dropped.
- **plays_bound** — every play has an id and a kind, triggers on a declared metric, and cites declared sources.
- **goldens** — a golden on a dataset names a declared metric and dataset, a numeric value and tolerance in the
  metric's unit, and the source that published the value.
- **datasets** — a dataset cites its source, states where it comes from, its size and its SHA-256, binds only
  declared roles and attributes, and binds every attribute of every metric it says it measures.
- **ontology** — a link or lifecycle names an object the ontology declares.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from aughor.packs.models import ATTRIBUTE_TYPES, METRIC_UNITS, PLAY_KINDS, Pack

#: A role attribute in a package expression.
ROLE_ATTRIBUTE = re.compile(r"\{\{\s*role\.([a-z0-9_]+)\.([a-z0-9_]+)\s*\}\}", re.I)
_ANY_TOKEN = re.compile(r"\{\{[^}]*\}\}")
_STRING = re.compile(r"'(?:[^']|'')*'")
_IDENTIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_REFUSED = re.compile(r"\b(FROM|JOIN|SELECT|WITH|UNION|INSERT|UPDATE|DELETE|CREATE|DROP|ATTACH|COPY|PRAGMA)\b|;", re.I)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

#: The SQL words an expression over role attributes may use: aggregates, scalar functions, CASE, comparisons, casts
#: and date parts. Anything else is a name the package would be reading from a table.
SQL_WORDS = frozenset(w.upper() for w in """
    SUM COUNT AVG MIN MAX MEDIAN STDDEV STDDEV_SAMP STDDEV_POP VARIANCE QUANTILE_CONT PERCENTILE_CONT
    NULLIF COALESCE GREATEST LEAST ABS ROUND FLOOR CEIL CEILING LN LOG EXP POWER SQRT
    CASE WHEN THEN ELSE END AND OR NOT IS NULL IN LIKE ILIKE BETWEEN DISTINCT FILTER WHERE TRUE FALSE
    CAST TRY_CAST AS DOUBLE FLOAT REAL INTEGER INT BIGINT DECIMAL NUMERIC VARCHAR TEXT DATE TIME TIMESTAMP BOOLEAN
    EXTRACT EPOCH YEAR QUARTER MONTH WEEK DAY HOUR MINUTE SECOND INTERVAL DATE_TRUNC DATE_PART DATE_DIFF DATEDIFF
    STRFTIME STRPTIME LOWER UPPER TRIM LENGTH SUBSTRING
""".split())


@dataclass(frozen=True)
class Finding:
    rule: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.where}: {self.message}"


@dataclass
class Gate3Report:
    pack_id: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def lines(self) -> list[str]:
        return [str(f) for f in self.findings]


def applies(pack: Pack) -> bool:
    """Whether the static gate holds this pack: it declares the IP-3 anatomy."""
    return (pack.manifest.anatomy or 0) >= 1


def run_gate3(pack: Pack) -> Gate3Report:
    """Every finding for a loaded pack that declares the anatomy (none for one that does not)."""
    report = Gate3Report(pack_id=pack.id)
    if not applies(pack):
        return report
    add = report.findings.append
    source_ids = _check_sources(pack, add)
    _check_anatomy(pack, add)
    metric_roles = _check_metrics(pack, source_ids, add)
    _check_aliases(pack, add)
    _check_plays(pack, source_ids, add)
    dataset_ids = _check_datasets(pack, source_ids, metric_roles, add)
    _check_goldens(pack, source_ids, dataset_ids, add)
    _check_ontology(pack, add)
    return report


def expression_findings(text: str, pack: Pack, where: str, *, allowed_roles: Iterable[str] | None = None) -> list[Finding]:
    """What is wrong with an expression over role attributes — empty when it names only declared role attributes
    and SQL words. `allowed_roles` narrows the roles it may name (a metric's bound roles)."""
    findings: list[Finding] = []
    body = _STRING.sub(" ", text or "")
    if _REFUSED.search(body):
        findings.append(Finding("roles_not_tables", where, f"{_REFUSED.search(body).group(0)!r} is not allowed — a "
                                                           f"dataset's binding supplies the table"))
    allowed = set(allowed_roles) if allowed_roles is not None else None
    for token in _ANY_TOKEN.findall(body):
        match = ROLE_ATTRIBUTE.fullmatch(token)
        if not match:
            findings.append(Finding("roles_not_tables", where, f"{token} is not a role attribute "
                                                               f"({{{{role.<role>.<attribute>}}}})"))
            continue
        role, attribute = match.group(1), match.group(2)
        spec = pack.entities.get(role)
        if spec is None:
            findings.append(Finding("roles_not_tables", where, f"role {role!r} is not declared in entities.yaml"))
        elif attribute not in spec.attributes:
            findings.append(Finding("roles_not_tables", where, f"role {role!r} declares no attribute {attribute!r}"))
        elif allowed is not None and role not in allowed:
            findings.append(Finding("roles_not_tables", where, f"names role {role!r}, which the metric does not bind"))
    for word in _IDENTIFIER.findall(_ANY_TOKEN.sub(" ", body)):
        if word.upper() not in SQL_WORDS:
            findings.append(Finding("roles_not_tables", where, f"{word!r} names a table or a column directly — "
                                                               f"name a role attribute instead"))
    return findings


def roles_named(text: str) -> set[str]:
    return {m.group(1) for m in ROLE_ATTRIBUTE.finditer(text or "")}


# ── the rules ──────────────────────────────────────────────────────────────────────────────────────────────

def _check_anatomy(pack: Pack, add) -> None:
    missing = [part for part, present in (
        ("sources.yaml", bool(pack.sources)),
        ("entities.yaml roles", bool(pack.entities)),
        ("metrics/*.yaml", bool(pack.metrics)),
        ("ontology.yaml", pack.ontology is not None and bool(pack.ontology.objects)),
        ("playbooks/*.yaml", bool(pack.playbooks)),
        ("questions.yaml", bool(pack.questions.canonical or pack.questions.intent_tags)),
        ("evals/*.yaml", bool(pack.evals)),
        ("datasets/*.yaml", bool(pack.datasets)),
    ) if not present]
    for part in missing:
        add(Finding("anatomy", "pack", f"anatomy 1 needs {part}"))
    for name, role in pack.entities.items():
        if not role.attributes:
            add(Finding("anatomy", f"role {name}", "declares no attributes — a formula cannot name it"))
        for attribute, spec in role.attributes.items():
            if spec.type not in ATTRIBUTE_TYPES:
                add(Finding("anatomy", f"role {name}.{attribute}", f"type {spec.type!r} not in {ATTRIBUTE_TYPES}"))


def _check_sources(pack: Pack, add) -> set[str]:
    ids: set[str] = set()
    for source in pack.sources:
        where = f"source {source.id or '?'}"
        if not source.id:
            add(Finding("sources", where, "has no id"))
            continue
        if source.id in ids:
            add(Finding("sources", where, "id is declared twice"))
        ids.add(source.id)
        for key in ("title", "publisher"):
            if not (getattr(source, key) or "").strip():
                add(Finding("sources", where, f"has no {key}"))
        if not re.match(r"^https?://\S+$", source.url or ""):
            add(Finding("sources", where, "has no http(s) url"))
        for key in ("published", "retrieved"):
            if not _iso_date(getattr(source, key)):
                add(Finding("sources", where, f"{key} is not an ISO date (YYYY-MM-DD)"))
        for figure in source.figures:
            if not figure.label.strip() or figure.value is None or not figure.quote.strip():
                add(Finding("sources", where, "a figure needs a label, a value and the words it was published in"))
    return ids


def _check_metrics(pack: Pack, source_ids: set[str], add) -> dict[str, set[str]]:
    roles_by_metric: dict[str, set[str]] = {}
    for metric in pack.metrics:
        where = f"metric {metric.name or '?'}"
        if metric.unit not in METRIC_UNITS:
            add(Finding("sane_range", where, f"unit {metric.unit!r} not in {METRIC_UNITS}"))
        band = metric.sane_range
        if band is None:
            add(Finding("sane_range", where, "has no sane_range"))
        else:
            if band.min is None and band.max is None:
                add(Finding("sane_range", where, "sane_range has neither a min nor a max"))
            if band.min is not None and band.max is not None and band.min > band.max:
                add(Finding("sane_range", where, f"sane_range min {band.min} is above max {band.max}"))
            if not band.basis.strip():
                add(Finding("sane_range", where, "sane_range has no basis (the population and period it holds for)"))
            if not band.sources:
                add(Finding("sane_range", where, "sane_range cites no source — a band without a source fails"))
            for sid in band.sources:
                if sid not in source_ids:
                    add(Finding("sane_range", where, f"sane_range cites {sid!r}, which sources.yaml does not declare"))
        if not metric.formula.strip():
            add(Finding("roles_not_tables", where, "has no formula"))
        required = set(metric.binds.required) | set(metric.binds.optional)
        for finding in expression_findings(metric.formula, pack, f"{where} formula", allowed_roles=required):
            add(finding)
        named = roles_named(metric.formula)
        for role in sorted(named - set(metric.binds.required)):
            add(Finding("roles_not_tables", where, f"formula names role {role!r}; list it in binds.required"))
        roles_by_metric[metric.name] = named
    return roles_by_metric


def _check_aliases(pack: Pack, add) -> None:
    owner: dict[str, str] = {}
    for metric in pack.metrics:
        for label in dict.fromkeys([metric.name, metric.title, *metric.aliases]):
            key = re.sub(r"[^a-z0-9]+", "", (label or "").lower())
            if not key:
                continue
            if key in owner and owner[key] != metric.name:
                add(Finding("alias_collision", f"metric {metric.name}",
                            f"{label!r} is also a name of metric {owner[key]!r}"))
            owner.setdefault(key, metric.name)


def _check_plays(pack: Pack, source_ids: set[str], add) -> None:
    metric_names = {m.name for m in pack.metrics}
    seen: set[str] = set()
    for play in pack.playbooks:
        where = f"play {play.id or play.trigger_condition[:40] or '?'}"
        if not play.id:
            add(Finding("plays_bound", where, "has no id"))
        elif play.id in seen:
            add(Finding("plays_bound", where, "id is declared twice"))
        seen.add(play.id)
        if play.kind not in PLAY_KINDS:
            add(Finding("plays_bound", where, f"kind {play.kind!r} not in {PLAY_KINDS}"))
        if play.trigger_metric not in metric_names:
            add(Finding("plays_bound", where, f"triggers on {play.trigger_metric!r}, which is not a declared metric"))
        for sid in play.sources:
            if sid not in source_ids:
                add(Finding("plays_bound", where, f"cites {sid!r}, which sources.yaml does not declare"))
        if play.detection:
            if play.kind != "data_quality":
                add(Finding("plays_bound", where, "only a data_quality play carries a detection"))
            for finding in expression_findings(play.detection, pack, f"{where} detection"):
                add(finding)


def _check_datasets(pack: Pack, source_ids: set[str], metric_roles: dict[str, set[str]], add) -> set[str]:
    ids: set[str] = set()
    metrics = {m.name: m for m in pack.metrics}
    for dataset in pack.datasets:
        where = f"dataset {dataset.id or '?'}"
        if not dataset.id:
            add(Finding("datasets", where, "has no id"))
            continue
        if dataset.id in ids:
            add(Finding("datasets", where, "id is declared twice"))
        ids.add(dataset.id)
        if dataset.source not in source_ids:
            add(Finding("datasets", where, f"cites {dataset.source!r}, which sources.yaml does not declare"))
        if not re.match(r"^https?://\S+$", dataset.url or ""):
            add(Finding("datasets", where, "has no http(s) url"))
        if dataset.bytes <= 0:
            add(Finding("datasets", where, "states no size in bytes"))
        if not _SHA256.match(dataset.sha256 or ""):
            add(Finding("datasets", where, "states no SHA-256 (64 lowercase hex characters)"))
        if not dataset.load:
            add(Finding("datasets", where, "has no load statements"))
        for role, bound in dataset.binding.items():
            spec = pack.entities.get(role)
            if spec is None:
                add(Finding("datasets", where, f"binds role {role!r}, which entities.yaml does not declare"))
                continue
            if not bound.table:
                add(Finding("datasets", where, f"binds role {role!r} to no table"))
            for attribute in bound.columns:
                if attribute not in spec.attributes:
                    add(Finding("datasets", where, f"binds {role}.{attribute}, which role {role!r} does not declare"))
        for name in dataset.measures:
            metric = metrics.get(name)
            if metric is None:
                add(Finding("datasets", where, f"measures {name!r}, which is not a declared metric"))
                continue
            for match in ROLE_ATTRIBUTE.finditer(metric.formula):
                role, attribute = match.group(1), match.group(2)
                bound = dataset.binding.get(role)
                if bound is None or attribute not in bound.columns:
                    add(Finding("datasets", where, f"measures {name!r} but does not bind {role}.{attribute}"))
            if len(metric_roles.get(name, set())) > 1:
                add(Finding("datasets", where, f"measures {name!r}, whose formula spans several roles — gate 4 "
                                               f"measures one role per metric"))
    return ids


def _check_goldens(pack: Pack, source_ids: set[str], dataset_ids: set[str], add) -> None:
    metric_names = {m.name for m in pack.metrics}
    for number, golden in enumerate(pack.evals, 1):
        expect = golden.expect or {}
        where = f"golden {number} ({golden.question[:50]})"
        named = expect.get("metric") or expect.get("uses_recipe")
        if named and named not in metric_names:
            add(Finding("goldens", where, f"names metric {named!r}, which is not declared"))
        if "dataset" not in expect:
            continue
        if expect["dataset"] not in dataset_ids:
            add(Finding("goldens", where, f"names dataset {expect['dataset']!r}, which is not declared"))
        if not expect.get("metric"):
            add(Finding("goldens", where, "a golden on a dataset names the metric it computes"))
        if not isinstance(expect.get("value"), (int, float)) or isinstance(expect.get("value"), bool):
            add(Finding("goldens", where, "a golden on a dataset states the published value as a number"))
        tolerance = expect.get("tolerance")
        if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) or tolerance < 0:
            add(Finding("goldens", where, "a golden on a dataset states a tolerance of zero or more"))
        if expect.get("source") not in source_ids:
            add(Finding("goldens", where, f"cites {expect.get('source')!r}, which sources.yaml does not declare"))
        if expect.get("where"):
            for finding in expression_findings(str(expect["where"]), pack, f"{where} where"):
                add(finding)


def _check_ontology(pack: Pack, add) -> None:
    ontology = pack.ontology
    if ontology is None:
        return
    objects = {o.name for o in ontology.objects}
    for link in ontology.links:
        for end in (link.from_object, link.to_object):
            if end not in objects:
                add(Finding("ontology", f"link {link.from_object}->{link.to_object}", f"{end!r} is not a declared object"))
    for lifecycle in ontology.lifecycles:
        if lifecycle.object not in objects:
            add(Finding("ontology", f"lifecycle {lifecycle.object}", "names an object the ontology does not declare"))
        stray = set(lifecycle.terminal_states) - set(lifecycle.states)
        if stray:
            add(Finding("ontology", f"lifecycle {lifecycle.object}", f"terminal states {sorted(stray)} are not states"))


def _iso_date(text: str) -> bool:
    try:
        date.fromisoformat(str(text or ""))
        return True
    except ValueError:
        return False
