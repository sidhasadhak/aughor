"""KI-2 (§3.10) — deterministic file mappers: a file in, a KI bundle out.

Formats multiply HERE, cheaply: each mapper turns one file shape into the lane's
typed sections and nothing else — no store writes, no model calls, no judgement.
The lane (KI-1) stays the only place a human verdict happens.

Deterministic by construction: the same bytes always produce the same sections,
which is this slice's stated receipt. The LLM prose mapper is a LATER, separately
gated slice — nothing in this module may call a model.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any

#: What a spreadsheet id looks like once extracted from an id or URL.
_SHEET_ID_RE = re.compile(r"[a-zA-Z0-9-_]{10,}")

#: The metric file's columns — the ONE description of the import format: the template a person
#: downloads, the reference the Import tab shows and this mapper all read it. ``(column, required,
#: what it holds, example)``. Asked for 2026-10-07: *"a rich structure in which an organisation can
#: build a CSV file … the formula, the name, the Date grain, the caveats — the most critical fields
#: required for a metric to be defined"*.
METRIC_COLUMNS: tuple[tuple[str, bool, str, str], ...] = (
    ("name", True, "The metric's id: lowercase words joined by underscores. Unique within its dataset.",
     "net_revenue"),
    ("label", False, "How it reads to a person. Defaults to the name.", "Net revenue"),
    ("sql", True, "A whole SELECT returning ONE row with the value — no date filter: the period "
                  "picker sets the dates.",
     "SELECT SUM(amount) AS net_revenue FROM sales.orders WHERE status <> 'cancelled'"),
    ("dataset", False, "The dataset (schema) it belongs to. Empty: the one its SQL reads. "
                       "* : every dataset of the connection.", "sales"),
    ("description", False, "What it means, in a sentence a reader trusts.",
     "Revenue after refunds and cancellations, in USD."),
    ("unit", False, "USD, %, count, days … — how its figure is shown.", "USD"),
    ("date_column", False, "The date that puts a row in a period: table.column. Empty: set by rule "
                           "from the table's main date.", "sales.orders.ordered_at"),
    ("date_kind", False, "flow (adds up over a period), stock (a level at a date) or cohort "
                         "(tied to one date, completed by a later one). Default flow.", "flow"),
    ("date_grain", False, "The period it is reported by: day, week, month, quarter or year.", "month"),
    ("until_column", False, "A stock's end: a row counts until this date.", ""),
    ("outcome_column", False, "A cohort's completing event.", ""),
    ("settles_after_days", False, "A cohort's maturity, in days.", ""),
    ("caveats", False, "Exclusions and known limits.", "Excludes B2B invoices."),
    ("dimensions", False, "Columns it can be sliced by, comma-separated.", "region, channel"),
    ("filters", False, "Conditions always applied, one per line or ; separated.", ""),
    ("tables", False, "Tables it reads, comma-separated (read from the SQL when empty).", ""),
    ("additivity", False, "additive or non_additive — whether period figures may be summed.", "additive"),
    ("owner", False, "The team or person who answers for it.", "Finance"),
    ("target_value", False, "The figure it aims for.", "1200000"),
    ("warning_threshold", False, "Below (or above) this it reads amber.", "1000000"),
    ("critical_threshold", False, "Below (or above) this it reads red.", "800000"),
    ("target_period", False, "The period the target is for: monthly, quarterly, ytd.", "monthly"),
    ("benchmark_source", False, "Where the target comes from.", "FY2026 plan"),
    ("anti_patterns", False, "Ways NOT to compute it, one per line or ; separated — the assistant "
                             "is told never to.", "Never count cancelled orders"),
    ("quality_tests", False, "SQL assertions that must hold, one per line or ; separated.", ""),
    ("freshness_sla", False, "When its data is due, in words.", "daily by 06:00 UTC"),
    ("freshness_check_sql", False, "SQL returning its data's newest timestamp.", ""),
    ("synonyms", False, "Other names people use for it, comma-separated.", "net sales, NR"),
)

#: Header spellings a metric dictionary is seen in the wild with, mapped to the
#: canonical field. Matching is case-insensitive on the stripped header.
HEADER_ALIASES: dict[str, str] = {
    # the metric's identity
    "name": "name", "metric": "name", "metric_name": "name", "kpi": "name", "id": "name",
    # display
    "label": "label", "display_name": "label", "title": "label",
    # the formula — only rows WITH one become governed-metric candidates
    "sql": "sql", "formula": "sql", "expression": "sql", "calculation": "sql", "statement": "sql",
    # the prose definition — the shape most dictionaries actually have
    "definition": "definition", "description": "definition",
    "business_definition": "definition", "meaning": "definition",
    # where it lives
    "dataset": "schema_name", "schema": "schema_name", "schema_name": "schema_name",
    # its dates — how it is measured for a period
    "date_column": "time_column", "time_column": "time_column", "date": "time_column",
    "date_kind": "time_kind", "time_kind": "time_kind", "kind": "time_kind",
    "date_grain": "time_grain", "time_grain": "time_grain", "grain": "time_grain",
    "granularity": "time_grain", "period": "time_grain", "reporting_period": "time_grain",
    "until_column": "until_column", "outcome_column": "outcome_column",
    "settles_after_days": "settles_after_days", "maturity_days": "settles_after_days",
    # the rest of the governed-metric fields
    "unit": "unit", "format": "unit",
    "owner": "owner", "steward": "owner", "team": "owner",
    "caveats": "caveats", "notes": "caveats", "exclusions": "caveats",
    "table": "tables", "tables": "tables", "source_table": "tables",
    "dimensions": "dimensions", "slice_by": "dimensions", "breakdowns": "dimensions",
    "filters": "filters", "always_on_filters": "filters",
    "additivity": "additivity",
    "target_value": "target_value", "target": "target_value",
    "warning_threshold": "warning_threshold", "warning": "warning_threshold",
    "critical_threshold": "critical_threshold", "critical": "critical_threshold",
    "target_period": "target_period", "benchmark_source": "benchmark_source", "benchmark": "benchmark_source",
    "anti_patterns": "wrong_usage_examples", "wrong_usage_examples": "wrong_usage_examples",
    "never": "wrong_usage_examples", "do_not": "wrong_usage_examples",
    "quality_tests": "quality_tests", "tests": "quality_tests",
    "lineage": "lineage", "freshness_sla": "freshness_sla", "freshness_check_sql": "freshness_check_sql",
    # synonyms
    "aliases": "aliases", "synonyms": "aliases", "also_known_as": "aliases",
}

#: Fields read as a list: words split on commas (or ;), prose and SQL on new lines (or ;) — a
#: filter `status IN ('a', 'b')` and an anti-pattern sentence both carry commas.
_WORD_LISTS = ("tables", "dimensions")
_LINE_LISTS = ("filters", "wrong_usage_examples", "quality_tests", "lineage")
_NUMBERS = ("target_value", "warning_threshold", "critical_threshold")
_SCALARS = ("unit", "owner", "caveats", "schema_name", "time_column", "time_kind", "time_grain",
            "until_column", "outcome_column", "additivity", "target_period", "benchmark_source",
            "freshness_sla", "freshness_check_sql")


def metric_template_csv() -> str:
    """The template a person downloads: every column, and one example row a reader can copy."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c for c, *_ in METRIC_COLUMNS])
    w.writerow([ex for *_, ex in METRIC_COLUMNS])
    return buf.getvalue()


