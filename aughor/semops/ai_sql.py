"""R8 — AI as a GOVERNED SQL operator: ``prompt()`` over a column.

MotherDuck exposes ``prompt()`` / ``embedding()`` as SQL functions — an LLM applied per row,
right inside a query. Aughor's +1 is **governance**: every AI column carries its model,
template, cost, and a Trust Receipt, so an LLM-derived column is *auditable*, not magic.

The operator is pinned and bounded:
  * **model-pinned + temperature 0** — an AI column must be reproducible run-to-run.
  * **row-capped** — refuses above ``max_rows`` (surfaced, never a silent truncation), so the
    caller pushes a ``WHERE``/``LIMIT`` into SQL first; this is the cost gate.
  * **batched** to bound call count, **fail-open per row** (a failed batch leaves those rows
    empty, never raises into the query path), **cost-metered** by the provider (R1).
  * **provenanced** — returns an :class:`AIColumnReceipt` (model · template · rows · truncated)
    that the Trust Receipt records.

Two surfaces: ``ai_prompt`` (apply to a Python list → AI column + receipt) and
``register_prompt_udf`` (register a governed ``prompt(instruction, text)`` UDF on a DuckDB
connection so the agent can emit an AI column inside generated SQL — capped so a runaway scan
can't make a million LLM calls).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel

from aughor.llm.provider import Role, get_provider

logger = logging.getLogger(__name__)

DEFAULT_ROLE: Role = "fast"
DEFAULT_MAX_ROWS = 200          # refuse above — push a WHERE/LIMIT into SQL first (the cost gate)
DEFAULT_BATCH = 20
_MAX_CELL = 2000
_TEMPERATURE = 0.0              # pinned deterministic — an AI column must be reproducible


@dataclass
class AIColumnReceipt:
    """Provenance for one AI column — what the Trust Receipt records."""
    operator: str               # "prompt"
    template: str
    role: str
    model: str
    n_input: int
    n_applied: int = 0          # rows actually annotated (≤ cap)
    truncated: bool = False      # True when the cap forced a refusal
    json_schema: Optional[dict] = None
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "operator": self.operator, "template": self.template, "role": self.role,
            "model": self.model, "n_input": self.n_input, "n_applied": self.n_applied,
            "truncated": self.truncated, "json_schema": bool(self.json_schema), "notes": self.notes,
        }


class _Annotated(BaseModel):
    index: int
    value: str = ""


class _AnnotateBatch(BaseModel):
    rows: list[_Annotated]


_SYS = (
    "You apply ONE instruction to each text value of a column and return a single short value per "
    "row — a classification, label, sentiment, or extracted answer. Be consistent and literal; if "
    "a row gives no basis for an answer, return an empty string. Return a value for EVERY index."
)


def ai_prompt(
    values: list,
    template: str,
    *,
    role: Role = DEFAULT_ROLE,
    json_schema: Optional[dict] = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    batch: int = DEFAULT_BATCH,
    override_cap: bool = False,
) -> tuple:
    """Apply ``template`` to each value via the pinned LLM → an AI column + a provenance receipt.

    Returns ``(ai_column, AIColumnReceipt)`` where ``ai_column[i]`` aligns to ``values[i]``
    (``None`` where unfilled). Governed: pinned role/model + temperature 0, an explicit row cap
    (refused + surfaced), batched, fail-open per row."""
    provider = get_provider(role)
    model = getattr(provider, "_model", "") or getattr(provider, "model", "") or ""
    n = len(values)
    receipt = AIColumnReceipt(operator="prompt", template=template, role=str(role), model=str(model),
                              n_input=n, json_schema=json_schema)

    if n == 0:
        return [], receipt
    if not override_cap and n > max_rows:
        receipt.truncated = True
        receipt.notes.append(
            f"Refused: {n} values exceed the AI-column cap of {max_rows}. Add a WHERE/LIMIT to "
            f"reduce the set first, or set override_cap to accept the cost.")
        return [None] * n, receipt

    schema_hint = f"\n\nReturn each value as JSON matching this schema: {json_schema}" if json_schema else ""
    out: list = [None] * n
    for start in range(0, n, max(1, batch)):
        chunk = values[start:start + batch]
        listing = "\n".join(f"[{start + i}] {str(chunk[i])[:_MAX_CELL]}" for i in range(len(chunk)))
        try:
            resp = provider.complete(
                system=_SYS,
                user=(f"Instruction: {template}{schema_hint}\n\nRows (index: text):\n{listing}\n\n"
                      f"Return a value for every index above."),
                response_model=_AnnotateBatch,
                temperature=_TEMPERATURE,
            )
            by_idx = {r.index: r.value for r in resp.rows}
            for i in range(len(chunk)):
                out[start + i] = by_idx.get(start + i)
        except Exception as e:  # noqa: BLE001 — an AI column must never raise into the query path
            logger.warning("ai_prompt: batch [%d:%d] failed: %s", start, start + len(chunk), e)
            receipt.notes.append(f"batch [{start}:{start + len(chunk)}] failed ({str(e)[:80]}) — left empty")
    receipt.n_applied = sum(1 for v in out if v not in (None, ""))
    return out, receipt


def register_prompt_udf(
    duck_conn: Any,
    *,
    role: Role = DEFAULT_ROLE,
    max_calls: int = DEFAULT_MAX_ROWS,
    name: str = "prompt",
) -> Any:
    """Register a governed ``prompt(instruction, text)`` scalar UDF on a DuckDB connection so the
    agent can emit an AI column inside generated SQL (MotherDuck parity). Governed by a hard
    per-registration call cap — beyond it the UDF RAISES, so a runaway scan fails loudly instead
    of silently costing a fortune. Each call is pinned + temperature 0. Returns the connection;
    pair with a ``LIMIT`` in the SQL."""
    counter = {"n": 0}

    def _prompt(instruction: str, text: str) -> str:
        counter["n"] += 1
        if counter["n"] > max_calls:
            raise RuntimeError(
                f"prompt() UDF exceeded the {max_calls}-call governance cap — add a LIMIT to the "
                f"query (AI columns are cost-gated).")
        out, _ = ai_prompt([text or ""], str(instruction), role=role, max_rows=max_calls, override_cap=True)
        return (out[0] or "") if out else ""

    try:
        duck_conn.create_function(name, _prompt, ["VARCHAR", "VARCHAR"], "VARCHAR")
    except Exception as e:
        logger.warning("register_prompt_udf: could not register %s(): %s", name, e)
    return duck_conn


def ai_embed(
    values: list,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    batch: int = 64,
    override_cap: bool = False,
) -> tuple:
    """Embed each value via the pinned embedding model → an embedding column + a receipt.

    The ``embedding()`` half of MotherDuck's ``prompt()/embedding()`` pair, under the same
    governance: a pinned model (reproducible), an explicit row cap (refused + surfaced, never a
    silent truncation — the cost gate), batched, fail-open per batch (a failed batch leaves those
    rows ``None``, never raises into the query path). Returns ``(embeddings, AIColumnReceipt)``
    where ``embeddings[i]`` aligns to ``values[i]`` (``None`` where unfilled). Pair the column with
    DuckDB's built-in ``list_cosine_similarity`` to rank by semantic similarity in SQL."""
    from aughor.semantic.embedder import EMBED_MODEL
    n = len(values)
    receipt = AIColumnReceipt(operator="embedding", template="", role="embed",
                              model=str(EMBED_MODEL), n_input=n)
    if n == 0:
        return [], receipt
    if not override_cap and n > max_rows:
        receipt.truncated = True
        receipt.notes.append(
            f"Refused: {n} values exceed the AI-column cap of {max_rows}. Add a WHERE/LIMIT to "
            f"reduce the set first, or set override_cap to accept the cost.")
        return [None] * n, receipt

    out: list = [None] * n
    for start in range(0, n, max(1, batch)):
        chunk = [str(v)[:_MAX_CELL] for v in values[start:start + batch]]
        try:
            from aughor.semantic.embedder import embed
            vecs = embed(chunk)
            for i in range(min(len(vecs), len(chunk))):
                out[start + i] = vecs[i]
        except Exception as e:  # noqa: BLE001 — an AI column must never raise into the query path
            logger.warning("ai_embed: batch [%d:%d] failed: %s", start, start + len(chunk), e)
            receipt.notes.append(f"batch [{start}:{start + len(chunk)}] failed ({str(e)[:80]}) — left empty")
    receipt.n_applied = sum(1 for v in out if v is not None)
    return out, receipt


