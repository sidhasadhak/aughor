"""An image a person uploads to place on a cockpit (the canvas, docs/COCKPIT_CANVAS_2026-10-08.md, B4).

The bytes go where every uploaded object goes — a volume under the connection's catalog, through
``aughor/files/ops.py`` — in one volume per connection, ``cockpit-images``. What this module adds
is the judgement a cockpit needs of them:

- **what it is, read from the bytes.** A client's declared type is not read; the first bytes are.
  PNG, JPEG, GIF, WebP and SVG, up to 5 MB (the user's call, 2026-10-08). An SVG is text that
  can carry script; one that does is refused here, and one that is served carries a policy that
  runs nothing even so.
- **whose it is.** The uploader is kept on the object's row (``created_by``) and shown beside the
  image: a static thing says it is static, and who placed it.
- **where it may be shown.** An image is placed by its object id, and a cockpit may place only
  an image of its own connection's cockpit volume — never another connection's, never a document
  from another volume. The reader of a cockpit reads the image with their own access.
"""
from __future__ import annotations

import re
from typing import Any, Optional

#: The one volume, per connection, cockpit images live in.
VOLUME = "cockpit-images"
#: The cap, stated in the refusal.
MAX_BYTES = 5 * 1024 * 1024
#: What an image may be, by what its bytes say.
TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml")
_TYPE_WORDS = "PNG, JPEG, GIF, WebP or SVG"

#: What an SVG may not carry: script, an event handler, a script URL, or a foreign document.
_SVG_UNSAFE = re.compile(
    r"<\s*script|\bon[a-z]+\s*=|javascript\s*:|<\s*foreignObject|<\s*iframe|<\s*embed|<\s*object|"
    r"data\s*:\s*text/html|<\s*set\b|<\s*animate\b[^>]*\bhref", re.IGNORECASE)


class Refused(Exception):
    """Why an image is not taken, in a sentence a person can act on."""


def sniffed(data: bytes) -> tuple[str, str]:
    """``(content type, "")`` from the bytes, or ``("", why)`` when they are not an image a
    cockpit shows."""
    if not data:
        return "", "The file is empty."
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", ""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", ""
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", ""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ""
    head = data[:4096].lstrip()
    if head[:1] == b"<" and (head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in head):
        text = data.decode("utf-8", "replace")
        if "<svg" not in text:
            return "", f"The file is not a {_TYPE_WORDS} image."
        if _SVG_UNSAFE.search(text):
            return "", "The SVG carries script, an event handler or an embedded document, which a cockpit does not run."
        return "image/svg+xml", ""
    return "", f"The file is not a {_TYPE_WORDS} image."


def _stamp(obj: Any) -> dict:
    return {"object": obj.id, "file_name": obj.name, "uploaded_by": obj.created_by or "",
            "uploaded_at": obj.created_at, "content_type": obj.mime_type, "bytes": int(obj.size_bytes or 0),
            "readable": True, "why": ""}


def volume_for(connection_id: str):
    """This connection's cockpit volume, made on first use. The catalog a volume hangs under is
    the connection's own, synced from the registry; a connection newer than the last sync is
    synced now rather than refused."""
    from aughor.files import ops
    from aughor.metastore import get_catalog
    if get_catalog(connection_id) is None:
        from aughor.metastore.sync import ensure_catalogs_for_connections
        ensure_catalogs_for_connections()
    return ops.create_volume(connection_id, VOLUME)


def put_image(connection_id: str, name: str, data: bytes, declared: str = "", *, uploaded_by: str) -> dict:
    """Take an image into this connection's cockpit volume, or refuse it with the reason. Returns
    the stamp a cockpit shows beside it."""
    from aughor.files import ops
    if len(data) > MAX_BYTES:
        raise Refused(f"{name or 'The file'} is {len(data) / 1048576:.1f} MB; the cap is {MAX_BYTES // 1048576} MB.")
    content_type, why = sniffed(data)
    if not content_type:
        said = why
        if declared and "not a" in why:
            said = f"{why[:-1]} (it was sent as {declared})."
        raise Refused(said)
    if not (uploaded_by or "").strip():
        raise Refused("An image is kept with the name of the person who uploaded it. None was given.")
    vol = volume_for(connection_id)
    obj = ops.put_object(vol.id, name or "image", data, mime_type=content_type, created_by=uploaded_by.strip())
    return _stamp(obj)


def _held(connection_id: str, object_id: str):
    """The object, if it is one of this connection's cockpit images — else None."""
    from aughor.files import store
    if not isinstance(object_id, str) or not object_id:
        return None
    obj = store.get_object(object_id)
    if obj is None:
        return None
    vol = store.get_volume(obj.volume_id)
    if vol is None or vol.catalog_id != connection_id or vol.name != VOLUME:
        return None
    return obj


def stamp_of(connection_id: str, object_id: str) -> Optional[dict]:
    """What a cockpit shows beside this image, or None when it is not one this connection's
    cockpits may place."""
    obj = _held(connection_id, object_id)
    return _stamp(obj) if obj is not None else None


NOT_HELD = "This image is not in this connection's cockpit volume, or it is gone."


def stamps_for(connection_id: str, spec: Any) -> dict[str, dict]:
    """A stamp for every image a spec places, by object id. One the cockpit may not show stands
    as its caption and says why — withheld is said, never an empty box."""
    out: dict[str, dict] = {}
    elements = (spec or {}).get("elements") if isinstance(spec, dict) else None
    for el in (elements or {}).values():
        if not isinstance(el, dict) or el.get("type") != "Image" or not isinstance(el.get("props"), dict):
            continue
        object_id = str(el["props"].get("object") or "")
        if not object_id or object_id in out:
            continue
        out[object_id] = stamp_of(connection_id, object_id) or {
            "object": object_id, "file_name": "", "uploaded_by": "", "uploaded_at": "", "content_type": "",
            "bytes": 0, "readable": False, "why": NOT_HELD}
    return out


def not_held(connection_id: str, spec: Any) -> list[str]:
    """A sentence for each image a spec places that this connection's cockpits may not: what a
    keep is refused with."""
    said = []
    elements = (spec or {}).get("elements") if isinstance(spec, dict) else None
    for key, el in (elements or {}).items():
        if not isinstance(el, dict) or el.get("type") != "Image" or not isinstance(el.get("props"), dict):
            continue
        object_id = str(el["props"].get("object") or "")
        if _held(connection_id, object_id) is None:
            said.append(f'The image "{el["props"].get("caption") or key}" places the object "{object_id}", which is not '
                        "an image uploaded to this connection's cockpits.")
    return said


def read_image(connection_id: str, object_id: str) -> tuple[bytes, str]:
    """The bytes and the content type, for a reader of a cockpit on this connection."""
    from aughor.files import ops
    obj = _held(connection_id, object_id)
    if obj is None:
        raise Refused(NOT_HELD)
    try:
        data = ops.read_object(obj.id)
    except (ValueError, OSError) as exc:
        raise Refused(f"The image's bytes could not be read: {exc}") from exc
    content_type = obj.mime_type if obj.mime_type in TYPES else sniffed(data)[0] or "application/octet-stream"
    return data, content_type