def _metric_fields(vals: dict[str, str]) -> tuple[dict[str, Any], str]:
    """A row's governed-metric fields, typed and checked — ``(fields, "")`` or ``({}, why)``."""
    from aughor.semantic.metric_catalogue import normalize_name
    from aughor.semantic.metric_time import GRAINS, KINDS

    name = normalize_name(vals["name"])
    m: dict[str, Any] = {"name": name, "label": vals.get("label") or vals["name"], "sql": vals["sql"]}
    for k in _SCALARS:
        if vals.get(k):
            m[k] = vals[k]
    if not m.get("caveats") and vals.get("definition"):
        m["caveats"] = vals["definition"]
    for k in _WORD_LISTS:
        if vals.get(k):
            m[k] = [t.strip() for t in vals[k].replace(";", ",").split(",") if t.strip()]
    for k in _LINE_LISTS:
        if vals.get(k):
            m[k] = [t.strip() for t in re.split(r"[;\n]", vals[k]) if t.strip()]
    for k in _NUMBERS:
        if vals.get(k):
            try:
                m[k] = float(vals[k].replace(",", "").replace("_", ""))
            except ValueError:
                return {}, f"{k} {vals[k]!r} is not a number"
    if vals.get("settles_after_days"):
        try:
            m["settles_after_days"] = int(float(vals["settles_after_days"]))
        except ValueError:
            return {}, f"settles_after_days {vals['settles_after_days']!r} is not a number of days"
    kind = str(m.get("time_kind") or "").lower()
    if kind:
        if kind not in KINDS:
            return {}, f"date_kind {m['time_kind']!r} is not one of {', '.join(KINDS)}"
        m["time_kind"] = kind
    elif m.get("time_column"):
        m["time_kind"] = "flow"
    grain = str(m.get("time_grain") or "").lower()
    if grain:
        grain = {"daily": "day", "weekly": "week", "monthly": "month", "quarterly": "quarter",
                 "yearly": "year", "annual": "year"}.get(grain, grain)
        if grain not in GRAINS:
            return {}, f"date_grain {m['time_grain']!r} is not one of {', '.join(GRAINS)}"
        m["time_grain"] = grain
    if m.get("additivity") and m["additivity"].lower().replace("-", "_") not in ("additive", "non_additive"):
        return {}, f"additivity {m['additivity']!r} is not additive or non_additive"
    if m.get("time_kind") == "stock" and not m.get("until_column"):
        return {}, "a stock needs an until_column — the date a row stops counting"
    if m.get("time_kind") == "cohort" and not m.get("outcome_column"):
        return {}, "a cohort needs an outcome_column — the event that completes it"
    return m, ""


