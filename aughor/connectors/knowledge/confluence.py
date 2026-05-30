"""Confluence knowledge connector — indexes Confluence pages into aughor_documents.

Unlike database connectors, this does NOT implement execute()/get_schema().
It fetches Confluence wiki pages and indexes them into the existing Qdrant
document collection so they appear in investigation synthesis context.

DSN:   confluence://  (sentinel)
Meta:  {
  "base_url":    "https://yourorg.atlassian.net",
  "username":    "user@example.com",
  "api_token":   "ATATT3…",          (Atlassian API token)
  "space_keys":  "ENG,PROD,DATA",    (comma-sep, or empty = all spaces)
  "page_limit":  "500"               (optional, max pages to sync)
}

Auth: HTTP Basic — username + API token.
URL:  https://yourorg.atlassian.net/wiki/rest/api/content

Optional dep: none — uses requests (always available).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Iterator

import requests

logger = logging.getLogger(__name__)

_STATE_DIR = Path("data")
_PAGE_SIZE  = 50       # Confluence max per request is 100; 50 is safe


def _html_to_text(html: str) -> str:
    """Strip Confluence storage-format XML/HTML to plain text."""
    # Remove script/style blocks
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.I)
    # Replace block-level tags with newlines
    html = re.sub(r"<(p|br|li|h[1-6]|div|tr)[^>]*>", "\n", html, flags=re.I)
    # Strip remaining tags
    html = re.sub(r"<[^>]+>", " ", html)
    # Decode common HTML entities
    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">") \
               .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    # Collapse whitespace
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", html)).strip()


class ConfluenceSync:
    """Fetches Confluence pages and indexes them into aughor_documents."""

    def __init__(self, connection_id: str, meta: dict) -> None:
        self._conn_id   = connection_id
        self._base_url  = meta.get("base_url", "").rstrip("/")
        self._username  = meta.get("username", "")
        self._api_token = meta.get("api_token", "")
        self._space_keys = [s.strip() for s in meta.get("space_keys", "").split(",") if s.strip()]
        self._page_limit = int(meta.get("page_limit", 500))
        self._state_path = _STATE_DIR / f"knowledge_sync_{connection_id}.json"

        if not (self._base_url and self._username and self._api_token):
            raise ValueError("Confluence connector requires base_url, username, and api_token")

        self._session = requests.Session()
        self._session.auth = (self._username, self._api_token)
        self._session.headers.update({"Accept": "application/json"})

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

    # ── Confluence REST API ────────────────────────────────────────────────────

    def _list_spaces(self) -> list[str]:
        if self._space_keys:
            return self._space_keys
        resp = self._session.get(
            f"{self._base_url}/wiki/rest/api/space",
            params={"limit": 50, "type": "global"},
            timeout=15,
        )
        resp.raise_for_status()
        return [s["key"] for s in resp.json().get("results", [])]

    def _iter_pages(self, space_key: str) -> Iterator[dict]:
        """Yield page dicts with {id, title, body.storage.value} from a space."""
        start = 0
        fetched = 0
        while True:
            resp = self._session.get(
                f"{self._base_url}/wiki/rest/api/content",
                params={
                    "type":   "page",
                    "spaceKey": space_key,
                    "expand": "body.storage",
                    "limit":  _PAGE_SIZE,
                    "start":  start,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            for page in results:
                yield page
                fetched += 1
                if fetched >= self._page_limit:
                    return
            if not data.get("_links", {}).get("next"):
                break
            start += _PAGE_SIZE

    # ── Main sync ──────────────────────────────────────────────────────────────

    def sync(self) -> dict[str, int]:
        """Sync all pages. Returns {space_key: pages_indexed}."""
        from aughor.knowledge.indexer import index_text
        state = self._load_state()
        results: dict[str, int] = {}

        spaces = self._list_spaces()
        logger.info("Confluence sync: %d spaces for %s", len(spaces), self._conn_id)

        for space_key in spaces:
            count = 0
            for page in self._iter_pages(space_key):
                page_id = page.get("id", "")
                title   = page.get("title", "Untitled")
                html    = page.get("body", {}).get("storage", {}).get("value", "")
                text    = _html_to_text(html)
                if len(text.strip()) < 40:
                    continue
                source_url = f"{self._base_url}/wiki/spaces/{space_key}/pages/{page_id}"
                doc_id = f"confluence_{self._conn_id}_{page_id}"
                try:
                    index_text(
                        text=text,
                        title=f"[{space_key}] {title}",
                        source=f"confluence:{space_key}",
                        doc_id=doc_id,
                        source_url=source_url,
                    )
                    count += 1
                except Exception as exc:
                    logger.debug("Confluence: skipped page %s: %s", page_id, exc)
            results[space_key] = count
            logger.info("Confluence: indexed %d pages from space %s", count, space_key)

        state["last_sync"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
        state["pages_indexed"] = {k: results.get(k, 0) for k in spaces}
        self._save_state(state)
        return results

    def test(self) -> tuple[bool, str]:
        try:
            resp = self._session.get(
                f"{self._base_url}/wiki/rest/api/space",
                params={"limit": 1},
                timeout=10,
            )
            resp.raise_for_status()
            total = resp.json().get("size", "?")
            return True, f"Confluence connected — {total} accessible spaces"
        except Exception as e:
            return False, str(e)

    def status(self) -> dict:
        state = self._load_state()
        return {
            "connection_id": self._conn_id,
            "last_sync":     state.get("last_sync"),
            "pages_indexed": state.get("pages_indexed", {}),
            "space_keys":    self._space_keys,
        }
