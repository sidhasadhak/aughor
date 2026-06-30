"""Notion knowledge connector — indexes Notion pages into aughor_documents.

DSN:   notion://  (sentinel)
Meta:  {
  "integration_token": "secret_…",      (Notion integration token)
  "database_ids":      "id1,id2",       (optional — comma-sep database IDs to sync)
  "page_limit":        "200"
}

Auth: Bearer {integration_token}
API:  Notion API v1  (https://api.notion.com/v1)

To access content, the integration must be invited to the workspace or
specific pages/databases via "Share → Invite → your integration".

Optional dep: none — uses requests.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterator

import requests

logger = logging.getLogger(__name__)

_STATE_DIR  = Path("data")
_PAGE_SIZE  = 100
_NOTION_VER = "2022-06-28"


def _blocks_to_text(blocks: list[dict]) -> str:
    """Convert Notion block JSON to readable plain text."""
    lines: list[str] = []
    for block in blocks:
        btype = block.get("type", "")
        content = block.get(btype, {})
        rich_texts = content.get("rich_text", [])
        text = "".join(rt.get("plain_text", "") for rt in rich_texts)

        if btype in ("heading_1", "heading_2", "heading_3"):
            lines.append(f"\n{'#' * int(btype[-1])} {text}")
        elif btype == "bulleted_list_item":
            lines.append(f"• {text}")
        elif btype == "numbered_list_item":
            lines.append(f"1. {text}")
        elif btype == "to_do":
            done = "✓" if content.get("checked") else "○"
            lines.append(f"{done} {text}")
        elif btype == "code":
            lang = content.get("language", "")
            lines.append(f"```{lang}\n{text}\n```")
        elif btype == "quote":
            lines.append(f"> {text}")
        elif btype == "divider":
            lines.append("---")
        elif text:
            lines.append(text)
    return "\n".join(lines).strip()


class NotionSync:
    """Fetches Notion pages and indexes them into aughor_documents."""

    def __init__(self, connection_id: str, meta: dict) -> None:
        self._conn_id   = connection_id
        self._token     = meta.get("integration_token", "")
        self._db_ids    = [d.strip() for d in meta.get("database_ids", "").split(",") if d.strip()]
        self._page_limit = int(meta.get("page_limit", 200))
        self._state_path = _STATE_DIR / f"knowledge_sync_{connection_id}.json"

        if not self._token:
            raise ValueError("Notion connector requires integration_token")

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization":   f"Bearer {self._token}",
            "Notion-Version":  _NOTION_VER,
            "Content-Type":    "application/json",
        })

    # ── State ──────────────────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        try:
            if self._state_path.exists():
                return json.loads(self._state_path.read_text())
        except Exception:
            pass
        return {}

    def _save_state(self, state: dict) -> None:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(state, indent=2))

    # ── Notion API ─────────────────────────────────────────────────────────────

    def _search_pages(self) -> Iterator[dict]:
        """List all pages the integration can access."""
        cursor = None
        fetched = 0
        while True:
            payload: dict = {
                "filter":    {"property": "object", "value": "page"},
                "page_size": _PAGE_SIZE,
            }
            if cursor:
                payload["start_cursor"] = cursor
            resp = self._session.post(
                "https://api.notion.com/v1/search",
                json=payload,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            for result in data.get("results", []):
                yield result
                fetched += 1
                if fetched >= self._page_limit:
                    return
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    def _query_database(self, database_id: str) -> Iterator[dict]:
        """List all pages in a specific database."""
        cursor = None
        fetched = 0
        while True:
            payload: dict = {"page_size": _PAGE_SIZE}
            if cursor:
                payload["start_cursor"] = cursor
            resp = self._session.post(
                f"https://api.notion.com/v1/databases/{database_id}/query",
                json=payload,
                timeout=20,
            )
            if not resp.ok:
                break
            data = resp.json()
            for result in data.get("results", []):
                yield result
                fetched += 1
                if fetched >= self._page_limit:
                    return
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    def _get_page_blocks(self, page_id: str) -> list[dict]:
        """Fetch all block content for a page."""
        blocks: list[dict] = []
        cursor = None
        while True:
            params: dict = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            resp = self._session.get(
                f"https://api.notion.com/v1/blocks/{page_id}/children",
                params=params,
                timeout=20,
            )
            if not resp.ok:
                break
            data = resp.json()
            blocks.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return blocks

    def _page_title(self, page: dict) -> str:
        props = page.get("properties", {})
        for key in ("title", "Title", "Name"):
            prop = props.get(key, {})
            if prop.get("type") == "title":
                parts = prop.get("title", [])
                return "".join(p.get("plain_text", "") for p in parts).strip()
        return "Untitled"

    # ── Main sync ──────────────────────────────────────────────────────────────

    def sync(self) -> dict:
        """Sync all accessible pages. Returns sync stats."""
        from aughor.kernel.registries.ingestion import ingest
        state   = self._load_state()
        count   = 0
        sources = {"search": 0, **{db: 0 for db in self._db_ids}}

        def _index_page(page: dict, source_label: str) -> None:
            nonlocal count
            page_id = page.get("id", "").replace("-", "")
            title   = self._page_title(page)
            blocks  = self._get_page_blocks(page_id)
            text    = _blocks_to_text(blocks)
            if len(text.strip()) < 40:
                return
            source_url = page.get("url", "")
            doc_id = f"notion_{self._conn_id}_{page_id}"
            ingest(
                "knowledge",
                text=text,
                title=title,
                source=f"notion:{source_label}",
                doc_id=doc_id,
                source_url=source_url,
            )
            count += 1

        # Search-based (catches workspace pages)
        if not self._db_ids:
            for page in self._search_pages():
                try:
                    _index_page(page, "search")
                    sources["search"] = sources.get("search", 0) + 1
                except Exception as exc:
                    logger.debug("Notion: skipped page: %s", exc)

        # Database-specific
        for db_id in self._db_ids:
            for page in self._query_database(db_id):
                try:
                    _index_page(page, db_id)
                    sources[db_id] = sources.get(db_id, 0) + 1
                except Exception as exc:
                    logger.debug("Notion: skipped db page: %s", exc)

        state["last_sync"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z")
        state["pages_indexed"] = count
        state["sources"] = sources
        self._save_state(state)
        logger.info("Notion sync: %d pages indexed for %s", count, self._conn_id)
        return {"pages_indexed": count, "sources": sources}

    def test(self) -> tuple[bool, str]:
        try:
            resp = self._session.post(
                "https://api.notion.com/v1/search",
                json={"page_size": 1},
                timeout=10,
            )
            resp.raise_for_status()
            return True, "Notion connected (integration token valid)"
        except Exception as e:
            return False, str(e)

    def status(self) -> dict:
        state = self._load_state()
        return {
            "connection_id":  self._conn_id,
            "last_sync":      state.get("last_sync"),
            "pages_indexed":  state.get("pages_indexed", 0),
            "sources":        state.get("sources", {}),
        }
