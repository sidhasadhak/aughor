"""KI-1's planner and applier — the lane's two verbs, deterministic, no model call.

`plan` diffs a bundle's typed objects against the LIVE stores and hands each a verdict:
``new`` (the store has nothing), ``identical`` (nothing to decide), ``changed`` (the
store holds a different version), ``conflict`` (the store holds an APPROVED different
version — overwriting a human's approved curation is a decision a human makes, which
is `ontology/interchange.py`'s philosophy carried whole; its synonym planner is
consumed here directly rather than re-implemented).

`apply_candidate` fans ONE accepted object out to its existing store, through that
store's own governance: a metric enters the metrics workflow proposed, not approved; a
trusted query goes through KI-0's seed flow (verified, then proposed); a synonym lands
via the vocabulary writer that finally has a consumer. Nothing here approves anything.
"""
from __future__ import annotations

import hashlib
from typing import Any

#: The wire format shares interchange's version discipline: carried in the bundle,
#: refused when newer than this build understands.
from aughor.ontology.interchange import BUNDLE_VERSION

#: The KI sections and the store each maps to. `synonyms` uses interchange's shape
#: verbatim; the rest are this arc's additions to the wire format.
SECTIONS: tuple[str, ...] = ("metrics", "synonyms", "glossary", "rules", "joins",
                             "trusted_queries")

#: Fields a metric candidate may carry (subset of MetricDefinition, governance
#: lifecycle excluded — lifecycle is the workflow's to assign, never the file's).
_METRIC_FIELDS = ("name", "label", "sql", "tables", "dimensions", "filters", "unit",
                  "caveats", "additivity", "owner", "lineage", "wrong_usage_examples")


def refusal(bundle: dict) -> str:
    """A non-empty string refuses the whole bundle (interchange's forward-version law)."""
    version = int(bundle.get("version") or 0)
    if version > BUNDLE_VERSION:
        return (f"bundle version {version} is newer than this build understands "
                f"({BUNDLE_VERSION}) — upgrade before importing")
    sections = bundle.get("sections")
    if not isinstance(sections, dict) or not sections:
        return "bundle carries no sections"
    unknown = sorted(set(sections) - set(SECTIONS))
    if unknown:
        return f"unknown section(s): {', '.join(unknown)} — known: {', '.join(SECTIONS)}"
    return ""


# ── plan ─────────────────────────────────────────────────────────────────────────────


def plan(connection_id: str, bundle: dict) -> tuple[list[dict], list[str]]:
    """Every candidate with its verdict, plus refused (malformed) entries.

    Deterministic; reads the live stores only. Malformed entries are REFUSED at the
    door rather than staged — interchange's shape: a row the applier could never
    take is not a decision, it is a report."""
    sections = bundle.get("sections") or {}
    out: list[dict] = []
    refused: list[str] = []
    out += _plan_metrics(connection_id, sections.get("metrics") or [], refused)
    out += _plan_synonyms(connection_id, sections.get("synonyms") or [], refused)
    out += _plan_glossary(connection_id, sections.get("glossary") or [], refused)
    out += _plan_kb(connection_id, "rule", sections.get("rules") or [], refused)
    out += _plan_kb(connection_id, "join", sections.get("joins") or [], refused)
    out += _plan_trusted(connection_id, sections.get("trusted_queries") or [], refused)
    return out, refused


def _cand(kind: str, verdict: str, payload: dict, detail: str = "") -> dict:
    return {"kind": kind, "verdict": verdict, "payload": payload, "detail": detail}


