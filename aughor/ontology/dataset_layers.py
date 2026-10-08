"""What a dataset is for — its LAYER — proposed from its signs, set by a person (2026-10-08).

The exploration principles (`docs/EXPLORATION_PRINCIPLES_2026-10-07.md` §5, the user's decisions
1 and 2): staging, raw, mapping and uploaded tables were explored like the business layer, and a
raw bronze table yields no finding a person can use. Every schema and every table now has a layer
— one of six — and the layer decides what the platform does with it on its own initiative:

=============  ===================================================================
business       explored fully, then watched over time
integration    structure only — findings come from the business layer, unless there is none
raw            structure and pipeline health only
reference      profiled; used as dimensions by others, never explored alone
uploads        explored only when a person asks
system         never read
=============  ===================================================================

The layer is PROPOSED from evidence — schema and table names read as whole words and as prefixes
(`stage_marketing`, `STAGE_API`, `fct_orders`), column signs (loader columns, all-text columns, a
narrow table of keys and codes), approved metrics — and a PERSON sets it. A name never applies a
layer by itself (decision 2): until a person sets one, a dataset gets structure learning only,
which spends no model call. No model writes a layer, and none proposes one.

Stored beside the people's other declarations about a dataset (the table exclusions of
`ontology/visibility.py`), one file per connection and schema.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import yaml

LAYERS: tuple[str, ...] = ("business", "integration", "raw", "reference", "uploads", "system")

LABEL = {
    "business": "Business",
    "integration": "Integration",
    "raw": "Raw",
    "reference": "Reference",
    "uploads": "Uploads",
    "system": "System",
}

#: The one line a person reads about what the platform does with a dataset of each layer.
POLICY = {
    "business": "explored fully, then watched over time",
    "integration": "structure only — findings come from the business layer",
    "raw": "structure and pipeline health only",
    "reference": "profiled and used as dimensions by others, never explored alone",
    "uploads": "explored only when a person asks",
    "system": "never read",
}

#: The jobs the platform runs ON ITS OWN for a dataset of each layer once a person has set it.
#: A person's Start is not limited by this — it is a person asking.
_AUTO_JOBS = {
    "business": frozenset({"structure", "questions", "time"}),
    "integration": frozenset({"structure"}),
    "raw": frozenset({"structure"}),
    "reference": frozenset({"structure"}),
    "uploads": frozenset({"structure"}),
    "system": frozenset(),
}
#: A dataset nobody has set a layer for yet: its structure is learned, nothing that spends.
UNSET_JOBS = frozenset({"structure"})

LAYERS_FILE = "dataset_layers.yaml"


# ── the signs ────────────────────────────────────────────────────────────────

#: Whole words, read at the SCHEMA level — every one of §5's words.
_SCHEMA_WORDS = {
    "business": {"fact", "facts", "dimension", "dimensions", "dim", "mart", "marts", "gold",
                 "presentation", "reporting", "report", "reports", "analytics", "business",
                 "semantic", "curated"},
    "integration": {"silver", "integration", "intermediate", "cleansed", "clean", "conformed",
                    "core", "vault", "hub", "link", "satellite"},
    "raw": {"raw", "landing", "bronze", "source", "sources", "src", "stage", "staging", "stg",
            "ingest", "ingestion", "import", "load", "extract", "api", "feed", "file", "files",
            "external", "ext"},
    "reference": {"mapping", "mappings", "map", "lookup", "lookups", "lkp", "reference", "ref",
                  "xref", "crosswalk", "master", "calendar", "codes"},
    "uploads": {"upload", "uploads", "sandbox", "scratch", "temp", "tmp", "test", "adhoc",
                "personal", "user"},
    "system": {"audit", "log", "logs", "history", "archive", "backup", "metadata", "system",
               "admin", "etl", "job", "jobs"},
}
#: Whole words, read at the TABLE level — only the words that never name a business thing.
#: `user_sessions`, `order_history`, `api_keys` and `jobs` are business tables in somebody's
#: warehouse, so `user`, `history`, `api` and `job` say nothing about a table on their own.
_TABLE_WORDS = {
    "business": {"fact", "facts", "dim", "mart", "marts", "gold"},
    "integration": {"silver", "intermediate", "cleansed", "conformed", "vault", "satellite"},
    "raw": {"raw", "landing", "bronze", "staging", "stg", "ingest", "ingestion"},
    "reference": {"mapping", "lookup", "lkp", "xref", "crosswalk"},
    "uploads": {"sandbox", "scratch", "tmp", "adhoc", "upload", "uploads"},
    "system": {"audit", "metadata", "etl", "backup"},
}
_PREFIXES = {
    "business": ("fct_", "fact_", "dim_", "mart_", "rpt_", "agg_"),
    "integration": ("int_", "hub_", "lnk_", "sat_", "cln_"),
    "raw": ("raw_", "src_", "stg_", "lnd_", "ext_"),
    "reference": ("map_", "lkp_", "ref_", "xref_"),
    "uploads": ("tmp_", "temp_", "test_"),
    "system": (),
}
_SUFFIXES = {
    "business": ("_fact", "_dim"),
    "integration": (),
    "raw": ("_raw", "_stg"),
    "reference": ("_map", "_lookup"),
    "uploads": ("_tmp", "_bak"),
    "system": ("_log", "_audit", "_hist", "_archive", "_backup"),
}
#: Columns a loader adds: a table that carries them is a copy of somebody's source.
_LOADER_PREFIXES = ("_fivetran_", "_airbyte_", "_sdc_", "_dlt_", "_stitch_", "_hevo_")
_LOADER_COLUMNS = {"_loaded_at", "_ingested_at", "_file_name", "_source_file", "_load_ts",
                   "_load_date", "_inserted_at", "_batch_id", "_etl_loaded_at"}
_KEYISH = re.compile(r"(^id$|_id$|^code$|_code$|_key$|^key$|^name$|_name$|^label$|_label$|"
                     r"^description$|_description$|_desc$|^value$)", re.I)
_TEXT_TYPES = re.compile(r"char|text|string|varchar|utf8", re.I)
#: Column names that hold a number or a date — text there is a value a loader landed untyped. A table of
#: names and codes is all text legitimately; a raw landing table has text where numbers and dates belong.
_TYPED_WORDS = {"date", "at", "on", "time", "timestamp", "ts", "amount", "price", "qty", "quantity", "count",
                "total", "cost", "revenue", "rate", "pct", "percent", "number", "num", "weight", "score",
                "balance", "dt"}

#: Weights: lineage is what the warehouse's own builders declared; a prefix or suffix is a convention
#: somebody chose; a whole word is a hint.
_W_LINEAGE, _W_AFFIX, _W_WORD, _W_COLUMNS = 4, 3, 2, 2


def name_words(name: str) -> list[str]:
    """A name's words: split on `_`, `-`, `.`, spaces and case changes, lower-cased.
    ``stage_marketing`` → stage, marketing · ``STAGE_API`` → stage, api · ``rawSalesforce`` → raw, salesforce."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(name or ""))
    return [w.lower() for w in re.split(r"[_\-.\s]+", s) if w]


