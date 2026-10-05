"""Earned authority for declared actions (the 2027 study §M; phase 4, P4-1 to P4-3).

The substrate stays thin — an action is a reference to something that already exists, wrapped in
a declaration (§4.2's law) — and what this module adds is the RECORD around it:

- **Every execution is a ledger entry** (kind ``action``): who ran it, under which approval (a
  person's accept, a standing grant cited by id, or the gate's own verdict), what it returned, and
  what the VERIFICATION read found. The verification is the statement the declaration names
  (`ontology/models.Verification`), run through the ordinary query door after dispatch; a read that
  cannot run is ``unavailable``, never ``failed`` — the tie-out's own rule.
- **Authority is a level per (action kind, scope)**, L0–L5, computed from that record and never
  from a setting: L1 declared · L2 complete (verification and undo declared) · L3 execute with
  approval (the gate's default) · L4 execute within policy, granted ONLY on a graduation receipt ·
  L5 autonomous, unreachable until missions exist (phase 5). An irreversible action never passes
  L3. ``authority = min(the ceiling a person set, what the record earned)``.
- **A graduation is a receipt** (kind ``authority_graduation``): at least :data:`GRADUATION_N`
  approved executions whose verification passed, no failed verification, and at least one outcome
  inside expectation on a decision that ran this action — phase 3's exit is the condition §4.8's
  amendment set, and it holds by construction: with no outcome recorded nothing graduates.
- **Demotion is automatic and a ledger entry** (kind ``authority_demotion``): a failed verification
  demotes the (action, scope) and WITHDRAWS its standing grants; the level stands at L3 until a
  person books a new graduation on a recovered record. Nobody has to notice for it to happen; the
  entry is what they notice.

The earned ladder in `memory/trust.py` (L0–L3 by a connection's clean runs) and the standing
grants in `actions/grants.py` had never met; this is where they meet, keyed by action and scope
and fed by verified executions and outcomes.
"""
from __future__ import annotations

import datetime as _dt
import uuid
from typing import Optional

ACTION_KIND = "action"
GRADUATION_KIND = "authority_graduation"
DEMOTION_KIND = "authority_demotion"

LEVELS: dict[int, str] = {0: "observe", 1: "recommend", 2: "prepare", 3: "execute with approval",
                          4: "execute within policy", 5: "autonomous"}
#: Approved executions whose verification passed before a (action, scope) may graduate to L4.
GRADUATION_N = 5
#: Verified executions at L4 before L5 could be considered — and missions (phase 5) must exist.
L5_N = 20


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ── the declaration ────────────────────────────────────────────────────────────────────────

def declaration_problem(action) -> str:
    """Why a declaration is incomplete, or "". A side-effect action needs a verification statement,
    and an undo unless it is declared irreversible by name; an ``annotate`` writes the platform's own
    overlay, which is withdrawable (its undo is built in), and a ``query`` changes nothing."""
    if getattr(action, "kind", "") != "side_effect":
        return ""
    verification = getattr(action, "verification", None)
    if verification is None or not str(getattr(verification, "sql", "") or "").strip():
        return ("a side-effect action is declared with a verification statement — the read that proves "
                "the change took effect; without one it cannot be declared")
    if getattr(action, "reversibility", "") == "irreversible":
        return ""
    undo = getattr(action, "undo", None)
    if undo is None or not str(getattr(undo, "action_id", "") or "").strip():
        return ("a side-effect action is declared with an undo — the compensating action and its window — "
                "or declared irreversible by name (reversibility: irreversible), which caps it at L3")
    return ""


def is_complete(action) -> bool:
    return declaration_problem(action) == ""


# ── the verification read ──────────────────────────────────────────────────────────────────

