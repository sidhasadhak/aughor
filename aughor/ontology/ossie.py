"""Arc OC-8 — import an Apache Ossie semantic model as PROPOSALS a person accepts (decision (j): import only).

Ossie (ex-OSI, incubating; this reads draft 0.2.0.dev0 — github.com/apache/ossie, core-spec/spec.md) is the format
semantic models customers already keep are converging on: one model per document, YAML or JSON, with `datasets` (a
physical `source`, a `primary_key`, `fields`), `relationships` (`from` the many side's columns `to` the one side's) and
`metrics` (an aggregate expression per dialect). It has nothing for processes, promises, rules, actions or identity —
those stay declared here. Export stays refused (ROADMAP §4.6).

Nothing is served from an import. `plan` reads a model against the scope's ontology and says what each part would
become — a new entity over a table no entity reads, a description for an entity that has none, a link, a metric — and
what it cannot (a composite key, a dataset whose table this scope does not hold, an expression only in a dialect this
engine does not speak). A person picks; the picked ones are declared through the ordinary doors as that person's
declarations, into the draft release, with `ossie:<model>@<version>` as their provenance. Pure: no warehouse, no I/O.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from aughor.ontology.models import OntologyGraph

#: The draft this reads. A model of another 0.2 draft is read too and says which; another major or minor is refused.
VERSION = "0.2.0.dev0"
#: Which of a metric's dialects this engine speaks, in order — Ossie's own first, then the engine's, then ANSI.
_DIALECTS = {"bigquery": ("OSSIE_SQL_2026", "BIGQUERY", "ANSI_SQL"),
             "duckdb": ("OSSIE_SQL_2026", "ANSI_SQL"),
             "postgres": ("OSSIE_SQL_2026", "ANSI_SQL"),
             "snowflake": ("OSSIE_SQL_2026", "SNOWFLAKE", "ANSI_SQL"),
             "databricks": ("OSSIE_SQL_2026", "DATABRICKS", "ANSI_SQL")}


class OssieRefused(ValueError):
    """The document is not an Ossie model this reads — said in words."""


def parse(text: str) -> dict:
    """An Ossie model from its YAML or JSON text, checked for the fields the spec requires."""
    raw = (text or "").strip()
    if not raw:
        raise OssieRefused("the model is empty")
    try:
        model = json.loads(raw)
    except ValueError:
        import yaml
        try:
            model = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise OssieRefused(f"the model is neither JSON nor YAML: {str(exc)[:200]}") from exc
    if not isinstance(model, dict):
        raise OssieRefused("an Ossie model is one mapping at the document's root")
    version = str(model.get("version") or "")
    if not version.startswith("0.2"):
        raise OssieRefused(f"this reads Ossie {VERSION} (any 0.2 draft); the model says version {version or 'nothing'}")
    if not str(model.get("name") or "").strip():
        raise OssieRefused("an Ossie model has a `name`")
    datasets = model.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise OssieRefused("an Ossie model has at least one dataset")
    for i, d in enumerate(datasets):
        if not isinstance(d, dict) or not d.get("name") or not d.get("source"):
            raise OssieRefused(f"dataset {i + 1} needs a `name` and a `source`")
    return model


def provenance(model: dict) -> str:
    return f"ossie:{model.get('name')}@{model.get('version')}"


def _bare(table: str) -> str:
    return (table or "").replace("`", "").replace('"', "").split(".")[-1].strip().lower()


def _entity_id(name: str) -> str:
    out = "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", name) if part)
    out = out[:-1] if out.endswith("s") and not out.endswith("ss") and len(out) > 3 else out
    return out if out and not out[0].isdigit() else f"T{out}"


def _context_text(ctx: Any) -> str:
    if isinstance(ctx, str):
        return ctx.strip()
    if isinstance(ctx, dict):
        return str(ctx.get("instructions") or "").strip()
    return ""


def _expression(item: dict, dialect: str) -> tuple[str, str]:
    """``(expression, dialect)`` — the one this engine reads, or ``("", "")``."""
    spoken = {str(d.get("dialect") or "").upper(): str(d.get("expression") or "").strip()
              for d in ((item.get("expression") or {}).get("dialects") or []) if isinstance(d, dict)}
    for name in _DIALECTS.get((dialect or "duckdb").lower(), ("OSSIE_SQL_2026", "ANSI_SQL")):
        if spoken.get(name):
            return spoken[name], name
    return "", ""


def plan(model: dict, graph: OntologyGraph, *, dialect: str = "duckdb") -> list[dict]:
    """What each part of ``model`` would become on ``graph``'s scope: one row per proposal with an `id` a person picks
    by, its `kind` (entity · describe · link · metric), what declaring it sends (`spec`), and — when it cannot be
    declared — `refused` with why. Already-held parts say so and are not offered."""
    by_table = {_bare((e.backing.table if e.backing else "") or ""): e for e in graph.entities.values()
                if e.backing is not None and (e.backing.table or "")}
    rows: list[dict] = []
    datasets: dict[str, dict] = {}
    for d in model.get("datasets") or []:
        name = str(d["name"])
        table = _bare(str(d["source"]))
        description = str(d.get("description") or _context_text(d.get("ai_context")) or "").strip()
        held = by_table.get(table)
        keys = [str(k) for k in d.get("primary_key") or []]
        datasets[name] = {"table": table, "entity": held.id if held is not None else _entity_id(name)}
        row = {"id": f"dataset:{name}", "from": name, "table": table}
        if held is not None:
            datasets[name]["entity"] = held.id
            if description and not (held.description or "").strip():
                rows.append({**row, "kind": "describe", "entity": held.id,
                             "says": f"describe {held.id} as the model does: {description[:160]}",
                             "spec": {"description": description}})
            else:
                rows.append({**row, "kind": "held", "entity": held.id,
                             "says": f"{table} is already the entity {held.id}" + ("; it has its own description"
                                                                                 if description else "")})
            continue
        if len(keys) != 1:
            rows.append({**row, "kind": "entity", "entity": _entity_id(name),
                         "refused": ("a composite key cannot be an entity's key here — declare one key column"
                                     if keys else "the dataset names no primary key — an entity needs one")})
            continue
        rows.append({**row, "kind": "entity", "entity": _entity_id(name),
                     "says": f"a new entity {_entity_id(name)} over {table}, keyed by {keys[0]}",
                     "spec": {"id": _entity_id(name), "display_name": name.replace("_", " ").capitalize(),
                              "description": description, "backing": {"kind": "table", "table": table,
                                                                       "primary_key": keys[0]}}})
    held_links = {(r.from_entity, r.to_entity, (r.from_col or "").lower(), (r.to_col or "").lower())
                  for r in graph.relationships.values()}
    for r in model.get("relationships") or []:
        name = str(r.get("name") or "")
        row = {"id": f"relationship:{name}", "kind": "link", "from": name}
        src, dst = datasets.get(str(r.get("from"))), datasets.get(str(r.get("to")))
        fc, tc = [str(c) for c in r.get("from_columns") or []], [str(c) for c in r.get("to_columns") or []]
        if src is None or dst is None:
            rows.append({**row, "refused": f"it joins {r.get('from')} to {r.get('to')}, and the model names no such dataset"})
        elif len(fc) != 1 or len(tc) != 1:
            rows.append({**row, "refused": "a link joins on one column each side here — this one joins on several"})
        elif (src["entity"], dst["entity"], fc[0].lower(), tc[0].lower()) in held_links:
            rows.append({**row, "kind": "held", "says": f"{src['entity']} → {dst['entity']} on {fc[0]} is already a link"})
        else:
            rows.append({**row, "says": f"a link {src['entity']} → {dst['entity']} ({fc[0]} = {tc[0]}), many to one",
                         "spec": {"name": name, "from_entity": src["entity"], "to_entity": dst["entity"],
                                  "from_column": fc[0], "to_column": tc[0], "cardinality": "N:1"}})
    for m in model.get("metrics") or []:
        name = str(m.get("name") or "")
        row = {"id": f"metric:{name}", "kind": "metric", "from": name}
        expression, spoken = _expression(m, dialect)
        if not expression:
            rows.append({**row, "refused": "its expression is only in a dialect this engine does not read"})
            continue
        tables = sorted({d["table"] for n, d in datasets.items() if re.search(rf"\b{re.escape(n)}\.", expression)})
        if len(tables) != 1:
            rows.append({**row, "refused": ("it reads several datasets — a metric here is one statement over one table"
                                            if tables else "its expression names no dataset of the model")})
            continue
        bare = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\.(?=[A-Za-z_])", "", expression)
        rows.append({**row, "says": f"a draft metric {name} = {bare} over {tables[0]} ({spoken}), waiting for approval",
                     "spec": {"name": name, "label": name.replace("_", " ").capitalize(),
                              "sql": f"SELECT {bare} AS {name} FROM {tables[0]}", "tables": [tables[0]],
                              "caveats": str(m.get("description") or "").strip() or None}})
    return rows


def offered(rows: list[dict]) -> list[dict]:
    """The rows a person can accept."""
    return [r for r in rows if r.get("spec") and not r.get("refused") and r.get("kind") != "held"]


def model_from(body: Any) -> dict:
    """A model handed as text or as an already-parsed mapping."""
    if isinstance(body, dict):
        return parse(json.dumps(body))
    return parse(str(body or ""))


def summary(rows: list[dict]) -> dict:
    out: dict[str, int] = {}
    for r in rows:
        key = "refused" if r.get("refused") else ("held" if r.get("kind") == "held" else "offered")
        out[key] = out.get(key, 0) + 1
    return out


def note(model: dict) -> Optional[str]:
    """What the reader should know of the document's version, or None."""
    version = str(model.get("version") or "")
    return None if version == VERSION else f"read as Ossie {VERSION}; the model says {version}"