@dataclass
class Sign:
    layer: str
    weight: int
    evidence: str


def name_signs(name: str, *, level: str) -> list[Sign]:
    """What a schema's or a table's NAME says, each sign with the sentence a person reads."""
    low = str(name or "").strip().lower()
    if not low:
        return []
    bare = low.split(".")[-1]
    words = name_words(bare)
    vocab = _SCHEMA_WORDS if level == "schema" else _TABLE_WORDS
    out: list[Sign] = []
    for layer in LAYERS:
        hit = next((p for p in _PREFIXES[layer] if bare.startswith(p)), None) \
            or next((s for s in _SUFFIXES[layer] if bare.endswith(s)), None)
        if hit:
            out.append(Sign(layer, _W_AFFIX, f"its name has `{hit.strip('_')}` as a {'prefix' if bare.startswith(hit) else 'suffix'}"))
            continue
        word = next((w for w in words if w in vocab[layer]), None)
        if word:
            out.append(Sign(layer, _W_WORD, f"its name has the word `{word}`"))
    return out


def column_signs(columns: Iterable[tuple[str, str]]) -> list[Sign]:
    """What a table's COLUMNS say: loader columns, or every column text where numbers and dates belong →
    raw; two to four columns, all keys, codes or labels → reference."""
    cols = [(str(n or ""), str(t or "")) for n, t in columns if str(n or "").strip()]
    if not cols:
        return []
    out: list[Sign] = []
    loader = [n for n, _ in cols if n.lower() in _LOADER_COLUMNS or n.lower().startswith(_LOADER_PREFIXES)]
    if loader:
        out.append(Sign("raw", _W_COLUMNS + 1, f"it carries the loader column `{loader[0]}`"))
    elif len(cols) >= 3 and all(t and _TEXT_TYPES.search(t) for _, t in cols):
        typed = [n for n, _ in cols if set(name_words(n)) & _TYPED_WORDS]
        if typed:
            out.append(Sign("raw", _W_COLUMNS, f"all {len(cols)} of its columns are text, "
                                               f"`{'`, `'.join(typed[:2])}` included"))
    if 2 <= len(cols) <= 4 and all(_KEYISH.search(n) for n, _ in cols):
        out.append(Sign("reference", _W_COLUMNS, f"its {len(cols)} columns are all keys, codes or labels"))
    return out