def verify(action, params: dict, scope: str, *, run_sql=None) -> dict:
    """Run the declared verification read and say what it found: ``passed`` · ``failed`` ·
    ``unavailable`` (the read could not run — recorded, not a failed change) · ``not_declared``."""
    verification = getattr(action, "verification", None)
    if verification is None or not str(getattr(verification, "sql", "") or "").strip():
        return {"status": "not_declared", "why": "the action declares no verification statement"}
    from aughor.actions.executor import _fill
    try:
        sql = _fill(verification.sql, params)
    except Exception as exc:  # noqa: BLE001 — a template that cannot fill is the declaration's fault, said
        return {"status": "unavailable", "why": f"the verification statement could not be filled: {str(exc)[:160]}"}
    try:
        if run_sql is None:
            from aughor.db.measure import run_sql_for
            run_sql = run_sql_for(scope, internal=True, label="action_verification")
        columns, rows, error = run_sql(sql)
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "sql": sql, "why": f"the verification read could not run: {str(exc)[:160]}"}
    if error:
        return {"status": "unavailable", "sql": sql, "why": f"the verification read failed: {str(error)[:160]}"}
    n = len(rows or [])
    expects = getattr(verification, "expects", "rows")
    if expects == "rows":
        ok, why = n > 0, (f"{n} row{'s' if n != 1 else ''} returned" if n else "no row returned — the change is not visible")
    elif expects == "no_rows":
        ok, why = n == 0, ("no row returned, as expected" if n == 0 else f"{n} row{'s' if n != 1 else ''} still returned")
    else:
        first = str(rows[0][0]) if rows and rows[0] else ""
        ok, why = first == str(verification.value), (f"read {first!r}" + ("" if ok else f", expected {verification.value!r}"))
    return {"status": "passed" if ok else "failed", "sql": sql, "rows": n, "why": why}


# ── the Action ledger entry ────────────────────────────────────────────────────────────────

def book_action(*, action, params: dict, scope: str, actor: str, status: str, outcome: Optional[dict],
                grant_id: str = "", approved_by: str = "", verification: Optional[dict] = None,
                decision_id: str = "", compensates: str = "") -> str:
    """One execution as a kernel artifact: what ran, under what, what it returned, what the
    verification found. ``compensates`` (the close-out, C5) names the Action entry this execution
    is the declared UNDO of. Returns the entry id."""
    under = (f"grant:{grant_id}" if grant_id else approved_by or "gate")
    payload = {"action_id": action.id, "kind": getattr(action, "kind", ""), "scope": scope, "actor": actor or "",
               "status": status, "params": {k: str(v) for k, v in (params or {}).items()},
               "outcome": dict(outcome or {}) if isinstance(outcome, dict) else {},
               "under": under, "grant_id": grant_id or "", "approved_by": approved_by or "",
               "verification": dict(verification or {"status": "not_declared"}),
               "reversibility": getattr(action, "reversibility", "") or "",
               "undo": (action.undo.model_dump() if getattr(action, "undo", None) is not None else None),
               "decision": decision_id, "at": _now(), **({"compensates": compensates} if compensates else {})}
    edges = [("verification", payload["verification"].get("status", ""), (payload["verification"].get("why") or "")[:400])]
    if grant_id:
        edges.append(("under_grant", grant_id, "the standing grant that allowed it"))
    if decision_id:
        edges.append(("under_decision", decision_id, ""))
    if compensates:
        edges.append(("compensates", compensates, "the declared undo of this execution"))
    return _ledger().artifact_write(ACTION_KIND, f"action:{scope}:{action.id}:{uuid.uuid4().hex[:12]}", payload,
                                    conn_id=scope or None, lineage=edges)


# ── the gateway writes (the close-out, C5) ─────────────────────────────────────────────────

def book_write(*, door: str, action_id: str, scope: str, actor: str, status: str, params: Optional[dict],
               outcome: Optional[dict], under: str, message: str = "") -> str:
    """A write the integration gateway or the MCP call door performed, booked beside the declared
    actions' entries (§M's architecture: the two stay the one write path, so what passes them is
    on the same record). ``door`` is ``integration`` or ``mcp``; ``action_id`` names the operation
    (``integration.<provider>.<operation>``, ``mcp.<server>.<tool>``); ``scope`` is the grant or the
    server — these writes know no warehouse connection, so they ride with no ``conn_id`` and are
    said as such. A gateway write declares no verification read and no undo, and the entry says so
    rather than leaving the fields to read as passed."""
    payload = {"action_id": action_id, "kind": "write", "door": door, "scope": scope, "actor": actor or "",
               "status": status, "params": {k: str(v)[:200] for k, v in (params or {}).items()},
               "outcome": dict(outcome or {}) if isinstance(outcome, dict) else {},
               "under": under, "grant_id": "", "approved_by": "", "message": (message or "")[:400],
               "verification": {"status": "not_declared", "why": f"a write through the {door} door declares no verification read"},
               "reversibility": "undeclared", "undo": None, "decision": "", "at": _now()}
    return _ledger().artifact_write(ACTION_KIND, f"action:{scope}:{action_id}:{uuid.uuid4().hex[:12]}", payload,
                                    conn_id=None, lineage=[("through", door, under)])