def read_tabular(filename: str, data: bytes) -> tuple[list[str], list[dict]]:
    """Rows out of a CSV/TSV/XLSX file: ``(headers, rows-as-dicts)``.

    CSV/TSV ride the stdlib with the upload connector's encoding spirit (UTF-8 with
    BOM tolerance, latin-1 as the last resort). XLSX rides DuckDB's `excel`
    extension — the same reader the data-upload path uses — via an in-memory
    connection. Raises ``ValueError`` with a human-readable reason on failure.
    """
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if suffix in (".csv", ".tsv"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        delim = "\t" if suffix == ".tsv" else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        headers = [h or "" for h in (reader.fieldnames or [])]
        if not headers:
            raise ValueError("the file has no header row")
        return headers, [dict(r) for r in reader]
    if suffix in (".xlsx", ".xls"):
        import tempfile

        import duckdb
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as f:
            f.write(data)
            f.flush()
            con = duckdb.connect(":memory:")
            try:
                from aughor.db.duckdb_ext import prepare_extensions
                prepare_extensions(con)
                try:
                    con.execute("INSTALL excel")
                except Exception as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "excel extension install skipped — a cached "
                                  "install still LOADs; a truly offline box errors "
                                  "on the LOAD below with DuckDB's own message",
                             counter="intake.excel_install")
                con.execute("LOAD excel")
                rel = con.execute(
                    f"SELECT * FROM read_xlsx('{f.name}', all_varchar = true)")
                headers = [d[0] for d in rel.description]
                rows = [dict(zip(headers, r)) for r in rel.fetchall()]
            except Exception as exc:
                raise ValueError(f"could not read the spreadsheet: {exc}") from exc
            finally:
                con.close()
        return headers, rows
    raise ValueError(f"unsupported file type {suffix or filename!r} "
                     "(csv, tsv, xlsx, xls, or a dbt manifest .json)")


