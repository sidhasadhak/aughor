"""KI-1 (§3.10) — the knowledge-intake lane over HTTP.

Upload a bundle → a PLAN (per-object verdict against the live stores) → a human
accepts / edits / dismisses → accepted objects fan out to the existing stores through
each store's own governance. Nothing auto-applies; identical objects need no decision;
an identical re-upload returns the SAME bundle (content-hash dedupe) — idempotence is
what makes this door safe to point a sync at.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from aughor.licensing import Capability, gate
from aughor.org.context import current_org_id

router = APIRouter(tags=["intake"])


def _org() -> str:
    return current_org_id() or "default"


def _check_conn_org(request: Request, conn_id: str) -> None:
    from aughor.security.authz import check_owner, get_principal
    if conn_id:
        check_owner("connection", conn_id, get_principal(request))


def _emit(payload: dict) -> None:
    from aughor.kernel.ledger import Ledger
    Ledger.default().emit("intake.governance", payload)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _summary(cands: list[dict]) -> dict:
    out = {"new": 0, "changed": 0, "identical": 0, "conflict": 0}
    for c in cands:
        out[c["verdict"]] = out.get(c["verdict"], 0) + 1
    return out


class BundleUpload(BaseModel):
    actor: str
    source: str = ""                       # a label for where this file came from
    connection_id: str = ""                # falls back to the bundle's own
    bundle: Optional[dict] = None          # the bundle as JSON …
    yaml_text: str = ""                    # … or as YAML text (exactly one of the two)


@router.post("/intake/bundles", status_code=201,
             dependencies=[gate(Capability.SEMANTIC_EDIT)])
def upload_bundle(body: BundleUpload, request: Request):
    """Stage one bundle: parse, refuse what cannot be taken (forward versions,
    unknown sections, malformed rows), diff the rest against the live stores, and
    persist the plan as candidates awaiting a human. Re-uploading identical content
    returns the existing bundle and stages nothing new."""
    from aughor.ontology.interchange import bundle_from_yaml

    if not (body.actor or "").strip():
        raise HTTPException(status_code=400, detail="actor is required")
    if (body.bundle is None) == (not body.yaml_text):
        raise HTTPException(status_code=400,
                            detail="exactly one of bundle or yaml_text is required")
    bundle = body.bundle if body.bundle is not None else bundle_from_yaml(body.yaml_text)
    if bundle is None:
        raise HTTPException(status_code=400, detail="not a parseable bundle "
                            "(YAML with a top-level `sections` mapping)")

    conn_id = (body.connection_id or str(bundle.get("connection_id") or "")).strip()
    if not conn_id:
        raise HTTPException(status_code=400, detail="connection_id is required "
                            "(on the request or inside the bundle)")
    _check_conn_org(request, conn_id)
    return _stage(bundle, conn_id, source=body.source, actor=body.actor)


def _stage(bundle: dict, conn_id: str, *, source: str, actor: str,
           mapper_refused: list[str] | None = None) -> dict:
    """Refuse-or-stage one bundle — shared by the bundle door and the file door
    (KI-2's mappers feed the SAME lane; a mapped file is just a bundle)."""
    from aughor.intake import engine, store

    refusal = engine.refusal(bundle)
    if refusal:
        raise HTTPException(status_code=400, detail=refusal)

    org = _org()
    rec, created = store.save_bundle(bundle, source=source, actor=actor, org_id=org)
    if not created:
        cands = store.list_candidates(rec["id"], org_id=org)
        return {"bundle": rec, "duplicate": True,
                "refused": list(mapper_refused or []),
                "summary": _summary(cands), "candidates": cands}

    cands, refused = engine.plan(conn_id, bundle)
    refused = list(mapper_refused or []) + refused
    staged = store.add_candidates(rec["id"], cands, org_id=org)
    _emit({"action": "upload", "bundle": rec["id"], "content_hash": rec["content_hash"],
           "connection_id": conn_id, "actor": actor, "source": source,
           "staged": len(staged), "refused": len(refused), "at": _now(),
           **_summary(cands)})
    return {"bundle": rec, "duplicate": False, "refused": refused,
            "summary": _summary(cands),
            "candidates": store.list_candidates(rec["id"], org_id=org)}


@router.post("/intake/files", status_code=201,
             dependencies=[gate(Capability.SEMANTIC_EDIT)])
async def upload_file(request: Request,
                      file: UploadFile = File(...),
                      connection_id: str = Form(...),
                      actor: str = Form(...),
                      source: str = Form("")):
    """KI-2 — the file door: a metric dictionary (CSV / TSV / XLSX with name,
    definition, formula, unit, owner, aliases columns) or a dbt `manifest.json`
    becomes a bundle through a DETERMINISTIC mapper and enters the SAME lane.
    The mapper judges nothing: every object still waits for a human verdict."""
    from aughor.intake import mappers

    if not (actor or "").strip():
        raise HTTPException(status_code=400, detail="actor is required")
    if not (connection_id or "").strip():
        raise HTTPException(status_code=400, detail="connection_id is required")
    _check_conn_org(request, connection_id)

    name = file.filename or "upload"
    data = await file.read()
    src = (source or "").strip() or name
    ignored: list[str] = []
    mapper_refused: list[str] = []
    if name.lower().endswith(".json"):
        import json as _json
        try:
            doc = _json.loads(data.decode("utf-8-sig"))
        except Exception:
            raise HTTPException(status_code=422, detail="not parseable JSON")
        if not mappers.looks_like_dbt_manifest(doc):
            raise HTTPException(status_code=422, detail="the JSON is not a dbt "
                                "manifest (no nodes/sources + metadata)")
        sections = mappers.map_dbt_manifest(doc)
        if not sections:
            raise HTTPException(status_code=422, detail="the manifest carries no "
                                "described models or sources")
    else:
        try:
            headers, rows = mappers.read_tabular(name, data)
            sections, ignored, mapper_refused = mappers.map_dictionary_rows(
                headers, rows)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        if not sections:
            raise HTTPException(status_code=422, detail="no usable rows — "
                                + "; ".join(mapper_refused[:5]))

    bundle = {"version": 1, "connection_id": connection_id,
              "source_file": name, "sections": sections}
    out = _stage(bundle, connection_id, source=src, actor=actor,
                 mapper_refused=mapper_refused)
    out["mapped"] = {"file": name, "ignored_headers": ignored}
    return out


class SheetIn(BaseModel):
    spreadsheet: str          # a spreadsheet id, or the full /spreadsheets/d/... URL
    sheet: str = ""           # worksheet name; empty = the first tab
    connection_id: str
    actor: str
    source: str = ""


@router.post("/intake/sheets", status_code=201,
             dependencies=[gate(Capability.SEMANTIC_EDIT)])
def upload_sheet(body: SheetIn, request: Request):
    """KI-3 — the Sheets definitions mode: a link-shared Google Sheet holding a
    metric dictionary is fetched through the SAME public gviz export the Sheets
    data connector reads, mapped by the SAME deterministic dictionary mapper, and
    staged in the SAME lane. Public link-sharing only — no OAuth, no credentials,
    exactly the claims the data connector makes."""
    from aughor.intake import mappers

    if not (body.actor or "").strip():
        raise HTTPException(status_code=400, detail="actor is required")
    _check_conn_org(request, body.connection_id)
    try:
        data = mappers.fetch_gsheet_csv(body.spreadsheet, body.sheet)
        headers, rows = mappers.read_tabular("sheet.csv", data)
        sections, ignored, mapper_refused = mappers.map_dictionary_rows(headers, rows)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not sections:
        raise HTTPException(status_code=422, detail="no usable rows — "
                            + "; ".join(mapper_refused[:5]))
    src = (body.source or "").strip() or f"gsheet:{body.spreadsheet.strip()[:60]}"
    bundle = {"version": 1, "connection_id": body.connection_id,
              "source_sheet": {"spreadsheet": body.spreadsheet, "sheet": body.sheet},
              "sections": sections}
    out = _stage(bundle, body.connection_id, source=src, actor=body.actor,
                 mapper_refused=mapper_refused)
    out["mapped"] = {"sheet": body.sheet or "(first tab)",
                     "ignored_headers": ignored}
    return out


class MineIn(BaseModel):
    knowledge_connection_id: str   # the Confluence/Notion connection to walk
    connection_id: str             # the DATA connection the definitions belong to
    actor: str
    source: str = ""               # optional label; defaults to each page's URL


@router.post("/intake/mine", dependencies=[gate(Capability.SEMANTIC_EDIT)])
def mine_knowledge(body: MineIn, request: Request):
    """KI-3 — mine a Confluence or Notion connection's pages for definition tables,
    through the SAME dictionary mapper and into the SAME lane, one bundle per page
    with the page URL as provenance. Deterministic: tables only; a page with no
    dictionary-shaped table stages nothing, and a re-mine of an unchanged page
    proposes nothing (content-hash dedupe). The target DATA connection is named
    explicitly — mined definitions attached to the wiki connection itself would be
    invisible to every prompt, which is the built-and-inert trap by construction."""
    from aughor.db.registry import get_dsn, get_meta
    from aughor.intake import mining

    if not (body.actor or "").strip():
        raise HTTPException(status_code=400, detail="actor is required")
    _check_conn_org(request, body.connection_id)
    _check_conn_org(request, body.knowledge_connection_id)
    try:
        conn_type, _ = get_dsn(body.knowledge_connection_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Knowledge connection not found")
    meta = get_meta(body.knowledge_connection_id)
    try:
        if conn_type == "confluence":
            from aughor.connectors.knowledge.confluence import ConfluenceSync
            pages = mining.mine_confluence(
                ConfluenceSync(body.knowledge_connection_id, meta))
        elif conn_type == "notion":
            from aughor.connectors.knowledge.notion import NotionSync
            pages = mining.mine_notion(
                NotionSync(body.knowledge_connection_id, meta))
        else:
            raise HTTPException(status_code=400, detail=f"{conn_type!r} is not a "
                                "knowledge connector (confluence or notion)")
    except ValueError as e:      # a mis-configured connector names its gap plainly
        raise HTTPException(status_code=400, detail=str(e))

    results: list[dict] = []
    staged = duplicates = skipped = 0
    error = ""
    try:
        for page in pages:
            if not page.sections:
                skipped += 1
                results.append({"url": page.url, "title": page.title,
                                "outcome": "no_dictionary",
                                "tables_seen": page.tables_seen})
                continue
            bundle = {"version": 1, "connection_id": body.connection_id,
                      "source_page": {"url": page.url, "title": page.title},
                      "sections": page.sections}
            out = _stage(bundle, body.connection_id,
                         source=(body.source or "").strip() or page.url,
                         actor=body.actor, mapper_refused=page.refused)
            if out["duplicate"]:
                duplicates += 1
            else:
                staged += 1
            results.append({"url": page.url, "title": page.title,
                            "outcome": "duplicate" if out["duplicate"] else "staged",
                            "bundle_id": out["bundle"]["id"],
                            "summary": out["summary"], "refused": out["refused"],
                            "tables_seen": page.tables_seen,
                            "tables_mapped": page.tables_mapped})
    except Exception as exc:     # a wiki that dies mid-walk keeps what it yielded
        error = str(exc)
    return {"knowledge_connection_id": body.knowledge_connection_id,
            "connection_id": body.connection_id,
            "staged": staged, "duplicates": duplicates, "skipped": skipped,
            "pages": results, **({"error": error} if error else {})}


@router.get("/intake/bundles")
def bundles(connection_id: str = ""):
    from aughor.intake import store
    return {"bundles": store.list_bundles(org_id=_org(), connection_id=connection_id)}


@router.get("/intake/bundles/{bundle_id}")
def bundle_plan(bundle_id: str):
    from aughor.intake import store
    rec = store.get_bundle(bundle_id, org_id=_org())
    if rec is None:
        raise HTTPException(status_code=404, detail="No such bundle")
    cands = store.list_candidates(bundle_id, org_id=_org())
    return {"bundle": rec, "summary": _summary(cands), "candidates": cands}


class ResolveIn(BaseModel):
    actor: str
    accept: list[str] = Field(default_factory=list)     # candidate ids to apply
    dismiss: list[str] = Field(default_factory=list)    # candidate ids to drop
    edits: dict[str, dict] = Field(default_factory=dict)  # id → edited payload


@router.post("/intake/bundles/{bundle_id}/resolve",
             dependencies=[gate(Capability.SEMANTIC_EDIT)])
def resolve_bundle(bundle_id: str, body: ResolveIn, request: Request):
    """The human verdicts. Accepted candidates apply IMMEDIATELY, each through its
    target store's own governance (a metric lands proposed in the metrics workflow, a
    trusted query goes through KI-0's verified seed — approval stays that store's
    second act). A candidate whose apply fails STAYS PENDING with the error attached,
    so the human can edit rather than lose it. Dismissed candidates write nothing."""
    from aughor.intake import engine, store

    if not (body.actor or "").strip():
        raise HTTPException(status_code=400, detail="actor is required")
    rec = store.get_bundle(bundle_id, org_id=_org())
    if rec is None:
        raise HTTPException(status_code=404, detail="No such bundle")
    conn_id = rec["connection_id"]
    _check_conn_org(request, conn_id)

    org = _org()
    by_id = {c["id"]: c for c in store.list_candidates(bundle_id, org_id=org)}
    results: list[dict] = []
    applied = dismissed = failed = 0
    for cid in body.accept:
        cand = by_id.get(cid)
        if cand is None or cand["status"] not in ("pending",):
            results.append({"id": cid, "outcome": "skipped",
                            "reason": "unknown id or not pending"})
            continue
        payload = body.edits.get(cid) or cand["payload"]
        try:
            res = engine.apply_candidate(conn_id, cand["kind"], payload,
                                         actor=body.actor, source=rec["source"])
        except KeyError:
            raise HTTPException(status_code=404, detail="Connection not found")
        except ValueError as e:
            failed += 1
            results.append({"id": cid, "outcome": "error", "reason": str(e)})
            continue
        store.resolve_candidate(cid, status="accepted", actor=body.actor,
                                edited_payload=body.edits.get(cid),
                                target_ref=res.get("target_ref", ""),
                                apply_result=res, org_id=org)
        applied += 1
        results.append({"id": cid, "outcome": "accepted", **res})
    for cid in body.dismiss:
        cand = by_id.get(cid)
        if cand is None or cand["status"] not in ("pending",):
            results.append({"id": cid, "outcome": "skipped",
                            "reason": "unknown id or not pending"})
            continue
        store.resolve_candidate(cid, status="dismissed", actor=body.actor, org_id=org)
        dismissed += 1
        results.append({"id": cid, "outcome": "dismissed"})

    _emit({"action": "resolve", "bundle": bundle_id, "connection_id": conn_id,
           "actor": body.actor, "accepted": applied, "dismissed": dismissed,
           "errors": failed, "at": _now()})
    return {"bundle": bundle_id, "accepted": applied, "dismissed": dismissed,
            "errors": failed, "results": results}


@router.get("/intake/export/{connection_id}")
def export_bundle(connection_id: str, request: Request):
    """The round-trip's other half: this deployment's declared knowledge as a bundle
    — importable elsewhere, and an identical re-import there plans zero changes.
    Trusted queries export APPROVED entries only; drafts are nobody's statement."""
    import yaml as _yaml

    from aughor.intake import engine

    _check_conn_org(request, connection_id)
    bundle = engine.export(connection_id)
    return {"bundle": bundle,
            "yaml_text": _yaml.safe_dump(bundle, sort_keys=True, allow_unicode=True)}


@router.get("/intake/provenance")
def intake_provenance(ref: str):
    """Walk an accepted object back to its import: candidate → bundle hash → source
    → who uploaded and who accepted. `ref` is a target_ref, e.g.
    `trusted_query:tq_ab12…` or `metric:*:revenue`."""
    from aughor.intake import store
    rows = store.provenance(ref, org_id=_org())
    return {"ref": ref, "found": bool(rows), "trail": rows}