def writes(*, door: str = "", limit: int = 200) -> list[dict]:
    """The gateway writes on the record, newest first — every write the integration gateway and
    the MCP door performed, with its status, beside the declared actions' entries."""
    out = []
    for art in _ledger().artifacts_of_kind(ACTION_KIND, limit=limit * 4):
        p = dict(art.get("payload") or {})
        if p.get("kind") != "write" or (door and p.get("door") != door):
            continue
        p["id"], p["recorded_at"] = str(art.get("id") or ""), str(art.get("created_at") or "")
        out.append(p)
        if len(out) >= limit:
            break
    return out


# ── the undo, fired (the close-out, C5) ────────────────────────────────────────────────────

def undo_window(payload: dict, *, now: Optional[_dt.datetime] = None) -> dict:
    """Whether an execution's declared undo window is still open: ``{open, why, closes_at}``.
    ``window_hours`` 0 is no limit."""
    undo = payload.get("undo") or {}
    if not undo:
        return {"open": False, "why": "the action declared no undo", "closes_at": ""}
    hours = float(undo.get("window_hours") or 0)
    if hours <= 0:
        return {"open": True, "why": "the undo window has no limit", "closes_at": ""}
    try:
        at = _dt.datetime.fromisoformat(str(payload.get("at") or ""))
    except ValueError:
        return {"open": False, "why": "the execution's time is not recorded; the window cannot be read", "closes_at": ""}
    closes = at + _dt.timedelta(hours=hours)
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if now <= closes:
        return {"open": True, "why": f"open until {closes.isoformat()}", "closes_at": closes.isoformat()}
    return {"open": False, "why": f"the {hours:g}-hour undo window closed at {closes.isoformat()}", "closes_at": closes.isoformat()}


