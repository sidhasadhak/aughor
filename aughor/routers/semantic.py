"""Semantic Layer router — annotations, connection KB, and benchmarks.

Endpoints
─────────
Schema Annotations (per-connection, per-table, per-column descriptions):
  GET    /semantic/{conn_id}/annotations
  GET    /semantic/{conn_id}/annotations/table/{table}
  PUT    /semantic/{conn_id}/annotations/table/{table}
  DELETE /semantic/{conn_id}/annotations/table/{table}
  GET    /semantic/{conn_id}/annotations/column/{table}/{column}
  PUT    /semantic/{conn_id}/annotations/column/{table}/{column}
  DELETE /semantic/{conn_id}/annotations/column/{table}/{column}

Connection Knowledge Store:
  GET    /semantic/{conn_id}/knowledge
  POST   /semantic/{conn_id}/knowledge
  PUT    /semantic/{conn_id}/knowledge/{entry_id}
  DELETE /semantic/{conn_id}/knowledge/{entry_id}
  POST   /semantic/{conn_id}/knowledge/rebuild-index

Benchmark Suite:
  GET    /semantic/{conn_id}/benchmarks
  POST   /semantic/{conn_id}/benchmarks
  PUT    /semantic/{conn_id}/benchmarks/{case_id}
  DELETE /semantic/{conn_id}/benchmarks/{case_id}
  POST   /semantic/{conn_id}/benchmarks/run
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/semantic", tags=["semantic"])


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic schemas
# ═══════════════════════════════════════════════════════════════════════════════

class TableAnnotationIn(BaseModel):
    description: str


class ColumnAnnotationIn(BaseModel):
    description: str


class KnowledgeEntryIn(BaseModel):
    id:    Optional[str] = None
    title: str
    body:  str
    kind:  str = "note"          # metric | synonym | rule | join | note
    tags:  list[str] = []


class BenchmarkCaseIn(BaseModel):
    id:               Optional[str] = None
    question:         str
    expected_cols:    list[str] = []
    must_contain:     list[str] = []
    must_not_contain: list[str] = []
    notes:            str       = ""


# ═══════════════════════════════════════════════════════════════════════════════
# Schema Annotations
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{conn_id}/annotations")
def get_all_annotations(conn_id: str):
    """Return all table and column annotations for a connection."""
    from aughor.db.annotations import load_annotations
    ann = load_annotations(conn_id)
    return ann.all_tables()


@router.get("/{conn_id}/annotations/table/{table}")
def get_table_annotation(conn_id: str, table: str):
    from aughor.db.annotations import load_annotations
    ann  = load_annotations(conn_id)
    desc = ann.table_description(table)
    return {"table": table, "description": desc}


@router.put("/{conn_id}/annotations/table/{table}", status_code=200)
def upsert_table_annotation(conn_id: str, table: str, body: TableAnnotationIn):
    from aughor.db.annotations import load_annotations, save_annotations
    ann = load_annotations(conn_id)
    ann.set_table_description(table, body.description)
    save_annotations(conn_id, ann)
    return {"table": table, "description": body.description}


@router.delete("/{conn_id}/annotations/table/{table}", status_code=200)
def delete_table_annotation(conn_id: str, table: str):
    from aughor.db.annotations import load_annotations, save_annotations
    ann = load_annotations(conn_id)
    ann.delete_table_description(table)
    save_annotations(conn_id, ann)
    return {"ok": True}


@router.get("/{conn_id}/annotations/column/{table}/{column}")
def get_column_annotation(conn_id: str, table: str, column: str):
    from aughor.db.annotations import load_annotations
    ann  = load_annotations(conn_id)
    desc = ann.column_description(table, column)
    return {"table": table, "column": column, "description": desc}


@router.put("/{conn_id}/annotations/column/{table}/{column}", status_code=200)
def upsert_column_annotation(conn_id: str, table: str, column: str, body: ColumnAnnotationIn):
    from aughor.db.annotations import load_annotations, save_annotations
    ann = load_annotations(conn_id)
    ann.set_column_description(table, column, body.description)
    save_annotations(conn_id, ann)
    return {"table": table, "column": column, "description": body.description}


@router.delete("/{conn_id}/annotations/column/{table}/{column}", status_code=200)
def delete_column_annotation(conn_id: str, table: str, column: str):
    from aughor.db.annotations import load_annotations, save_annotations
    ann = load_annotations(conn_id)
    ann.delete_column_description(table, column)
    save_annotations(conn_id, ann)
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# Connection Knowledge Store
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{conn_id}/knowledge")
def list_knowledge(conn_id: str):
    from aughor.semantic.connection_kb import load_entries
    entries = load_entries(conn_id)
    return [e.to_dict() for e in entries]


@router.post("/{conn_id}/knowledge", status_code=201)
def create_knowledge(conn_id: str, body: KnowledgeEntryIn):
    from aughor.semantic.connection_kb import KnowledgeEntry, upsert_entry
    entry = KnowledgeEntry(
        id=body.id or "",
        title=body.title,
        body=body.body,
        kind=body.kind,          # type: ignore[arg-type]
        tags=body.tags,
        connection_id=conn_id,
    )
    saved = upsert_entry(conn_id, entry)
    return saved.to_dict()


@router.put("/{conn_id}/knowledge/{entry_id}", status_code=200)
def update_knowledge(conn_id: str, entry_id: str, body: KnowledgeEntryIn):
    from aughor.semantic.connection_kb import KnowledgeEntry, upsert_entry, load_entries
    existing = {e.id: e for e in load_entries(conn_id)}
    if entry_id not in existing:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    entry = KnowledgeEntry(
        id=entry_id,
        title=body.title,
        body=body.body,
        kind=body.kind,          # type: ignore[arg-type]
        tags=body.tags,
        connection_id=conn_id,
    )
    saved = upsert_entry(conn_id, entry)
    return saved.to_dict()


@router.delete("/{conn_id}/knowledge/{entry_id}", status_code=200)
def delete_knowledge(conn_id: str, entry_id: str):
    from aughor.semantic.connection_kb import delete_entry
    ok = delete_entry(conn_id, entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    return {"ok": True}


@router.post("/{conn_id}/knowledge/rebuild-index", status_code=200)
def rebuild_knowledge_index(conn_id: str):
    from aughor.semantic.connection_kb import rebuild_index
    count = rebuild_index(conn_id)
    return {"ok": True, "indexed": count}


# ═══════════════════════════════════════════════════════════════════════════════
# Benchmark Suite
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{conn_id}/benchmarks")
def list_benchmarks(conn_id: str):
    from aughor.db.benchmarks import load_cases
    return [c.to_dict() for c in load_cases(conn_id)]


@router.post("/{conn_id}/benchmarks", status_code=201)
def create_benchmark(conn_id: str, body: BenchmarkCaseIn):
    from aughor.db.benchmarks import BenchmarkCase, upsert_case
    case = BenchmarkCase(
        id=body.id or "",
        question=body.question,
        expected_cols=body.expected_cols,
        must_contain=body.must_contain,
        must_not_contain=body.must_not_contain,
        notes=body.notes,
    )
    saved = upsert_case(conn_id, case)
    return saved.to_dict()


@router.put("/{conn_id}/benchmarks/{case_id}", status_code=200)
def update_benchmark(conn_id: str, case_id: str, body: BenchmarkCaseIn):
    from aughor.db.benchmarks import BenchmarkCase, upsert_case, load_cases
    existing = {c.id: c for c in load_cases(conn_id)}
    if case_id not in existing:
        raise HTTPException(status_code=404, detail="Benchmark case not found")
    case = BenchmarkCase(
        id=case_id,
        question=body.question,
        expected_cols=body.expected_cols,
        must_contain=body.must_contain,
        must_not_contain=body.must_not_contain,
        notes=body.notes,
    )
    saved = upsert_case(conn_id, case)
    return saved.to_dict()


@router.delete("/{conn_id}/benchmarks/{case_id}", status_code=200)
def delete_benchmark(conn_id: str, case_id: str):
    from aughor.db.benchmarks import delete_case
    ok = delete_case(conn_id, case_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Benchmark case not found")
    return {"ok": True}


@router.post("/{conn_id}/benchmarks/run")
def run_benchmarks_endpoint(conn_id: str):
    """Generate + execute SQL for every benchmark case and score them."""
    from aughor.db.benchmarks import run_benchmarks
    try:
        run = run_benchmarks(conn_id)
        return run.to_dict()
    except Exception as exc:
        logger.exception("Benchmark run failed for %s", conn_id)
        raise HTTPException(status_code=500, detail=str(exc))