def _plan_metrics(connection_id: str, rows: list[dict], refused: list[str]) -> list[dict]:
    from aughor.semantic.metrics import get_metric

    out = []
    for raw in rows:
        name = str(raw.get("name") or "").strip()
        if not name or not str(raw.get("sql") or "").strip():
            refused.append(f"metric: name and sql are required: {raw!r}")
            continue
        payload = {k: raw[k] for k in _METRIC_FIELDS if k in raw}
        payload["connection"] = str(raw.get("connection") or connection_id or "*")
        existing = get_metric(name, connection_id=payload["connection"])
        if existing is None:
            out.append(_cand("metric", "new", payload))
            continue
        live = existing.model_dump()
        differs = [k for k in payload
                   if k != "connection" and payload.get(k) != live.get(k)]
        if not differs:
            out.append(_cand("metric", "identical", payload))
        elif live.get("status") == "approved":
            out.append(_cand("metric", "conflict", payload,
                             f"approved v{live.get('version')} differs on: "
                             + ", ".join(differs)))
        else:
            out.append(_cand("metric", "changed", payload,
                             "differs on: " + ", ".join(differs)))
    return out


def _plan_synonyms(connection_id: str, rows: list[dict], refused: list[str]) -> list[dict]:
    """Consumes `interchange.plan_import` — the planner that existed with no caller."""
    from aughor.ontology.interchange import plan_import

    mini = {"version": 1, "sections": {"synonyms": rows}}
    p = plan_import(connection_id, mini)
    refused.extend(p.refused)
    added = {(str(a.get("subject_kind")), str(a.get("subject_id")), str(a.get("synonym")))
             for a in p.additions}
    collided = {(str(c.get("subject")), str(c.get("synonym"))) for c in p.collisions}
    out = []
    for raw in rows:
        key3 = (str(raw.get("subject_kind") or ""), str(raw.get("subject_id") or ""),
                str(raw.get("synonym") or ""))
        if not all(key3):
            continue   # already in p.refused via plan_import
        elif key3 in added:
            out.append(_cand("synonym", "new", raw))
        elif (key3[1], key3[2]) in collided:
            out.append(_cand("synonym", "conflict", raw,
                             "same synonym declared by a different source"))
        else:
            out.append(_cand("synonym", "identical", raw))
    return out


def _plan_glossary(connection_id: str, rows: list[dict], refused: list[str]) -> list[dict]:
    from aughor.semantic.glossary import canonical_key, load_glossary

    live = (load_glossary(connection_id=connection_id) or {}).get("tables") or {}
    out = []
    for raw in rows:
        table = str(raw.get("table") or "").strip()
        if not table:
            refused.append(f"glossary: table is required: {raw!r}")
            continue
        entry = live.get(canonical_key(table)) or live.get(table) or {}
        fields = {k: raw[k] for k in ("description", "grain", "joins") if k in raw}
        cols = raw.get("columns") or {}
        differs: list[str] = [k for k, v in fields.items() if entry.get(k) != v]
        for col, meta in cols.items():
            cur = (entry.get("columns") or {}).get(col) or {}
            differs += [f"{col}.{k}" for k, v in (meta or {}).items() if cur.get(k) != v]
        if not entry:
            out.append(_cand("glossary", "new", raw))
        elif not differs:
            out.append(_cand("glossary", "identical", raw))
        else:
            out.append(_cand("glossary", "changed", raw,
                             "differs on: " + ", ".join(differs)))
    return out


def _kb_id(kind: str, title: str) -> str:
    """Deterministic entry id, so re-accepting the same object upserts one row."""
    return hashlib.sha1(f"{kind}|{title.strip().lower()}".encode()).hexdigest()[:8]


def _plan_kb(connection_id: str, kind: str, rows: list[dict],
             refused: list[str]) -> list[dict]:
    from aughor.semantic.connection_kb import load_entries

    live = {e.title.strip().lower(): e for e in load_entries(connection_id)
            if e.kind == kind}
    out = []
    for raw in rows:
        title = str(raw.get("title") or "").strip()
        body = str(raw.get("body") or "").strip()
        if not title or not body:
            refused.append(f"{kind}: title and body are required: {raw!r}")
            continue
        cur = live.get(title.lower())
        if cur is None:
            out.append(_cand(kind, "new", raw))
        elif cur.body.strip() == body:
            out.append(_cand(kind, "identical", raw))
        else:
            out.append(_cand(kind, "changed", raw, "body differs"))
    return out