def undo(entry_id: str, *, by: str, actions: dict, scope: str, schema_name: str = "", dispatch=None,
         approved: bool = True, now: Optional[_dt.datetime] = None) -> dict:
    """FIRE the declared compensating action of one execution (§M: "the undo is a declared
    compensating action with a window"). Until the close-out the undo was declared and copied onto
    every Action entry and nothing read it back; this runs it: the undo action is loaded by the name
    the declaration gave, its parameters filled from the execution's by the declared templates, and
    it goes through the SAME governed pipeline as any execution (the executor's: criteria,
    approval, dispatch, verification, its own Action entry — naming the entry it compensates). The
    original entry is restated with ``undone_by``; a compensating action that could not run or whose
    verification failed DEMOTES the original (action, scope), as a failed verification does — an undo
    that does not work is the reversibility declaration found false. Refused, with why, when the
    entry is not an execution, is already undone, declared no undo, the window closed, or the undo
    names an action this connection does not declare. Returns the verdict; never raises for a
    refusal."""
    art = _ledger().artifact_by_id(entry_id)
    if not art or art.get("kind") != ACTION_KIND:
        return {"undone": False, "status": "refused", "why": f"no action entry {entry_id!r}", "entry": entry_id}
    # the entry's CURRENT version: an undo restates the entry under its key, and the id names the first
    current = _ledger().artifact_latest(str(art.get("natural_key") or "")) or art
    p = dict(current.get("payload") or {})
    if scope and p.get("scope") != scope:
        return {"undone": False, "status": "refused", "why": "the entry belongs to another scope", "entry": entry_id}
    if p.get("status") != "executed":
        return {"undone": False, "status": "refused", "why": f"only an executed action is undone; this entry is {p.get('status')!r}",
                "entry": entry_id}
    if p.get("undone_by"):
        return {"undone": False, "status": "refused", "why": f"already undone by {p['undone_by']}", "entry": entry_id,
                "undo_entry": p["undone_by"]}
    window = undo_window(p, now=now)
    if not window["open"]:
        return {"undone": False, "status": "refused", "why": window["why"], "entry": entry_id, "window": window}
    undo_decl = p.get("undo") or {}
    undo_action = (actions or {}).get(str(undo_decl.get("action_id") or ""))
    if undo_action is None:
        return {"undone": False, "status": "refused", "entry": entry_id, "window": window,
                "why": f"the undo names {undo_decl.get('action_id')!r}, which this connection does not declare"}
    from aughor.actions.executor import _fill, execute_kinetic_action
    try:
        filled = _fill(dict(undo_decl.get("params") or {}), dict(p.get("params") or {}))
    except Exception as exc:  # noqa: BLE001 — a template over undeclared parameters is the declaration's fault, said
        filled, fill_error = {}, str(exc)[:200]
    else:
        fill_error = ""
    if fill_error:
        result_status, verification, undo_entry, message = "invalid_params", {}, "", fill_error
    else:
        result = execute_kinetic_action(undo_action, filled, actor=by or "", scope=scope, dispatch=dispatch, approved=approved,
                                        schema_name=schema_name, compensates=entry_id)
        result_status, verification, undo_entry, message = result.status, dict(result.verification or {}), result.action_entry, result.message
    undone = result_status == "executed" and verification.get("status") != "failed"
    # the original entry says what became of it
    new = {**p, "undone_by": undo_entry or f"attempt:{result_status}", "undone_at": _now(), "undone_status": result_status,
           "undo_verification": verification, "undo_by": by or "unidentified", "undone": undone}
    restated = _ledger().artifact_write(ACTION_KIND, str(art.get("natural_key") or ""), new, conn_id=scope or None,
                                        lineage=[("undone_by", undo_entry or result_status, (message or "")[:300])])
    if not undone:
        why = (f"the declared undo {undo_decl.get('action_id')!r} did not undo it: {result_status}"
               + (f" — {message}" if message else "")
               + (f"; its verification {verification.get('status')}: {verification.get('why', '')}" if verification else ""))
        demote(str(p.get("action_id") or ""), scope, why=why, by=by or "system",
               evidence={"action_entry": entry_id, "undo_entry": undo_entry, "undo_status": result_status, "verification": verification})
    _ledger().emit("action.undone", {"action_id": p.get("action_id"), "scope": scope, "entry": entry_id, "undo_entry": undo_entry,
                                     "status": result_status, "undone": undone, "by": by or "unidentified"}, conn_id=scope or None)
    return {"undone": undone, "status": result_status, "entry": entry_id, "restated": restated, "undo_entry": undo_entry,
            "undo_action": undo_decl.get("action_id"), "params": filled, "verification": verification, "window": window,
            "message": message, **({"demoted": True} if not undone else {})}


def executions(action_id: str, scope: str, *, limit: int = 500) -> list[dict]:
    out = []
    for art in _ledger().artifacts_of_kind(ACTION_KIND, conn_id=scope or None, limit=limit * 4):
        p = dict(art.get("payload") or {})
        if p.get("action_id") == action_id and p.get("scope") == scope:
            p["id"], p["recorded_at"] = str(art.get("id") or ""), str(art.get("created_at") or "")
            out.append(p)
            if len(out) >= limit:
                break
    return out


def _outcomes_inside(action_id: str, scope: str) -> tuple[int, int]:
    """``(decisions that ran this action and carry an outcome, of them inside expectation)``."""
    from aughor.record import decisions as D
    n = inside = 0
    for d in D.list_decisions(conn_id=scope or None, limit=2000):
        if action_id not in (d.actions or []) or not d.outcome:
            continue
        o = D.outcome_by_id(d.outcome)
        if o is None:
            continue
        n += 1
        inside += o.against_expectation == "inside"
    return n, inside


def record(action_id: str, scope: str) -> dict:
    """The counts the ladder is computed from — a record, not an opinion."""
    runs = executions(action_id, scope)
    executed = [r for r in runs if r.get("status") == "executed"]
    v = [str((r.get("verification") or {}).get("status") or "not_declared") for r in executed]
    with_outcome, inside = _outcomes_inside(action_id, scope)
    return {"executions": len(executed), "verified": v.count("passed"), "failed_verifications": v.count("failed"),
            "unverified": v.count("unavailable") + v.count("not_declared"),
            "approved_by_person": sum(1 for r in executed if r.get("approved_by") and not r.get("grant_id")),
            "under_grant": sum(1 for r in executed if r.get("grant_id")),
            "undone": sum(1 for r in executed if r.get("undone")),
            "decisions_with_outcome": with_outcome, "outcomes_inside_expectation": inside,
            "last_run": executed[0].get("at") if executed else ""}


