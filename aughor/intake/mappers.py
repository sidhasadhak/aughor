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
from typing import Any

#: Header spellings a metric dictionary is seen in the wild with, mapped to the
#: canonical field. Matching is case-insensitive on the stripped header.
HEADER_ALIASES: dict[str, str] = {
    # the metric's identity
    "name": "name", "metric": "name", "metric_name": "name", "kpi": "name",
    # display
    "label": "label", "display_name": "label", "title": "label",
    # the formula — only rows WITH one become governed-metric candidates
    "sql": "sql", "formula": "sql", "expression": "sql", "calculation": "sql",
    # the prose definition — the shape most dictionaries actually have
    "definition": "definition", "description": "definition",
    "business_definition": "definition", "meaning": "definition",
    # the rest of the governed-metric fields
    "unit": "unit", "format": "unit",
    "owner": "owner", "steward": "owner", "team": "owner",
    "caveats": "caveats", "notes": "caveats", "exclusions": "caveats",
    "table": "tables", "tables": "tables", "source_table": "tables",
    # synonyms
    "aliases": "aliases", "synonyms": "aliases", "also_known_as": "aliases",
}


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
                try:
                    con.execute("INSTALL excel")
                except Exception:
                    pass  # cached installs still LOAD; a truly offline box errors below
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
            m: dict[str, Any] = {"name": name.lower().replace(" ", "_"),
                                 "label": vals.get("label") or name,
                                 "sql": vals["sql"]}
            for k in ("unit", "owner", "caveats"):
                if vals.get(k):
                    m[k] = vals[k]
            if vals.get("tables"):
                m["tables"] = [t.strip() for t in
                               vals["tables"].replace(";", ",").split(",") if t.strip()]
            metrics.append(m)
        if vals.get("definition"):
            definitions.append({"title": name, "body": vals["definition"],
                                "tags": ["dictionary"]})
        if not vals.get("sql") and not vals.get("definition"):
            refused.append(f"row {i} ({name}): neither a formula nor a definition")
        for alias in [a.strip() for a in
                      (vals.get("aliases") or "").replace(";", ",").split(",")]:
            if alias:
                synonyms.append({"subject_kind": "metric",
                                 "subject_id": name.lower().replace(" ", "_"),
                                 "synonym": alias, "source": "human"})

    sections: dict[str, Any] = {}
    if metrics:
        sections["metrics"] = metrics
    if definitions:
        sections["definitions"] = definitions
    if synonyms:
        sections["synonyms"] = synonyms
    return sections, ignored, refused


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