@dataclass
class Proposal:
    """A proposed layer and why. ``layer`` is "" when nothing points anywhere."""
    layer: str = ""
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"layer": self.layer, "label": LABEL.get(self.layer, ""), "evidence": list(self.evidence)}


def _strongest(signs: list[Sign]) -> Optional[Sign]:
    """The sign with the most weight; on a tie, the earliest — a name's own convention first."""
    best: Optional[Sign] = None
    for s in signs:
        if best is None or s.weight > best.weight:
            best = s
    return best


def propose_table(name: str, columns: Iterable[tuple[str, str]] = (), *, lineage: Optional[Sign] = None) -> Proposal:
    """A table's layer by its own signs, or no proposal (it then reads its schema's). ``lineage`` is what
    a dbt manifest says of it (`lineage_signs`), the strongest sign there is."""
    signs = ([lineage] if lineage else []) + name_signs(name, level="table") + column_signs(columns)
    best = _strongest(signs)
    if best is None:
        return Proposal()
    return Proposal(best.layer, [s.evidence for s in signs if s.layer == best.layer])


#: The share of a schema's tables that must point one way for the tables to speak for the schema.
_MAJORITY = 0.6


def propose_schema(name: str, tables: dict[str, Iterable[tuple[str, str]]], *,
                   approved_metrics: int = 0, lineage: Optional[dict[str, Sign]] = None) -> Proposal:
    """A schema's layer: its own name first; else what most of its tables say; else the business
    layer, said as such — a dataset with no sign of anything else reads as business data, and a
    person still sets it."""
    own = _strongest(name_signs(name, level="schema"))
    if own is not None:
        ev = [f"the schema's name has {own.evidence.split('has ', 1)[-1]}"]
        return Proposal(own.layer, ev)
    votes: dict[str, int] = {}
    total = 0
    for t, cols in (tables or {}).items():
        total += 1
        p = propose_table(t, cols, lineage=(lineage or {}).get(str(t).lower()))
        if p.layer:
            votes[p.layer] = votes.get(p.layer, 0) + 1
    if total and votes:
        layer, n = max(votes.items(), key=lambda kv: kv[1])
        if n / total >= _MAJORITY:
            return Proposal(layer, [f"{n} of {total} tables read as {LABEL[layer].lower()}"])
    ev = []
    if approved_metrics:
        ev.append(f"{approved_metrics} approved metric{'s' if approved_metrics != 1 else ''} read it")
    ev.append("no name or column sign of another layer")
    return Proposal("business", ev)


# ── what a person set ────────────────────────────────────────────────────────