def _plan_trusted(connection_id: str, rows: list[dict],
                  refused: list[str]) -> list[dict]:
    from aughor.evals.promote_trusted import trusted_id
    from aughor.semantic.trusted_queries import get_trusted

    out = []
    for raw in rows:
        question = str(raw.get("question") or "").strip()
        sql = str(raw.get("sql") or "").strip()
        if not question or not sql:
            refused.append(f"trusted_query: question and sql are required: {raw!r}")
            continue
        cur = get_trusted(trusted_id(connection_id, question))
        if cur is None:
            out.append(_cand("trusted_query", "new", raw))
        elif cur.sql.strip() == sql:
            out.append(_cand("trusted_query", "identical", raw))
        elif cur.status == "approved":
            out.append(_cand("trusted_query", "conflict", raw,
                             f"an APPROVED answer for this question differs "
                             f"(v{cur.version}, verified by {cur.verified_by or '?'})"))
        else:
            out.append(_cand("trusted_query", "changed", raw, "sql differs"))
    return out


# ── apply ────────────────────────────────────────────────────────────────────────────


def apply_candidate(connection_id: str, kind: str, payload: dict, *,
                    actor: str, source: str) -> dict:
    """Fan one ACCEPTED object out to its store, through that store's governance.

    Returns ``{"target_ref": ..., "landed_as": ..., ...}``. Raises ``KeyError`` when
    the connection does not exist (trusted queries execute) and ``ValueError`` on a
    payload the target store cannot take — the router turns both into HTTP answers,
    and the candidate stays pending so the human can edit rather than lose it.
    """
    if kind == "metric":
        return _apply_metric(connection_id, payload, actor)
    if kind == "synonym":
        return _apply_synonym(connection_id, payload, source)
    if kind == "glossary":
        return _apply_glossary(payload)
    if kind in ("rule", "join"):
        return _apply_kb(connection_id, kind, payload)
    if kind == "trusted_query":
        return _apply_trusted(connection_id, payload, actor, source)
    raise ValueError(f"unknown candidate kind {kind!r}")


def _apply_metric(connection_id: str, payload: dict, actor: str) -> dict:
    from datetime import datetime, timezone

    from aughor.semantic.governance import apply_transition
    from aughor.semantic.metrics import MetricDefinition, get_metric, save_metric

    name = str(payload.get("name") or "").strip()
    conn = str(payload.get("connection") or connection_id or "*")
    if not name or not str(payload.get("sql") or "").strip():
        raise ValueError("a metric candidate needs name and sql")
    existing = get_metric(name, connection_id=conn)
    base = existing.model_dump() if existing else {}
    merged = {**base, **{k: v for k, v in payload.items() if k in _METRIC_FIELDS},
              "name": name, "connection": conn}
    merged.setdefault("label", name.replace("_", " ").title())
    # An import NEVER carries lifecycle: it lands as a fresh draft and is proposed by
    # the accepting human — the metrics workflow's own approve stays the second act.
    merged["status"], merged["version"] = "draft", int(base.get("version") or 0)
    merged.pop("approved_by", None), merged.pop("approved_at", None)
    now = datetime.now(timezone.utc).isoformat()
    proposed, _audit = apply_transition({**merged, "name": name}, "propose", actor, now)
    save_metric(MetricDefinition(**proposed))
    return {"target_ref": f"metric:{conn}:{name}", "landed_as": "proposed"}


def _apply_synonym(connection_id: str, payload: dict, source: str) -> dict:
    from aughor.ontology.vocabulary import add_synonym

    tier = str(payload.get("source") or "human")
    add_synonym(connection_id, str(payload.get("subject_kind")),
                str(payload.get("subject_id")), str(payload.get("synonym")),
                source=tier,
                note=str(payload.get("note") or f"imported from {source}"))
    return {"target_ref": f"synonym:{connection_id}:{payload.get('subject_id')}:"
                          f"{payload.get('synonym')}",
            "landed_as": tier}