def map_dictionary_rows(headers: list[str],
                        rows: list[dict]) -> tuple[dict, list[str], list[str]]:
    """A metric dictionary's rows → KI sections.

    Returns ``(sections, ignored_headers, refused)``. A row with a formula becomes a
    governed-metric candidate; its prose definition (and every row WITHOUT a formula)
    becomes a `definitions` candidate — the connection-KB shape that already exists
    for prose metric meaning; an aliases cell fans out into synonym candidates.
    """
    canon: dict[str, str] = {}
    ignored: list[str] = []
    for h in headers:
        key = HEADER_ALIASES.get((h or "").strip().lower().replace(" ", "_"))
        if key:
            canon[h] = key
        elif (h or "").strip():
            ignored.append(h)

    if "name" not in canon.values():
        raise ValueError(
            "no metric-name column found — expected one of: name, metric, "
            "metric_name, kpi (case-insensitive)")

    metrics: list[dict] = []
    definitions: list[dict] = []
    synonyms: list[dict] = []
    refused: list[str] = []
    for i, row in enumerate(rows, start=2):     # 1-based + header line
        vals: dict[str, str] = {}
        for h, key in canon.items():
            v = str(row.get(h) or "").strip()
            if v:
                # first non-empty wins when two headers alias one field
                vals.setdefault(key, v)
        name = vals.get("name", "")
        if not name:
            refused.append(f"row {i}: no metric name")
            continue
        if vals.get("sql"):
            m, why = _metric_fields(vals)
            if why:
                refused.append(f"row {i} ({name}): {why}")
                continue
            metrics.append(m)
        if vals.get("definition"):
            definitions.append({"title": name, "body": vals["definition"],
                                "tags": ["dictionary"]})
        if not vals.get("sql") and not vals.get("definition"):
            refused.append(f"row {i} ({name}): neither a formula nor a definition")
        for alias in [a.strip() for a in
                      (vals.get("aliases") or "").replace(";", ",").split(",")]:
            if alias:
                from aughor.semantic.metric_catalogue import normalize_name
                synonyms.append({"subject_kind": "metric",
                                 "subject_id": normalize_name(name),
                                 "synonym": alias, "source": "human"})

    sections: dict[str, Any] = {}
    if metrics:
        sections["metrics"] = metrics
    if definitions:
        sections["definitions"] = definitions
    if synonyms:
        sections["synonyms"] = synonyms
    return sections, ignored, refused


def fetch_gsheet_csv(spreadsheet: str, sheet: str = "") -> bytes:
    """One worksheet of a link-shared Google Sheet, as CSV bytes — the same public
    gviz export the Sheets DATA connector reads (`connectors/api/gsheets.py`), so
    the definitions mode makes exactly the claims that connector makes: public
    link-sharing only, no OAuth, no credentials.

    The host is fixed (docs.google.com); only the extracted spreadsheet id and the
    sheet name ride the URL. Raises ``ValueError`` with a human-readable reason —
    including the private-sheet case, which Google answers with an HTML login page
    rather than an error code."""
    import urllib.parse
    import urllib.request

    from aughor.connectors.api.gsheets import extract_spreadsheet_id

    sid = extract_spreadsheet_id(spreadsheet)
    if not _SHEET_ID_RE.fullmatch(sid or ""):
        raise ValueError("not a spreadsheet id or /spreadsheets/d/... URL")
    url = (f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv"
           + (f"&sheet={urllib.parse.quote(sheet)}" if sheet else ""))
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read()
    except Exception as exc:
        raise ValueError(f"could not fetch the sheet: {exc}") from exc
    if data.lstrip()[:1] in (b"<",):
        raise ValueError("the sheet is not link-shared — Google answered with a "
                         "login page. Share it as 'Anyone with the link can view'.")
    return data


def looks_like_dbt_manifest(doc: dict) -> bool:
    return isinstance(doc, dict) and ("nodes" in doc or "sources" in doc) \
        and "metadata" in doc


def map_dbt_manifest(manifest: dict) -> dict:
    """A dbt manifest → a `glossary` section, through the SAME parser the
    env-configured dbt layer uses (`semantic/dbt.glossary_from_manifest`) — one
    reading of dbt's shape, not two."""
    from aughor.semantic.dbt import glossary_from_manifest

    tables = (glossary_from_manifest(manifest) or {}).get("tables") or {}
    entries = []
    for key, entry in sorted(tables.items()):
        row: dict[str, Any] = {"table": key}
        if entry.get("description"):
            row["description"] = entry["description"]
        if entry.get("columns"):
            row["columns"] = entry["columns"]
        entries.append(row)
    return {"glossary": entries} if entries else {}
