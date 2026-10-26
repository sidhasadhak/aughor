"""Comments on a Google file, read onto a decision (the decision-framework study §3.2; the user's call of 2026-10-27).

People argue a decision in the comments of a Sheet, a Slides deck or a Doc. A person names ONE file on a decision —
its link — and the platform reads that file's comments through the person's own Google grant (the *Google Drive
comments* card, `integrations/providers.py`), never listing, searching or reading any other file: invited capture,
never a crawl. Each comment becomes a *said* claim in its author's name, warranted by the conversation — the file and
comment id as the reference, a hash of the words, the words themselves (written in a document the file's owner shared
with the person who named it), and the cell, slide or quoted text it points at as the locator — and is added to the
decision as LATER evidence, dated, never as something it relied on when it was decided. Reading the same file again
adds only what is new, and a comment edited since restates its claim. Nothing is approved from a comment: a Google
comment's author address is not always given, and an approval is a named, verified person's.
"""
from __future__ import annotations

import re
from typing import Optional

FLAG = "arrivals.google_comments"
OPERATION = "drive.comments.list"
#: The comments read from one file at most — more are said, never silently dropped.
MAX_COMMENTS = 100
_FILE_ID = re.compile(r"/(?:spreadsheets|presentation|document|file)/d/([A-Za-z0-9_-]{20,})|[?&]id=([A-Za-z0-9_-]{20,})")


class CommentsRefused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def door_on() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def file_id_of(link: str) -> str:
    """The Drive file id a Sheets, Slides, Docs or Drive link names; "" when it names none."""
    m = _FILE_ID.search(link or "")
    return (m.group(1) or m.group(2)) if m else ""


def grant_for(user_id: str) -> Optional[str]:
    """The person's active Google grant that may read comments — its id, or None."""
    from aughor.integrations.operations import get_operation, missing_scopes
    from aughor.integrations.store import list_connections
    op = get_operation(OPERATION)
    for c in list_connections(user_id):
        if c.provider == "google" and c.status == "active" and op is not None and not missing_scopes(op, c.scopes):
            return c.id
    return None


def _locator(item: dict) -> str:
    quoted = ((item.get("quotedFileContent") or {}).get("value") or "").strip()
    anchor = str(item.get("anchor") or "").strip()
    return f"on “{quoted[:120]}”" if quoted else (f"at {anchor[:120]}" if anchor else "on the file")


def read_onto(decision_id: str, link: str, *, user_id: str, grant: str = "") -> dict:
    """Read one named file's comments onto a decision as later evidence. Says how many were read, how many were new,
    and how many were already held; refuses a link that names no file, a person with no grant, or a failed read."""
    from aughor.integrations.call import call_operation
    from aughor.record import claims as C
    from aughor.record import decisions as D
    fid = file_id_of(link)
    if not fid:
        raise CommentsRefused(422, "the link names no Google file — paste a Sheets, Slides, Docs or Drive link")
    first = D.get_decision(decision_id)
    if first is None:
        raise CommentsRefused(404, f"no decision {decision_id}")
    grant = grant or grant_for(user_id) or ""
    if not grant:
        raise CommentsRefused(409, "connect the Google Drive comments card first — this person has no Google grant "
                                   "that may read comments")
    got = call_operation(grant, OPERATION, {"file_id": fid}, actor=user_id or "unidentified")
    if got.status != "executed":
        raise CommentsRefused(502, f"Google did not give the comments ({got.status}): {got.message}")
    items = list((got.data or {}).get("items") or [])
    beyond = max(0, len(items) - MAX_COMMENTS) + (1 if (got.data or {}).get("next_page_token") else 0)
    d = D.latest_decision(first.source) or first
    held = {str(e.get("ref") or "") for e in (d.extra.get("evidence") or [])}
    added: list[dict] = []
    known = 0
    for it in items[:MAX_COMMENTS]:
        words = str(it.get("content") or "").strip()
        if not words or it.get("id") is None:
            continue
        ref = f"gdrive:{fid}:{it['id']}"
        author = it.get("author") or {}
        who = str(author.get("emailAddress") or author.get("displayName") or "someone").strip()
        where = _locator(it)
        warrant = C.said_warrant("conversation", ref, words, shared=True,
                                 detail=f"a comment by {who} {where}, in the Google file the decision names")
        claim = C.Claim(kind="said", tier="said", about=C.About(kind="connection", key=d.connection_id or ""),
                        statement=C.Statement(text=words[:1000]), status="Provisional", warrants=[warrant],
                        as_of=str(it.get("modifiedTime") or it.get("createdTime") or "")[:10],
                        author=f"person:{who}", author_kind="person",
                        extra={"decision": d.id, "via": "google comment", "file": fid, "locator": where,
                               "resolved": bool(it.get("resolved"))})
        cid = C.book(claim, key=C.claim_key("said", "gdrive", fid, str(it["id"])), conn_id=d.connection_id or None)
        if ref in held:
            known += 1
        else:
            added.append({**warrant.model_dump(), "claim": cid, "from": who, "at": D._now(), "added_later": True})
    if added:
        now = D._current(d)
        now.extra["evidence"] = list(now.extra.get("evidence") or []) + added
        now.extra.setdefault("google_files", [])
        if fid not in now.extra["google_files"]:
            now.extra["google_files"] = list(now.extra["google_files"]) + [fid]
        d = D.get_decision(D.book_decision(now)) or now
    return {"decision": d.id, "file": fid, "read": min(len(items), MAX_COMMENTS), "new": len(added),
            "already_held": known,
            "more": (f"the file holds more comments than the {MAX_COMMENTS} read" if beyond else "")}
