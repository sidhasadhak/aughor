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
from contextvars import ContextVar
from typing import Any, AsyncIterator, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
# Sample caps — an MCP result feeds an LLM context, so we never return the full
# (up to 10k-row) result set; we return a sample + the true row_count.
_ROW_SAMPLE = 50
_FINDING_CAP = 25

# DE-2a (ROADMAP §3.51) — the principal this client acts as. The API's identity mode
# (`AUGHOR_REQUIRE_IDENTITY=1`) resolves a caller from an OIDC bearer, or — while no issuer
# is configured — from the `X-Aughor-Org` / `X-Aughor-User` seam (`security/authz`). This
# client sent neither, so every MCP call was refused with a 401 the moment identity was
# required (the dbx study's finding 3). The header names are spelled here rather than
# imported: this module stays httpx-only by design, and a test holds the two spellings equal.
IDENTITY_ORG_HEADER = "X-Aughor-Org"
IDENTITY_USER_HEADER = "X-Aughor-User"
#: DE-2b — the mark that makes a request an agent's own, and the tool it serves. Spelled here
#: so this module stays httpx-only; `aughor.mcp.policy` imports them from here.
AGENT_HEADER = "X-Aughor-Agent"
TOOL_HEADER = "X-Aughor-Tool"
AGENT_MARK = "mcp"
#: The MCP tool a request serves, set by the server around each call (`PolicedFastMCP`).
CURRENT_TOOL: ContextVar[str] = ContextVar("aughor_mcp_current_tool", default="")


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

    The principal (DE-2a), when the API requires identity: ``AUGHOR_MCP_BEARER`` is sent as
    ``Authorization: Bearer …`` (an OIDC token, for an API with an issuer configured);
    ``AUGHOR_MCP_ORG`` and ``AUGHOR_MCP_USER`` (default ``mcp``) are sent as the
    ``X-Aughor-Org`` / ``X-Aughor-User`` seam a self-hosted API resolves while no issuer is
    configured. Unset, nothing is sent and identity-off installs are byte-identical.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        *,
        timeout: Optional[float] = None,
        deep_timeout: Optional[float] = None,
        transport: Optional[httpx.BaseTransport] = None,
        org: Optional[str] = None,
        user: Optional[str] = None,
        bearer: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("AUGHOR_API_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("AUGHOR_API_KEY", "")
        self.timeout = float(timeout if timeout is not None else os.environ.get("AUGHOR_MCP_TIMEOUT", "60"))
        self.deep_timeout = float(
            deep_timeout if deep_timeout is not None else os.environ.get("AUGHOR_MCP_DEEP_TIMEOUT", "300")
        )
        self._transport = transport
        self.org = (org if org is not None else os.environ.get("AUGHOR_MCP_ORG", "")).strip()
        self.user = (user if user is not None else os.environ.get("AUGHOR_MCP_USER", "")).strip()
        self.bearer = (bearer if bearer is not None else os.environ.get("AUGHOR_MCP_BEARER", "")).strip()

    # ── plumbing ────────────────────────────────────────────────────────────────
    def _headers(self) -> dict[str, str]:
        h = {"accept": "application/json"}
        if self.api_key:
            h["X-Api-Key"] = self.api_key
        # DE-2a — the principal this client acts as, so an API that requires identity can
        # resolve one: a verified bearer where an issuer is configured, the header seam where
        # not. The user defaults to `mcp` once an org is named, so the audit row says who.
        if self.bearer:
            h["Authorization"] = f"Bearer {self.bearer}"
        if self.org:
            h[IDENTITY_ORG_HEADER] = self.org
            h[IDENTITY_USER_HEADER] = self.user or "mcp"
        # DE-2b — every call this client makes is an agent's own, and says which tool it serves,
        # so the API applies the organisation's agent policy to it and audits it with its principal.
        h[AGENT_HEADER] = AGENT_MARK
        tool = CURRENT_TOOL.get()
        if tool:
            h[TOOL_HEADER] = tool
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

    # ── DS-14: chains as tools ──────────────────────────────────────────────────
    async def list_automation_tools(self) -> list[dict]:
        """The automations this deployment offers as MCP tools.

        Read at server start, so what an external agent can invoke is whatever the
        deployment has OPTED IN — never every automation it happens to hold.
        """
        payload = await self._get("/automations/tools")
        tools = payload.get("tools") if isinstance(payload, dict) else payload
        return list(tools or [])

    # ── SP-5: the Spotlight roster, one declaration for every transport ─────────
    async def list_spotlight_tools(self) -> list[dict]:
        """The declared Spotlight roster (name/description/parameters), read at
        server start — the MCP transport registers FROM the declaration, never a
        hand-kept copy, which is what keeps the parity diff empty."""
        payload = await self._get("/spotlight/tools")
        tools = payload.get("tools") if isinstance(payload, dict) else payload
        return list(tools or [])

    async def call_spotlight_tool(self, name: str, *, connection: str = "",
                                  args: Optional[dict] = None) -> Any:
        """One Spotlight call through the API — the stores stay behind their one
        writer; this process never opens them."""
        return await self._post(f"/spotlight/tools/{name}",
                                json_body={"connection_id": connection,
                                           "args": dict(args or {})})

    async def run_automation(self, automation_id: str) -> dict:
        """Fire one automation through the SAME route the web app's "Run now" uses.

        Not a private path for external callers: it lands in the one engine, records a run
        row, and stops for the approval gate exactly as a scheduled tick would. That is the
        whole claim of exposing a chain as a tool — the caller changes, the governance does
        not.
        """
        return await self._post(f"/automations/{automation_id}/run")

    # ── AO-5a: custom agents as tools ───────────────────────────────────────────
    async def list_user_agents(self) -> list[dict]:
        """The deployment's custom agents (the roster the registrar reads at start)."""
        payload = await self._get("/agents/custom")
        return list(payload or []) if isinstance(payload, list) else []

    async def ask_as_agent(self, agent_id: str, question: str, connection: str = "", *,
                           asker: str = "") -> dict:
        """One question through `/ask` AS a custom agent, folded to one answer — the same
        fold the HTTP door makes server-side (`custom_agents/reach.fold_ask`): headline,
        the SQL that ran, rows (capped), receipt and investigation id. This process is the
        principal (`api:mcp:<asker>`), attributed by the ask door when no session is in scope."""
        body = {
            "question": question, "connection_id": connection or "workspace",
            "agent_id": agent_id, "depth": "quick", "allow_clarify": False,
            "principal_ref": f"api:mcp:{(asker or 'anonymous')[:64]}", "history": [],
            "session_id": "",
        }
        acc: dict[str, Any] = {"agent_id": agent_id, "question": question, "headline": "",
                               "sql": "", "columns": [], "rows": [], "row_count": None,
                               "receipt_id": "", "investigation_id": "", "error": "",
                               "truncated": False}
        deltas: list[str] = []
        async for ev in self._stream_sse("POST", "/ask", body, timeout=self.deep_timeout):
            t = ev.get("type")
            if t == "headline":
                acc["headline"] = str(ev.get("headline") or "")
            elif t == "headline_delta":
                deltas.append(str(ev.get("headline") or ev.get("delta") or ""))
            elif t == "sql":
                acc["sql"] = str(ev.get("sql") or "")
            elif t == "columns" and not acc["columns"]:
                acc["columns"] = list(ev.get("columns") or [])
            elif t == "rows":
                rows = list(ev.get("rows") or [])
                room = 200 - len(acc["rows"])
                if room > 0:
                    acc["rows"].extend(rows[:room])
                if len(rows) > room:
                    acc["truncated"] = True
                if ev.get("row_count") is not None:
                    acc["row_count"] = ev.get("row_count")
            elif t == "receipt_id":
                acc["receipt_id"] = str(ev.get("receipt_id") or ev.get("id") or "")
            elif t == "error":
                acc["error"] = str(ev.get("message") or ev.get("error") or "error")
            if ev.get("investigation_id") and not acc["investigation_id"]:
                acc["investigation_id"] = str(ev["investigation_id"])
            # The quick path names its turn `inv_id` on the done frame (as `ask` below
            # already reads); the agent fold read one spelling and lost the turn (2026-10-03).
            if ev.get("type") == "done" and ev.get("inv_id") and not acc["investigation_id"]:
                acc["investigation_id"] = str(ev["inv_id"])
        if not acc["headline"] and deltas:
            acc["headline"] = max(deltas, key=len)
        if acc["row_count"] is None and acc["rows"]:
            acc["row_count"] = len(acc["rows"])
        return acc

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
                elif t in ("answer_report", "ada_report"):  # ada_report = deprecated wire alias (U9)
                    acc["report"], acc["report_kind"] = ev.get("answer_report") or ev.get("ada_report"), "ada"
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

    # ── traces (VA-5) ────────────────────────────────────────────────────────
    # Three calls, narrowing: which runs → one run's shape → one span's payload.
    # There is deliberately no "give me the whole trace": that response is 1.2 MB
    # for a 1,140-event run, and a tool whose success case floods the caller's
    # context is not a usable tool.

    async def list_runs(self, *, limit: int = 20, investigation_id: Optional[str] = None,
                        agent_id: Optional[str] = None) -> Any:
        return await self._get("/traces", params={
            "limit": limit, "investigation_id": investigation_id, "agent_id": agent_id})

    async def inspect_run(self, trace_id: str, *, top: int = 8) -> Any:
        return await self._get(f"/traces/{trace_id}/summary", params={"top": top})

    async def run_span(self, trace_id: str, span_id: str) -> Any:
        return await self._get(f"/traces/{trace_id}/spans/{span_id}")

    # ── DE-2b: the organisation's agent policy, as the API answers it ─────────────
    async def agent_policy(self) -> dict:
        return await self._get("/org-settings/agent-policy")

    # ── Phase 7 of the 2027 study: the ledger API ──────────────────────────────────
    async def contract(self) -> dict:
        return await self._get("/ledger/v1/contract")

    async def read_claims(self, *, connection: Optional[str] = None, kind: Optional[str] = None,
                          author: Optional[str] = None, as_of: Optional[str] = None, limit: int = 50) -> Any:
        return await self._get("/ledger/v1/claims", params={"connection_id": connection, "kind": kind, "author": author,
                                                            "as_of": as_of, "limit": limit})

    async def read_restatements(self, *, since: str = "", connection: Optional[str] = None, limit: int = 100) -> Any:
        return await self._get("/ledger/v1/restatements", params={"since": since or None, "connection_id": connection, "limit": limit})

    async def post_claim(self, body: dict) -> Any:
        return await self._post("/ledger/v1/claims", json_body=body)

    # ── DE-2c: the knowledge tools, through the API like everything else ───────────
    async def search_graph(self, connection: str, query: str, *, limit: int = 10) -> dict:
        return await self._get(f"/knowledge/{connection}/graph/search", params={"q": query, "limit": limit})

    async def describe_entity(self, connection: str, entity: str) -> dict:
        return await self._get(f"/knowledge/{connection}/entity/{entity}")

    async def get_table_health(self, connection: str, table: str) -> dict:
        return await self._get(f"/knowledge/{connection}/table-health", params={"table": table})

    async def list_trusted_queries(self, connection: str, *, limit: int = 25) -> dict:
        return await self._get(f"/knowledge/{connection}/trusted-queries", params={"limit": limit})


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