def register_embedding_udf(
    duck_conn: Any,
    *,
    max_calls: int = DEFAULT_MAX_ROWS,
    name: str = "embedding",
) -> Any:
    """Register a governed ``embedding(text) -> DOUBLE[]`` scalar UDF on a DuckDB connection so the
    agent can compute an embedding column inside generated SQL (MotherDuck parity), then rank with
    the built-in ``list_cosine_similarity(embedding(col), embedding('query'))``. Governed by a hard
    per-registration call cap — beyond it the UDF RAISES, so a runaway scan fails loudly instead of
    silently costing a fortune. Pair with a ``LIMIT``. Returns the connection."""
    counter = {"n": 0}

    def _embed(text: str):
        counter["n"] += 1
        if counter["n"] > max_calls:
            raise RuntimeError(
                f"embedding() UDF exceeded the {max_calls}-call governance cap — add a LIMIT to the "
                f"query (AI columns are cost-gated).")
        out, _ = ai_embed([text or ""], max_rows=max_calls, override_cap=True)
        return out[0] if (out and out[0] is not None) else None

    try:
        duck_conn.create_function(name, _embed, ["VARCHAR"], "DOUBLE[]")
    except Exception as e:
        logger.warning("register_embedding_udf: could not register %s(): %s", name, e)
    return duck_conn


def emit_ai_receipt(receipt: AIColumnReceipt, *, conn_id: Optional[str] = None) -> None:
    """Journal an AI-column's provenance as an ``ai.column`` event so it rides the Trust Receipt.
    Fail-open — never raises into the query path."""
    try:
        from aughor.kernel.ledger import Ledger
        from aughor.kernel.jobs import current_job_id
        Ledger.default().emit("ai.column", receipt.to_dict(), conn_id=conn_id, job_id=current_job_id())
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "ai-column receipt journal", counter="ai_column.receipt")