def _apply_glossary(payload: dict) -> dict:
    from aughor.semantic.glossary import update_column, update_table

    table = str(payload.get("table") or "").strip()
    if not table:
        raise ValueError("a glossary candidate needs a table")
    update_table(table, description=payload.get("description"),
                 grain=payload.get("grain"), joins=payload.get("joins"))
    for col, meta in (payload.get("columns") or {}).items():
        update_column(table, col, description=(meta or {}).get("description"),
                      values=(meta or {}).get("values"),
                      caveats=(meta or {}).get("caveats"))
    return {"target_ref": f"glossary:{table}", "landed_as": "glossary"}


def _apply_kb(connection_id: str, kind: str, payload: dict) -> dict:
    from aughor.semantic.connection_kb import KnowledgeEntry, upsert_entry

    title = str(payload.get("title") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not title or not body:
        raise ValueError(f"a {kind} candidate needs title and body")
    entry_id = _kb_id(kind, title)
    upsert_entry(connection_id, KnowledgeEntry(
        id=entry_id, title=title, body=body, kind=kind,  # type: ignore[arg-type]
        tags=[str(t) for t in (payload.get("tags") or [])],
        connection_id=connection_id))
    return {"target_ref": f"kb:{connection_id}:{entry_id}", "landed_as": kind}


def _apply_trusted(connection_id: str, payload: dict, actor: str, source: str) -> dict:
    from aughor.semantic.trusted_verify import seed_trusted

    res = seed_trusted(connection_id, str(payload.get("question") or ""),
                       str(payload.get("sql") or ""),
                       tables=[str(t) for t in (payload.get("tables") or [])],
                       note=str(payload.get("note") or ""),
                       tags=[str(t) for t in (payload.get("tags") or [])],
                       actor=actor, source=f"intake:{source}" if source else "intake")
    row = res["trusted_query"]
    return {"target_ref": f"trusted_query:{row['id']}", "landed_as": row["status"],
            "verification_passed": bool((res.get("verification") or {}).get("passed"))}


# ── export (the round-trip half) ─────────────────────────────────────────────────────


def export(connection_id: str) -> dict:
    """The extended bundle, read from the live stores — the other half of the receipt:
    exported from one deployment, planned on another, and an identical re-import plans
    zero changes. Approved trusted queries only: an export is a statement of what this
    deployment TRUSTS, and shipping drafts would launder them."""
    from aughor.ontology.interchange import export_bundle
    from aughor.semantic.connection_kb import load_entries
    from aughor.semantic.glossary import load_glossary
    from aughor.semantic.metrics import list_metrics
    from aughor.semantic.trusted_queries import list_trusted

    inter = export_bundle(connection_id)
    kb = load_entries(connection_id)
    gloss = (load_glossary(connection_id=connection_id) or {}).get("tables") or {}
    sections: dict[str, Any] = {
        "metrics": [{k: v for k, v in m.model_dump().items()
                     if k in _METRIC_FIELDS + ("connection",) and v not in (None, [], "")}
                    for m in list_metrics()
                    if m.connection in ("*", connection_id)],
        "synonyms": inter.sections.get("synonyms") or [],
        "glossary": [{"table": key, **{k: v for k, v in entry.items()
                                       if k in ("description", "grain", "joins", "columns")}}
                     for key, entry in sorted(gloss.items())],
        "rules": [{"title": e.title, "body": e.body, "tags": e.tags}
                  for e in kb if e.kind == "rule"],
        "joins": [{"title": e.title, "body": e.body, "tags": e.tags}
                  for e in kb if e.kind == "join"],
        "trusted_queries": [{"question": t.question, "sql": t.sql, "tables": t.tables,
                             "note": t.note, "tags": t.tags}
                            for t in list_trusted(connection_id)],
    }
    return {"version": BUNDLE_VERSION, "connection_id": connection_id,
            "sections": sections}
