"""Built-in capability instances (AL-02) — the real pipelines, each DELEGATING to existing code.

`SqlCapability` is the Data domain expressed as a `CapabilityPipeline`: its four phases call the
functions that already do the work (Trust plane for validate, the connection for execute, the
existing result formatter for interpret), so this is composition, not a rewrite. `generate` uses a
pre-supplied artifact (user SQL / a plan's SQL); wiring the LLM question→SQL step (`nodes._gen_sql`)
and the full narrative synthesis, and migrating the live investigate/explore orchestration onto the
template, are the deferred AL-02 slices.
"""
from __future__ import annotations

from aughor.capability.pipeline import CapabilityRequest, default_validate
from aughor.capability.registry import register_capability
from aughor.trust import Verdict


class SqlCapability:
    """The Data (SQL) domain as a four-phase capability."""
    domain = "data"
    kind = "sql"

    def generate(self, req: CapabilityRequest) -> str:
        # A pre-supplied artifact is used as-is; LLM question→SQL generation is the deferred step.
        return (req.artifact or "").strip()

    def validate(self, artifact: str, req: CapabilityRequest) -> Verdict:
        # The whole point of the plane: validate IS the Trust plane, not a per-path guard subset.
        return default_validate(self.kind, artifact, req)

    def execute(self, artifact: str, req: CapabilityRequest) -> dict:
        conn = req.scope.conn
        if conn is None:
            return {"sql": artifact, "columns": [], "rows": [], "row_count": 0,
                    "error": "no connection in scope"}
        r = conn.execute("capability.data", artifact)
        return {"sql": artifact, "columns": r.columns, "rows": r.rows,
                "row_count": r.row_count, "error": r.error}

    def interpret(self, output: dict, req: CapabilityRequest) -> str:
        # Delegate to the existing deterministic result formatter (the narrative-synthesis LLM
        # pass is a later migration). Reconstruct a QueryResult from the domain-agnostic output.
        from aughor.platform.contracts.execution import QueryResult
        from aughor.tools.executor import format_result_for_llm
        r = QueryResult(hypothesis_id="capability.data", sql=output.get("sql", ""),
                        columns=output.get("columns", []), rows=output.get("rows", []),
                        row_count=output.get("row_count", 0), error=output.get("error"))
        return format_result_for_llm(r)


def register_builtins() -> None:
    """Register the built-in capabilities. Idempotent (register overwrites by domain)."""
    register_capability(SqlCapability())
