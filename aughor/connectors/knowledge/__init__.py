# Knowledge connectors — Confluence and Notion (feed the aughor_documents pipeline)
"""What both connectors share: indexing one page, and saying so when a page is not indexed.

A page used to vanish three ways with nothing recorded: under 40 characters it was skipped
before indexing; between 40 and the chunker's floor it indexed to zero chunks; and a sink
failure came back as ``{}`` (``ingest`` never raises). The last two were still COUNTED as
indexed. Now a page counts only when it landed with at least one chunk, and every other
page is listed with its reason on the source's status.
"""
from __future__ import annotations

from typing import Optional

#: How many skipped pages a source's status keeps by name — the count is always whole.
MAX_SKIPPED_LISTED = 100


def index_page(*, text: str, title: str, source: str, doc_id: str,
               source_url: str = "") -> Optional[str]:
    """Index one page. Returns None when it landed, else the reason it did not."""
    from aughor.kernel.registries.ingestion import ingest

    if not text.strip():
        return "the page has no text"
    entry = ingest("knowledge", text=text, title=title, source=source,
                   doc_id=doc_id, source_url=source_url)
    if not entry:
        return "the document index did not accept it (the API log has the cause)"
    if not entry.get("chunk_count"):
        floor = entry.get("min_chars")
        return (f"too short to index — {len(text.strip())} characters"
                + (f", under the minimum chunk length of {floor}" if floor else ""))
    return None


def skipped_entry(title: str, url: str, reason: str) -> dict:
    return {"title": title, "url": url, "reason": reason}