def _path(conn: str, schema: str) -> Path:
    from aughor.ontology.recommendations import recommendations_root, safe_name
    return recommendations_root() / safe_name(conn) / safe_name(schema or "default") / LAYERS_FILE


def _bare(table: str) -> str:
    return str(table or "").strip().split(".")[-1].lower()


def load_declared(conn: str, schema: str) -> dict:
    """``{"schema": {layer, set_by, set_at} | None, "tables": {bare: {table, layer, set_by, set_at}}}``."""
    p = _path(conn, schema)
    empty = {"schema": None, "tables": {}}
    if not p.exists():
        return empty
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except Exception as exc:  # noqa: BLE001 — an unreadable file sets nothing, with a trace
        from aughor.kernel.errors import tolerate
        tolerate(exc, "dataset layers could not be read; none applied", counter="dataset_layers.read")
        return empty
    sch = raw.get("schema") if isinstance(raw.get("schema"), dict) else None
    if sch and sch.get("layer") not in LAYERS:
        sch = None
    tables = {}
    for k, v in (raw.get("tables") or {}).items() if isinstance(raw.get("tables"), dict) else []:
        if isinstance(v, dict) and v.get("layer") in LAYERS:
            tables[_bare(k)] = {**v, "table": v.get("table") or k}
    return {"schema": sch, "tables": tables}


def _write(conn: str, schema: str, data: dict) -> None:
    p = _path(conn, schema)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def set_layer(conn: str, schema: str, layer: str, *, table: str = "", set_by: str) -> dict:
    """A person sets a schema's layer, or one table's. Replaces what was set before. Raises
    ``ValueError`` for an unknown layer or a missing person — a layer nobody set is not a layer."""
    if layer not in LAYERS:
        raise ValueError(f"the layer must be one of {', '.join(LAYERS)}")
    if not str(set_by or "").strip():
        raise ValueError("a layer is set by a person")
    data = load_declared(conn, schema)
    rec = {"layer": layer, "set_by": str(set_by), "set_at": datetime.now(timezone.utc).isoformat()}
    if table:
        data["tables"][_bare(table)] = {"table": str(table), **rec}
    else:
        data["schema"] = rec
    _write(conn, schema, data)
    return rec


def clear_layer(conn: str, schema: str, *, table: str = "") -> bool:
    """Withdraw what a person set; the dataset reads its proposal again, unset."""
    data = load_declared(conn, schema)
    if table:
        if data["tables"].pop(_bare(table), None) is None:
            return False
    elif data["schema"] is None:
        return False
    else:
        data["schema"] = None
    _write(conn, schema, data)
    return True


def layer_of(conn: str, schema: str, table: str = "") -> str:
    """The layer a person set for this table (its own, else its schema's), or "" when unset."""
    data = load_declared(conn, schema)
    if table:
        own = data["tables"].get(_bare(table))
        if own:
            return own["layer"]
    return (data["schema"] or {}).get("layer", "")


def auto_jobs(layer: str, *, connection_has_business: bool = True) -> frozenset[str]:
    """The jobs the platform runs on its own for a dataset of this layer ("" = unset)."""
    if not layer:
        return UNSET_JOBS
    if layer == "integration" and not connection_has_business:
        # §5: "no findings unless no gold exists" — with no business layer, integration is the best there is
        return _AUTO_JOBS["business"]
    return _AUTO_JOBS.get(layer, UNSET_JOBS)


# ── one entity, several layers (§5) ──────────────────────────────────────────

_ALL_PREFIXES = tuple(sorted({p for ps in _PREFIXES.values() for p in ps}, key=len, reverse=True))
_ALL_SUFFIXES = tuple(sorted({s for ss in _SUFFIXES.values() for s in ss}, key=len, reverse=True))


