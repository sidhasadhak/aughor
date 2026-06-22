"""Thin async HTTP client over the running Aughor REST API — the substrate the MCP
server's governed tools call.

Keeping the MCP layer a *client* (not an in-process import of the FastAPI app) is a
deliberate choice: every tool then runs the exact governed path the web UI runs —
cost metering, agent governance/budgets, capability gating, and Trust Receipts all
happen in the API process, not a second copy of it. The MCP server stays stateless
and light (httpx only), so it starts fast under a stdio launcher and never spins up a
second JobKernel.

Two of the surfaces are SSE streams (``/chat`` and ``/investigate``); the rest are
plain JSON. ``_stream_sse`` parses Aughor's framing (one ``data: {"type": …}`` line
per event) and the high-level ``ask``/``deep_analysis`` helpers fold the stream into a
single result an MCP tool can return.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
# Sample caps — an MCP result feeds an LLM context, so we never return the full
# (up to 10k-row) result set; we return a sample + the true row_count.
_ROW_SAMPLE = 50
_FINDING_CAP = 25


class AughorError(RuntimeError):
    """An Aughor API call failed (a non-2xx response or a transport error). The
    message is shaped for an LLM client — capability-locked (402) and not-found
    (404) read cleanly rather than as raw stack traces."""


class AughorClient:
    """An async client over the Aughor REST API.

    Config comes from the environment so a stdio launcher (Claude Desktop/Code/Cursor)
    can set it once: ``AUGHOR_API_URL`` (default ``http://127.0.0.1:8000``),
    ``AUGHOR_API_KEY`` (sent as ``X-Api-Key`` when set), ``AUGHOR_MCP_TIMEOUT`` (plain
    calls, default 60s), ``AUGHOR_MCP_DEEP_TIMEOUT`` (the streaming ask/deep tools,
    default 300s). Tests inject ``transport=httpx.ASGITransport(app=…)`` to drive the
    real app in-process.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        *,
        timeout: Optional[float] = None,
        deep_timeout: Optional[float] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("AUGHOR_API_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("AUGHOR_API_KEY", "")
        self.timeout = float(timeout if timeout is not None else os.environ.get("AUGHOR_MCP_TIMEOUT", "60"))
        self.deep_timeout = float(
            deep_timeout if deep_timeout is not None else os.environ.get("AUGHOR_MCP_DEEP_TIMEOUT", "300")
        )
        self._transport = transport

    # ── plumbing ────────────────────────────────────────────────────────────────
    def _headers(self) -> dict[str, str]:
        h = {"accept": "application/json"}
        if self.api_key:
            h["X-Api-Key"] = self.api_key
        return h

    def _mk_client(self, timeout: Optional[float] = None) -> httpx.AsyncClient:
        kw: dict[str, Any] = {
            "base_url": self.base_url,
            "headers": self._headers(),
            "timeout": timeout if timeout is not None else self.timeout,
        }
        if self._transport is not None:
            kw["transport"] = self._transport
        return httpx.AsyncClient(**kw)

    @staticmethod
    def _err_message(status: int, detail: str, path: str) -> str:
        """One LLM-friendly error string for both the JSON and the streaming paths —
        a capability lock (402) and a not-found (404) read cleanly, not as stack traces."""
        if status == 402:
            return f"{path}: capability locked — {detail}"
        if status == 404:
            return f"{path}: not found — {detail}"
        return f"{path}: HTTP {status} — {detail}"

    @classmethod
    def _unwrap(cls, r: httpx.Response, path: str) -> Any:
        if r.status_code >= 400:
            raise AughorError(cls._err_message(r.status_code, _safe_detail(r), path))
        try:
            return r.json()
        except Exception:
            return r.text

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        async with self._mk_client() as c:
            try:
                r = await c.get(path, params=_clean(params))
            except httpx.HTTPError as e:
                raise AughorError(f"GET {path} failed — is the Aughor API running at {self.base_url}? ({e})") from e
        return self._unwrap(r, path)

    async def _post(self, path: str, json_body: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        async with self._mk_client() as c:
            try:
                r = await c.post(path, json=json_body, params=_clean(params))
            except httpx.HTTPError as e:
                raise AughorError(f"POST {path} failed — is the Aughor API running at {self.base_url}? ({e})") from e
        return self._unwrap(r, path)

    async def _stream_sse(
        self, method: str, path: str, json_body: Optional[dict] = None, *, timeout: Optional[float] = None
    ) -> AsyncIterator[dict]:
        """Yield each Aughor SSE event as a dict. Aughor frames every event as a
        single ``data: {"type": …, …}`` line (see investigations._sse)."""
        async with self._mk_client(timeout=timeout if timeout is not None else self.deep_timeout) as c:
            async with c.stream(method, path, json=json_body) as r:
                if r.status_code >= 400:
                    await r.aread()
                    raise AughorError(self._err_message(r.status_code, _safe_detail(r), path))
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if not payload:
                        continue
                    try:
                        yield json.loads(payload)
                    except json.JSONDecodeError:
                        logger.debug("skipping non-JSON SSE data line on %s", path)
                        continue

    # ── governed tools ──────────────────────────────────────────────────────────
    async def list_connections(self) -> list[dict]:
        conns = await self._get("/connections")
        out = []
        for c in conns if isinstance(conns, list) else []:
            out.append({
                "id": c.get("id"),
                "name": c.get("name"),
                "dialect": c.get("dialect") or c.get("conn_type"),
                "schemas": c.get("schemas") or c.get("schema_names"),
            })
        return out

    async def ask(
        self,
        question: str,
        connection: str,
        *,
        canvas: Optional[str] = None,
        history: Optional[list] = None,
        with_receipt: bool = True,
    ) -> dict:
        """Drive ``/chat`` to completion and fold the stream into one governed answer
        + its Trust Receipt."""
        body = {
            "question": question,
            "connection_id": connection,
            "canvas_id": canvas,
            "history": history or [],
            "session_id": "",
        }
        acc: dict[str, Any] = {
            "question": question, "connection": connection, "answer": None, "sql": None,
            "columns": None, "rows": None, "row_count": None, "chart_type": None,
            "analysis": None, "trusted_metrics": None, "tables_used": None,
            "investigation_id": None, "has_receipt": False, "error": None,
        }
        async for ev in self._stream_sse("POST", "/chat", body, timeout=self.deep_timeout):
            t = ev.get("type")
            if t == "sql":
                acc["sql"] = ev.get("sql")
            elif t == "columns":
                acc["columns"] = ev.get("columns")
            elif t == "rows":
                rows = ev.get("rows") or []
                acc["row_count"] = len(rows)
                acc["rows"] = rows[:_ROW_SAMPLE]
            elif t == "headline":
                acc["answer"] = ev.get("headline")
            elif t == "chart_type":
                acc["chart_type"] = ev.get("chart_type")
            elif t == "analysis":
                acc["analysis"] = {"intent": ev.get("intent"), "steps": ev.get("steps")}
            elif t == "trusted":
                acc["trusted_metrics"] = ev.get("items")
            elif t == "tables_used":
                acc["tables_used"] = ev.get("tables")
            elif t == "error":
                acc["error"] = ev.get("message")
            elif t == "done":
                acc["investigation_id"] = ev.get("inv_id")
                acc["has_receipt"] = bool(ev.get("has_receipt"))
        if acc["error"] and acc["answer"] is None:
            raise AughorError(f"ask failed: {acc['error']}")
        if with_receipt and acc["investigation_id"] and acc["has_receipt"]:
            try:
                acc["receipt"] = await self._get(f"/chat/{connection}/{acc['investigation_id']}/receipt")
            except AughorError:
                acc["receipt"] = None
        return acc

    async def deep_analysis(
        self,
        question: str,
        connection: str,
        *,
        schema: Optional[str] = None,
        deep: bool = True,
        skip_cache: bool = False,
        canvas: Optional[str] = None,
    ) -> dict:
        """Drive ``/investigate`` to completion (bounded by ``deep_timeout``) and return
        the final report. On timeout, hands back the investigation_id to poll."""
        body = {
            "question": question, "connection_id": connection, "schema": schema,
            "deep": deep, "skip_cache": skip_cache, "canvas_id": canvas,
        }
        acc: dict[str, Any] = {
            "question": question, "connection": connection, "investigation_id": None,
            "status": "running", "report": None, "report_kind": None, "hypotheses": None,
            "from_cache": False, "error": None,
        }
        try:
            async for ev in self._stream_sse("POST", "/investigate", body, timeout=self.deep_timeout):
                t = ev.get("type")
                if t == "start":
                    acc["investigation_id"] = ev.get("investigation_id") or acc["investigation_id"]
                elif t == "hypotheses":
                    acc["hypotheses"] = ev.get("hypotheses")
                elif t == "ada_report":
                    acc["report"], acc["report_kind"] = ev.get("ada_report"), "ada"
                    acc["from_cache"] = bool(ev.get("from_cache"))
                    acc["investigation_id"] = ev.get("investigation_id") or acc["investigation_id"]
                elif t == "explore_report":
                    acc["report"], acc["report_kind"] = ev.get("explore_report"), "explore"
                    acc["from_cache"] = bool(ev.get("from_cache"))
                    acc["investigation_id"] = ev.get("investigation_id") or acc["investigation_id"]
                elif t == "dossier_report":
                    acc["report"], acc["report_kind"] = ev.get("dossier"), "dossier"
                    acc["investigation_id"] = ev.get("insight_id") or acc["investigation_id"]
                elif t == "report":
                    acc["report"] = ev.get("report")
                    acc["report_kind"] = acc["report_kind"] or "report"
                    acc["investigation_id"] = ev.get("investigation_id") or acc["investigation_id"]
                elif t == "error":
                    acc["error"] = ev.get("message")
                elif t == "done":
                    acc["status"] = "complete"
        except httpx.TimeoutException:
            # A long run exceeded the read timeout. If it has started, hand back the id
            # to poll; otherwise it never got going. (Genuine errors — a 402 lock, a bad
            # request — are raised by _stream_sse and propagate cleanly, uncaught here.)
            if acc["investigation_id"]:
                acc["status"] = "running"
                acc["message"] = (
                    f"Deep analysis is still running after {self.deep_timeout:.0f}s. Poll "
                    f"get_investigation('{acc['investigation_id']}') for the report when it finishes."
                )
                return acc
            raise AughorError(
                f"deep_analysis timed out after {self.deep_timeout:.0f}s before producing a report."
            )
        if acc["report"] is not None:
            acc["status"] = "complete"
        elif acc["error"]:
            raise AughorError(f"deep_analysis failed: {acc['error']}")
        if acc["investigation_id"] and acc["report_kind"] in ("ada", "report"):
            try:
                acc["receipt"] = await self._get(f"/ada/{connection}/{acc['investigation_id']}/receipt")
            except AughorError:
                acc["receipt"] = None
        return acc

    async def get_investigation(self, investigation_id: str) -> dict:
        return await self._get(f"/investigations/{investigation_id}")

    async def get_metric(self, *, connection: Optional[str] = None, name: Optional[str] = None) -> dict:
        if not name:
            return {"metrics": await self._get("/metrics")}
        definition = None
        for m in (await self._get("/metrics")) or []:
            if m.get("name") == name:
                definition = m
                break
        if definition is None:
            raise AughorError(f"get_metric: no governed metric named '{name}'")
        result: dict[str, Any] = {"name": name, "definition": definition}
        if connection:
            try:
                val = await self._get(f"/metrics/{name}/value", params={"conn_id": connection})
                result.update({"value": val.get("value"), "unit": val.get("unit"), "sql": val.get("sql")})
            except AughorError as e:
                result["value_error"] = str(e)
        return result

    async def list_findings(self, connection: str, *, schema: Optional[str] = None, limit: int = _FINDING_CAP) -> dict:
        data = await self._get(f"/exploration/{connection}/findings", params={"schema": schema})
        insights = (data or {}).get("insights") or []
        trimmed = [
            {
                "id": i.get("id"), "finding": i.get("finding"), "confidence": i.get("confidence"),
                "novelty": i.get("novelty"), "domain": i.get("domain"), "sql": i.get("sql"),
            }
            for i in insights[: max(1, int(limit))]
        ]
        return {
            "connection": connection, "schema": schema, "phase": (data or {}).get("phase"),
            "count": len(insights), "findings": trimmed,
        }

    async def get_briefing(self, connection: str, *, schema: Optional[str] = None, refresh: bool = False) -> dict:
        data = await self._post(
            f"/exploration/{connection}/briefing", params={"schema": schema, "refresh": refresh}
        )
        return {
            "connection": connection, "schema": schema,
            "available": bool((data or {}).get("available")),
            "headline_theme": (data or {}).get("headline_theme"),
            "narrative": (data or {}).get("narrative"),
            "citations": (data or {}).get("citations"),
            "generated_at": (data or {}).get("generated_at"),
        }

    async def explore(self, connection: str, *, schema: Optional[str] = None) -> dict:
        started = await self._post(f"/exploration/{connection}/start", params={"schema": schema})
        status = await self._get(f"/exploration/{connection}/status", params={"schema": schema})
        return {
            "connection": connection, "schema": schema,
            "started": bool((started or {}).get("ok")),
            "reason": (started or {}).get("reason"),
            "phase": (status or {}).get("phase"),
            "insights_found": (status or {}).get("insights_found"),
        }

    async def list_jobs(self, *, state: Optional[str] = None, connection: Optional[str] = None, limit: int = 50) -> list:
        return await self._get("/jobs", params={"state": state, "conn_id": connection, "limit": limit})

    async def get_job(self, job_id: str) -> dict:
        return await self._get(f"/jobs/{job_id}")

    async def cancel_job(self, job_id: str) -> dict:
        return await self._post(f"/jobs/{job_id}/cancel")


def _clean(params: Optional[dict]) -> Optional[dict]:
    """Drop None-valued query params so we never send ``?schema=None``."""
    if not params:
        return None
    return {k: v for k, v in params.items() if v is not None}


def _safe_detail(r: httpx.Response) -> str:
    try:
        body = r.json()
        if isinstance(body, dict) and "detail" in body:
            d = body["detail"]
            return d if isinstance(d, str) else json.dumps(d)
        return json.dumps(body)
    except Exception:
        return (r.text or "")[:300]
