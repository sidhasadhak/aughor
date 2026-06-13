"""Action triggers, recommendation execution, action logs, knowledge sync, federation, CRM sync."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.licensing import Capability, gate

from aughor.db.connection import open_connection_for
from aughor.db.registry import add_connection, get_dsn, get_meta

logger = logging.getLogger(__name__)
router = APIRouter(tags=["actions"])


# ── Action Triggers ───────────────────────────────────────────────────────────

@router.get("/actions/triggers")
def list_action_triggers():
    from aughor.actions.store import list_triggers
    # to_safe_dict masks the credential URL — the raw secret never leaves the server.
    return {"triggers": [t.to_safe_dict() for t in list_triggers()]}


class _TriggerBody(BaseModel):
    name:       str
    type:       str = "webhook"
    url:        str
    headers:    dict = {}
    enabled:    bool = True
    channel:    Optional[str] = None
    project:    Optional[str] = None
    issue_type: Optional[str] = None


@router.post("/actions/triggers", status_code=201, dependencies=[gate(Capability.ACTION_HUB)])
def create_action_trigger(body: _TriggerBody):
    from aughor.actions.models import ActionTrigger
    from aughor.actions.store  import save_trigger
    trigger = ActionTrigger(
        id="", name=body.name, type=body.type, url=body.url,
        headers=body.headers, enabled=body.enabled,
        channel=body.channel, project=body.project, issue_type=body.issue_type,
    )
    return save_trigger(trigger).to_safe_dict()


@router.put("/actions/triggers/{trigger_id}", dependencies=[gate(Capability.ACTION_HUB)])
def update_action_trigger(trigger_id: str, body: _TriggerBody):
    from aughor.actions.models import ActionTrigger
    from aughor.actions.store  import save_trigger, get_trigger
    from aughor.secretvault    import is_masked
    existing = get_trigger(trigger_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Trigger not found")
    # The API returns a masked URL; if the UI sends that mask back unchanged, keep the
    # real secret rather than overwriting it with bullets.
    url = existing.url if is_masked(body.url) else body.url
    trigger = ActionTrigger(
        id=trigger_id, name=body.name, type=body.type, url=url,
        headers=body.headers, enabled=body.enabled,
        channel=body.channel, project=body.project, issue_type=body.issue_type,
    )
    return save_trigger(trigger).to_safe_dict()


@router.delete("/actions/triggers/{trigger_id}", status_code=200)
def delete_action_trigger(trigger_id: str):
    from aughor.actions.store import delete_trigger
    if not delete_trigger(trigger_id):
        raise HTTPException(status_code=404, detail="Trigger not found")
    return {"message": "Trigger deleted"}


@router.post("/actions/triggers/{trigger_id}/test")
def test_action_trigger(trigger_id: str):
    """Fire a test payload to the trigger URL."""
    import datetime
    from aughor.actions.store    import get_trigger
    from aughor.actions.models   import ActionPayload
    from aughor.actions.executor import fire_action
    trigger = get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")
    test_payload = ActionPayload(
        investigation_id="test_inv", rec_index=0,
        recommendation="[TEST] This is a test action from Aughor",
        metric_name="test_metric", headline="Test fire from Action Hub",
        trigger_id=trigger_id,
        triggered_at=datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    log = fire_action(trigger, test_payload)
    return {"status": log.status, "http_status": log.http_status, "error": log.error}


@router.post("/investigations/{inv_id}/recommendations/{rec_index}/execute")
def execute_recommendation_action(inv_id: str, rec_index: int, body: dict):
    """Fire a configured trigger for a specific recommendation."""
    import datetime, json as _json
    from aughor.actions.store    import get_trigger
    from aughor.actions.models   import ActionPayload
    from aughor.actions.executor import fire_action
    from aughor.db.history       import get_investigation

    trigger_id = body.get("trigger_id")
    if not trigger_id:
        raise HTTPException(status_code=400, detail="trigger_id required")
    trigger = get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")
    inv = get_investigation(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")

    rec_text = f"Recommendation #{rec_index} from investigation {inv_id}"
    try:
        report = inv.get("report_json") or {}
        if isinstance(report, str):
            report = _json.loads(report)
        recs = report.get("recommended_actions", [])
        if isinstance(recs, list) and rec_index < len(recs):
            item = recs[rec_index]
            rec_text = item if isinstance(item, str) else item.get("text", rec_text)
    except Exception:
        pass

    payload = ActionPayload(
        investigation_id=inv_id, rec_index=rec_index, recommendation=rec_text,
        metric_name=body.get("metric_name", ""), headline=inv.get("headline"),
        trigger_id=trigger_id,
        triggered_at=datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    return fire_action(trigger, payload).to_dict()


class _SendFindingBody(BaseModel):
    text:        str                    # the finding / claim to share
    metric_name: Optional[str] = None
    headline:    Optional[str] = None   # context line (e.g. domain · angle)
    source_id:   Optional[str] = None   # insight_id / canvas_id / conn_id for provenance


@router.post("/actions/triggers/{trigger_id}/send", dependencies=[gate(Capability.ACTION_HUB)])
def send_finding_to_trigger(trigger_id: str, body: _SendFindingBody):
    """Share an arbitrary finding (Briefing/Hub insight) to a configured trigger.

    Powers the finding-level 'Share' action — fires the same Slack/webhook/Jira
    delivery path as recommendation execution, but with a free-form finding payload
    instead of an investigation recommendation.
    """
    import datetime
    from aughor.actions.store    import get_trigger
    from aughor.actions.models   import ActionPayload
    from aughor.actions.executor import fire_action

    if not (body.text or "").strip():
        raise HTTPException(status_code=400, detail="text required")
    trigger = get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    payload = ActionPayload(
        investigation_id=body.source_id or "", rec_index=0,
        recommendation=body.text,
        metric_name=body.metric_name or "", headline=body.headline,
        trigger_id=trigger_id,
        triggered_at=datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    return fire_action(trigger, payload).to_dict()


@router.get("/actions/logs")
def list_action_logs(limit: int = 100, trigger_id: Optional[str] = None):
    from aughor.actions.store import list_logs
    return {"logs": list_logs(limit=limit, trigger_id=trigger_id)}


# ── Knowledge Sync ────────────────────────────────────────────────────────────

@router.post("/connections/{conn_id}/knowledge-sync", status_code=202)
async def trigger_knowledge_sync(conn_id: str):
    """Trigger a Confluence or Notion knowledge sync for a connection."""
    try:
        conn_type, _ = get_dsn(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    meta = get_meta(conn_id)

    async def _run():
        try:
            if conn_type == "confluence":
                from aughor.connectors.knowledge.confluence import ConfluenceSync
                syncer = ConfluenceSync(conn_id, meta)
            elif conn_type == "notion":
                from aughor.connectors.knowledge.notion import NotionSync
                syncer = NotionSync(conn_id, meta)
            else:
                return
            result = syncer.sync()
            logger.info("Knowledge sync complete for %s: %s", conn_id, result)
        except Exception as exc:
            logger.warning("Knowledge sync failed for %s: %s", conn_id, exc)

    asyncio.create_task(_run())
    return {"message": f"Knowledge sync triggered for {conn_id} ({conn_type})", "async": True}


@router.get("/connections/{conn_id}/knowledge-sync/status")
def get_knowledge_sync_status(conn_id: str):
    try:
        conn_type, _ = get_dsn(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    meta = get_meta(conn_id)
    try:
        if conn_type == "confluence":
            from aughor.connectors.knowledge.confluence import ConfluenceSync
            syncer = ConfluenceSync(conn_id, meta)
        elif conn_type == "notion":
            from aughor.connectors.knowledge.notion import NotionSync
            syncer = NotionSync(conn_id, meta)
        else:
            return {"message": "Not a knowledge connector"}
        return syncer.status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Federation ────────────────────────────────────────────────────────────────

class _FederateRequest(BaseModel):
    name: str
    connection_ids: list[str]


@router.post("/connections/federate", status_code=201, dependencies=[gate(Capability.FEDERATION)])
async def create_federated_connection(req: _FederateRequest):
    if len(req.connection_ids) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 connection_ids to federate")
    from aughor.connectors.federated import FederatedConnection
    meta = {"connection_ids": req.connection_ids}
    try:
        fed = FederatedConnection(connection_id="preview", meta=meta)
        ok, msg = fed.test()
        fed.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Federation failed: {e}")
    if not ok:
        raise HTTPException(status_code=400, detail=f"Federation test failed: {msg}")
    conn_id = add_connection(name=req.name, conn_type="federated", dsn="", meta=meta)
    return {"id": conn_id, "message": "Federated connection created", "test_result": msg}


@router.get("/connections/{conn_id}/federation-members")
async def get_federation_members(conn_id: str):
    loop = asyncio.get_event_loop()
    try:
        conn = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    if not hasattr(conn, "federation_members"):
        raise HTTPException(status_code=400, detail="Not a federated connection")

    def _work():
        try:
            return conn.federation_members()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    try:
        members = await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"connection_id": conn_id, "members": members}


# ── CRM / API Sync ────────────────────────────────────────────────────────────

@router.post("/connections/{conn_id}/sync")
async def trigger_sync(conn_id: str, incremental: bool = True):
    try:
        conn = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    if not hasattr(conn, "sync_all"):
        raise HTTPException(status_code=400, detail="Not a syncable API connector")

    async def _run():
        try:
            conn.sync_all(incremental=incremental)
        except Exception as exc:
            logger.warning("Sync failed for %s: %s", conn_id, exc)

    asyncio.create_task(_run())
    return {"message": f"Sync triggered for {conn_id}", "incremental": incremental}


@router.get("/connections/{conn_id}/sync-status")
async def get_sync_status(conn_id: str):
    loop = asyncio.get_event_loop()
    try:
        conn = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    if not hasattr(conn, "sync_status"):
        return {"message": "Not a syncable connector"}

    def _work():
        try:
            return conn.sync_status()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    try:
        return await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
