"""The public Trust Receipt (WP-10) — one signed, inspectable contract for any answer.

Per-mode receipt routes (`/answer/{conn}/{inv}/receipt`, `/chat/{conn}/{turn}/receipt`)
each returned the raw ledger artifact in its own shape. WP-10 introduces ONE receipt id (the
kernel ledger artifact id) and one `GET /receipt/{receipt_id}` that projects the raw ledger
receipt — artifact + lineage edges + the job that computed it — into a stable, signed public
contract, so every answer surface can open the same "why this number" object.

`build_public_receipt` is a pure projection (no I/O). `sign` / `verify` HMAC the canonical JSON
with a per-install server secret — this proves *the server issued this receipt* (and detects
tampering), NOT third-party non-repudiation (the secret is server-side).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from typing import Optional

PUBLIC_RECEIPT_VERSION = 1

# ledger artifact `kind` → the user-facing mode on the receipt.
_MODE = {
    "chat_answer": "quick", "chat": "quick",
    "ada_report": "deep", "ada": "deep", "answer": "deep",
    "insight": "explore", "builder": "builder",
    "monitor": "monitor", "brief": "brief",
}


def _mode(kind: str) -> str:
    return _MODE.get(kind or "", kind or "answer")


_SECRET_CACHE: Optional[bytes] = None
_SECRET_LOCK = threading.Lock()


def _server_secret() -> bytes:
    """The HMAC secret. Prefer the operator-set env (checked every call, so a rotation takes
    effect at once); else a stable per-install secret generated once and persisted in the
    ledger kv, then MEMOIZED for the process. Server-side only — never sent to a client."""
    global _SECRET_CACHE
    env = os.getenv("AUGHOR_RECEIPT_SECRET", "").strip()
    if env:
        return env.encode("utf-8")
    if _SECRET_CACHE is not None:
        return _SECRET_CACHE
    with _SECRET_LOCK:
        if _SECRET_CACHE is not None:                 # another thread generated it while we waited
            return _SECRET_CACHE
        try:
            from aughor.kernel.ledger import Ledger
            led = Ledger.default()
            sec = led.kv_get("receipt", "hmac_secret", None)
            if not sec:
                import secrets
                led.kv_put("receipt", "hmac_secret", secrets.token_hex(32))
                # Re-read so we adopt whatever actually persisted (accept-first) rather than a
                # value a concurrent process may have clobbered — the two converge on one secret.
                sec = led.kv_get("receipt", "hmac_secret", None)
            if sec:
                _SECRET_CACHE = str(sec).encode("utf-8")
                return _SECRET_CACHE
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "receipt HMAC secret unavailable from the ledger; using the process dev "
                          "fallback (signatures valid within this process only — set "
                          "AUGHOR_RECEIPT_SECRET in production)", counter="trust.receipt_secret")
    # Last resort (no ledger, e.g. a pure unit test). NOT memoized: keep trying the ledger on
    # the next call so a transient outage doesn't pin the process to the dev secret.
    return b"aughor-dev-receipt-secret"


def _canonical(receipt: dict) -> bytes:
    """Deterministic bytes for signing — the receipt minus its own signature, sorted keys."""
    body = {k: v for k, v in receipt.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sign(receipt: dict) -> str:
    """HMAC-SHA256 (hex) over the canonical receipt body."""
    return hmac.new(_server_secret(), _canonical(receipt), hashlib.sha256).hexdigest()


def verify(receipt: dict) -> bool:
    """True iff `receipt['signature']` matches a fresh HMAC of its body (constant-time)."""
    sig = receipt.get("signature") or ""
    if not isinstance(sig, str) or not sig:
        return False
    return hmac.compare_digest(sig, sign(receipt))


#: Lineage relations that belong on the receipt even though their ref is not a `guard:`.
#: `trusted` names the QUERY it reused, so it is written as `query:<question>` — matching on
#: the ref prefix alone silently dropped every one of them (see below).
_NON_GUARD_RELATIONS = ("trusted",)


def _guards_from_lineage(lineage: list) -> list[dict]:
    """Guard edges → guard rows for the receipt.

    A guard is on the receipt only because it FIRED, so `fired` is True; `action` is what it
    did (repaired vs merely flagged) and `caveat` is its human note.

    Matched on the RELATION as well as the ref prefix. Matching on `guard:` alone was a silent
    data-loss bug: the chat path writes its trusted-query provenance as
    ``("trusted", "query:<question>", note)``, so every trusted edge ever written was dropped
    here — and the frontend branch that renders it (`WhyThisNumber.tsx`, `action === "trusted"`)
    could never fire. The evidence existed at both ends and only the middle was missing.

    The `caveat` carried through is the promoter's authored warrant sentence, verbatim — e.g.
    "Consistency-verified (reproduces this connection's prior answer), NOT independently
    checked for correctness." That distinction is the whole point of surfacing this at all, so
    it is never paraphrased or shortened here.
    """
    out: list[dict] = []
    for e in lineage:
        ref = e.get("ref") or ""
        relation = e.get("relation") or ""
        if ref.startswith("guard:"):
            name = ref.split("guard:", 1)[1]
        elif relation in _NON_GUARD_RELATIONS:
            name = ref.split(":", 1)[1] if ":" in ref else ref
        else:
            continue
        out.append({
            "name": name,
            "fired": True,
            "action": relation,
            "caveat": e.get("detail") or "",
        })
    return out


def _metrics_from_lineage(lineage: list) -> dict:
    """The governed-metric enforcement view (B-7): which registered metrics were USED vs the
    answer DRIFTED from, which were available, which the question named but nothing governs."""
    used, drifted, available, proposed = [], [], [], []
    for e in lineage:
        rel, ref, detail = e.get("relation"), (e.get("ref") or ""), e.get("detail")
        name = ref.split("metric:", 1)[1] if ref.startswith("metric:") else ref
        if rel == "metric_used":
            used.append(name)
        elif rel == "metric_drift":
            drifted.append({"metric": name, "detail": detail})
        elif rel == "metric_available":
            available.append(name)
        elif rel == "metric_proposed":
            proposed.append({"metric": name, "detail": detail})
    return {"used": used, "drifted": drifted, "available": available, "proposed": proposed}


def build_public_receipt(raw: dict, *, connection: Optional[dict] = None,
                         signed: bool = True,
                         health_caveats: Optional[list] = None) -> Optional[dict]:
    """Project a raw ledger receipt (`{artifact, lineage, job, cost}`) into the public
    contract. Pure — no I/O. Absent fields are honestly null/empty, never fabricated. When
    `signed`, an HMAC `signature` over the canonical body is attached.

    ``health_caveats`` are Wave Q4's data-quality caveats for the tables this answer read.
    They arrive as DATA rather than being fetched here, because this function's purity is
    a contract other callers rely on — reading the quality store from inside it would make
    a documented pure projection do I/O, and the caller already has the connection and the
    permission to read. The caller computes them with
    :func:`aughor.quality.caveats.caveats_for_answer`.
    """
    if not raw or not raw.get("artifact"):
        return None
    art = raw["artifact"]
    payload = art.get("payload") if isinstance(art.get("payload"), dict) else {}
    lineage = raw.get("lineage") or []

    executed_sql = [
        {"sql": e.get("detail") or "", "label": f"query {i + 1}",
         "duration_ms": None, "row_count": None}
        for i, e in enumerate(lineage) if e.get("relation") == "source_sql" and e.get("detail")
    ]
    if not executed_sql and payload.get("sql"):
        executed_sql = [{"sql": payload["sql"], "label": "query 1",
                         "duration_ms": None, "row_count": None}]

    input_tables = [
        (e.get("ref") or "").split("table:", 1)[1]
        for e in lineage if e.get("relation") == "input" and (e.get("ref") or "").startswith("table:")
    ] or list(payload.get("tables") or [])

    guards = _guards_from_lineage(lineage)
    # Caveats: any explicit caveat stored on the answer, every FLAGGED guard's note, and
    # Wave Q4's data-quality caveats for the tables read.
    #
    # Assembled through `quality.caveats.assemble` rather than a local de-dup, because Q4's
    # rule is ONE caveat path: O6's declaration violations, trust_checks' result critiques,
    # the guard notes here and the health results all describe concerns to the same reader,
    # and a concern rendered twice in different words is one people stop reading. Two
    # de-dup implementations would be the first step back to that.
    guard_caveats = [g["caveat"] for g in guards
                     if g["action"] == "flagged" and g["caveat"]]
    from aughor.quality.caveats import assemble

    caveats = assemble(
        declaration_caveats=list(payload.get("caveats") or []) + guard_caveats,
        trust_caveats=list(health_caveats or []))

    conf = payload.get("confidence")
    confidence = {"level": (conf if isinstance(conf, str) else payload.get("confidence_level")),
                  "capped_by": payload.get("confidence_capped_by")}
    data_trust = {"window": payload.get("data_window"),
                  "coverage_notes": payload.get("coverage_notes")}
    model = payload.get("model") or {"role": "coder", "id": None}

    receipt = {
        "receipt_version": PUBLIC_RECEIPT_VERSION,
        "id": art.get("id"),
        "created_at": art.get("created_at"),
        "mode": _mode(art.get("kind")),
        "question": payload.get("question") or "",
        "headline": payload.get("headline") or "",
        "connection": connection or {"id": art.get("conn_id"), "name": None, "dialect": None},
        "executed_sql": executed_sql,
        "input_tables": input_tables,
        "guards": guards,
        "caveats": caveats,
        "metrics": _metrics_from_lineage(lineage),
        "confidence": confidence,
        "data_trust": data_trust,
        "model": model,
        # Wave H2: the user-defined persona this answer ran as, or null when it ran unbound.
        # Null is the honest answer for an anonymous ask — the alternative, an empty agent
        # object, would render as a nameless agent on every receipt ever issued.
        "agent": payload.get("agent") or None,
        "cost": raw.get("cost"),
    }
    if signed:
        receipt["signature"] = sign(receipt)
    return receipt