# ── receipts: graduation and demotion ──────────────────────────────────────────────────────

def _latest(kind: str, action_id: str, scope: str) -> Optional[dict]:
    for art in _ledger().artifacts_of_kind(kind, conn_id=scope or None, limit=2000):
        p = dict(art.get("payload") or {})
        if p.get("action_id") == action_id and p.get("scope") == scope:
            p["id"], p["recorded_at"] = str(art.get("id") or ""), str(art.get("created_at") or "")
            return p
    return None


def evaluate_graduation(action, scope: str) -> dict:
    """Whether (action, scope) has EARNED L4, with every blocker named — "the suite passes" is never
    confused with "it has earned it" (`evals/promotion.py`'s own shape)."""
    rec = record(action.id, scope)
    reasons: list[str] = []
    incomplete = declaration_problem(action)
    if incomplete:
        reasons.append(f"incomplete declaration: {incomplete}")
    if getattr(action, "reversibility", "") == "irreversible":
        reasons.append("an irreversible action never passes L3")
    if rec["verified"] < GRADUATION_N:
        reasons.append(f"{rec['verified']} of {GRADUATION_N} approved executions with a passed verification")
    if rec["failed_verifications"]:
        reasons.append(f"{rec['failed_verifications']} failed verification{'s' if rec['failed_verifications'] != 1 else ''} on the record")
    if rec["outcomes_inside_expectation"] < 1:
        reasons.append("no outcome inside expectation on a decision that ran this action — phase 3's exit, "
                       "the condition §4.8's amendment set")
    return {"action_id": action.id, "scope": scope, "can_graduate": not reasons, "reasons": reasons, "record": rec,
            "bar": {"verified": GRADUATION_N, "failed_verifications": 0, "outcomes_inside_expectation": 1}}


def graduate(action, scope: str, *, by: str) -> dict:
    """Book the graduation receipt for (action, scope) — or refuse with the blockers. A person books
    it; the record decides."""
    decision = evaluate_graduation(action, scope)
    if not decision["can_graduate"]:
        raise ValueError("not earned: " + "; ".join(decision["reasons"]))
    payload = {**decision, "by": by or "unidentified", "level": 4, "at": _now()}
    rid = _ledger().artifact_write(GRADUATION_KIND, f"graduation:{scope}:{action.id}:{uuid.uuid4().hex[:8]}", payload,
                                   conn_id=scope or None, lineage=[("graduates", action.id, "L3 → L4")])
    _ledger().emit("authority.graduated", {"action_id": action.id, "scope": scope, "receipt": rid, "by": by},
                   conn_id=scope or None)
    return {**payload, "id": rid}


def demote(action_id: str, scope: str, *, why: str, by: str = "system", evidence: Optional[dict] = None) -> str:
    """Take authority away — automatically, as a ledger entry — and WITHDRAW the standing grants of
    (action, scope). Returns the demotion entry's id."""
    from aughor.actions import grants
    revoked = grants.revoke_for_action(action_id, scope)
    payload = {"action_id": action_id, "scope": scope, "why": (why or "")[:1000], "by": by or "system",
               "grants_revoked": revoked, "evidence": dict(evidence or {}), "to_level": 3, "at": _now()}
    did = _ledger().artifact_write(DEMOTION_KIND, f"demotion:{scope}:{action_id}:{uuid.uuid4().hex[:8]}", payload,
                                   conn_id=scope or None, lineage=[("demotes", action_id, "→ L3")])
    _ledger().emit("authority.demoted", {"action_id": action_id, "scope": scope, "why": why[:300],
                                         "grants_revoked": revoked, "entry": did}, conn_id=scope or None)
    return did


# ── the level ──────────────────────────────────────────────────────────────────────────────