def entity_key(name: str) -> str:
    """What a table holds, its layer's affixes taken off: `stg_orders`, `orders_raw`, `fct_orders` and
    `orders` are one entity, `orders`. A trailing plural `s` goes too (`order` and `orders`)."""
    bare = str(name or "").strip().split(".")[-1].lower()
    for p in _ALL_PREFIXES:
        if bare.startswith(p) and len(bare) > len(p):
            bare = bare[len(p):]
            break
    for s in _ALL_SUFFIXES:
        if bare.endswith(s) and len(bare) > len(s):
            bare = bare[: -len(s)]
            break
    return bare[:-1] if len(bare) > 3 and bare.endswith("s") and not bare.endswith("ss") else bare


def copies_of(tables_by_schema: dict[str, list[str]]) -> dict[tuple[str, str], list[str]]:
    """``{(schema, table): ["other_schema.other_table", …]}`` for every table that holds the same entity
    as another table of the connection — the raw, cleansed and business copies of one thing."""
    by_key: dict[str, list[tuple[str, str]]] = {}
    for schema, tables in (tables_by_schema or {}).items():
        for t in tables or []:
            k = entity_key(t)
            if k:
                by_key.setdefault(k, []).append((schema, t))
    out: dict[tuple[str, str], list[str]] = {}
    for members in by_key.values():
        if len(members) < 2:
            continue
        for sch, t in members:
            out[(sch, t)] = [f"{s}.{o}" for s, o in members if (s, o) != (sch, t)]
    return out


# ── lineage: what a dbt manifest says (§5's third witness) ───────────────────

_DBT_FOLDERS = (
    ("business", {"marts", "mart", "reporting", "presentation", "gold", "core_marts"}),
    ("integration", {"intermediate", "int", "integration", "silver"}),
    ("raw", {"staging", "stg", "stage", "base", "bronze", "raw"}),
)


def lineage_signs(manifest: dict) -> dict[tuple[str, str], Sign]:
    """``{(schema, table): Sign}`` from a dbt ``manifest.json``: a source is raw, a seed reference, a
    snapshot integration, and a model takes its folder's layer — `models/staging/…` raw,
    `models/intermediate/…` integration, `models/marts/…` business. Names are lower-cased."""
    out: dict[tuple[str, str], Sign] = {}

    def put(node: dict, layer: str, why: str) -> None:
        schema = str(node.get("schema") or "").lower()
        table = str(node.get("alias") or node.get("identifier") or node.get("name") or "").lower()
        if schema and table:
            out[(schema, table)] = Sign(layer, _W_LINEAGE, why)

    for src in ((manifest or {}).get("sources") or {}).values():
        if isinstance(src, dict):
            put(src, "raw", "dbt declares it a source")
    for node in ((manifest or {}).get("nodes") or {}).values():
        if not isinstance(node, dict):
            continue
        kind = node.get("resource_type")
        if kind == "seed":
            put(node, "reference", "dbt loads it as a seed")
        elif kind == "snapshot":
            put(node, "integration", "dbt snapshots it")
        elif kind == "model":
            folders = [str(f).lower() for f in (node.get("fqn") or [])[1:-1]]
            for layer, words in _DBT_FOLDERS:
                hit = next((f for f in folders if f in words or any(w in words for w in name_words(f))), None)
                if hit:
                    put(node, layer, f"dbt builds it under models/{'/'.join(folders)}")
                    break
    return out


_lineage_cache: dict[str, tuple[float, dict]] = {}


def configured_lineage() -> dict[tuple[str, str], Sign]:
    """The lineage signs of the dbt manifest this install names (``AUGHOR_DBT_MANIFEST``, the same
    file `semantic/dbt.py` reads descriptions from), re-read when the file changes; {} without one."""
    import json
    import os
    path = os.getenv("AUGHOR_DBT_MANIFEST") or ""
    if not path or not Path(path).is_file():
        return {}
    mtime = Path(path).stat().st_mtime
    hit = _lineage_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        signs = lineage_signs(json.loads(Path(path).read_text()))
    except Exception as exc:  # noqa: BLE001 — an unreadable manifest is no witness, with a trace
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the dbt manifest could not be read for lineage signs", counter="dataset_layers.lineage")
        signs = {}
    _lineage_cache[path] = (mtime, signs)
    return signs