def level_for(action, scope: str, *, ceiling: Optional[int] = None) -> dict:
    """The L0–L5 of (action, scope): the lower of the ceiling a person set and what the record
    earned, with the reason, the receipt that granted it and the demotion that took it, if any."""
    from aughor.govern.actions import approval_enabled
    rec = record(action.id, scope)
    graduation = _latest(GRADUATION_KIND, action.id, scope)
    demotion = _latest(DEMOTION_KIND, action.id, scope)
    irreversible = getattr(action, "reversibility", "") == "irreversible"
    incomplete = declaration_problem(action)
    if incomplete:
        earned, why = 1, f"declared; {incomplete}"
    elif graduation and not (demotion and demotion["recorded_at"] > graduation["recorded_at"]):
        earned, why = 4, f"graduated on receipt {graduation['id']} ({graduation['record']['verified']} verified executions)"
    elif approval_enabled():
        earned, why = 3, "declared with verification and undo; executes with a person's approval"
    else:
        earned, why = 3, ("declared with verification and undo; the approval gate is OFF (kill switch) so executions "
                          "run unapproved — the operator's doing, not the ladder's")
    if demotion and (not graduation or demotion["recorded_at"] > graduation["recorded_at"]):
        why += f"; demoted on {demotion['recorded_at'][:10]}: {demotion['why'][:160]}"
    hard_ceiling = 3 if irreversible else 4
    notes = []
    if ceiling is None:
        # Phase 5: the ceiling a person set in an active mission on this scope — "the ceiling a person set".
        try:
            from aughor.record.mission import ceiling_for
            ceiling = ceiling_for(action.id, scope)
        except Exception as exc:  # noqa: BLE001 — an unreadable mission ledger leaves the ladder to the record, said
            from aughor.kernel.errors import tolerate
            tolerate(exc, "the missions' authority ceiling could not be read", counter="authority.ceiling", conn_id=scope or None)
            notes.append("the missions' ceiling could not be read; the level is the record's alone")
            ceiling = None
        else:
            if ceiling is not None:
                notes.append(f"an active mission on this scope caps it at L{int(ceiling)}")
    level = min(earned, hard_ceiling, ceiling if ceiling is not None else 5)
    if irreversible:
        notes.append("irreversible: never above L3")
    notes.append("L5 is granted by no code path: missions exist (phase 5), the agent that chooses among declared "
                 "actions toward one does not")
    return {"action_id": action.id, "scope": scope, "level": level, "label": LEVELS[level], "earned": earned,
            "ceiling": min(hard_ceiling, ceiling if ceiling is not None else 5), "why": why, "notes": notes,
            "record": rec, "graduation": graduation["id"] if graduation else "", "demotion": demotion["id"] if demotion else ""}


def table(actions: list, scope: str) -> list[dict]:
    """The authority table for a connection's declared actions — the Action centre's rows."""
    rows = []
    for a in actions:
        row = level_for(a, scope)
        row["graduation_check"] = evaluate_graduation(a, scope)["reasons"]
        row["reversibility"] = getattr(a, "reversibility", "") or "undeclared"
        row["verification_declared"] = getattr(a, "verification", None) is not None
        row["undo_declared"] = getattr(a, "undo", None) is not None
        rows.append(row)
    return rows


def widen(action, scope: str, *, target_value: str, by: str, expires_days: int = 30, max_uses: int = 0):
    """Mint a POLICY grant — bound to a target, a scope, a use cap and an expiry — for an action at L4,
    citing its graduation receipt. Refused below L4: widening is itself a receipted graduation."""
    from aughor.actions import grants
    lv = level_for(action, scope)
    if lv["level"] < 4:
        raise ValueError(f"{action.id} on {scope} is at L{lv['level']} ({lv['label']}); a policy grant needs L4 — {lv['why']}")
    arg = grants.single_target_arg(action)
    if arg is None:
        raise ValueError("a policy grant binds one declared target parameter; this action declares none or several")
    expires = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=int(expires_days))).isoformat() if expires_days else None
    return grants.mint_grant(grants.StandingGrant(
        connection_id=scope, action_id=action.id, target_arg=arg, target_value=str(target_value),
        owner_kind="authority", owner_id=lv["graduation"], created_by=by, graduation_receipt=lv["graduation"],
        expires_at=expires, max_uses=int(max_uses or 0)))
