"""DS-19 (§3.7 second movement) — SQL a person authored on a node, made governable.

The user, 2026-09-19, reading the Automations palette: *"Trusted Query … needs to be
generally available for explicity SQL input by the user."* This module is the half that
makes that safe, and the reasoning matters more than the code, because the repo's
`_NO_CODE_LAW` was standing in the way and should not have been.

**Three threats had been collapsed into one sentence, and only two of them are the law's.**
An imported flow file carrying executable behaviour, refused at the border forever. A model
authoring an expression that then runs unattended, refused and HARDENED here. And a person
typing SQL they already own — which is neither, and which `routers/query.py` has always
permitted against these same connections, with a signed provenance receipt. Refusing the
same act on the canvas was never the law; it was an inconsistency the law was being asked
to justify.

**What an unattended run needs that an editor session does not** is three things: it must
really have run before it is armed, a name must be against the content, and an edit must
reopen both. None of that is new — it is the trusted-query lifecycle (`routers/learning.py`),
and this module's whole job is to route authored SQL through it rather than around it.

So: the node takes `question` + `sql`; SAVE verifies it for real and mints the trusted-query
row it names; and the stored step carries a `query_id` like every other. **A saved node
stays a reference to a governed object.** The authored shape exists on the way in and
nowhere at rest — which is why DS-19 cost none of the validator churn its plan predicted.

**Scope is a flag, not a second store** (§6 item 26 (c), the user's call): the minted row
carries `owner_automation`, so it is hidden from the catalogue, the picker and every
prompt, and promotion is that field going empty.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aughor.automations.models import Automation

logger = logging.getLogger(__name__)

#: What `source` the minted row carries, so the catalogue can tell where it came from
#: and a promotion can say so. One string, named here, because a literal spelled at two
#: call sites is how a provenance field starts meaning two things.
SOURCE = "authored_on_node"


class AuthoredSqlRefused(ValueError):
    """Verification said no. Carries the report so the editor can render the reason.

    A ValueError because the save path already turns those into a 422 the form renders —
    the refusal a person can act on must not arrive as a crash (`_save`'s own lesson).
    """

    def __init__(self, message: str, report: dict | None = None) -> None:
        super().__init__(message)
        self.report = report or {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def materialise_authored_sql(automation: "Automation", *, actor: str = "") -> "Automation":
    """Turn every node-authored `sql` on this automation into a governed query it names.

    Returns a COPY with those steps rewritten to `{"query_id": …}`; an automation with no
    authored SQL is returned unchanged, so this is safe to call on every save.

    Raises `AuthoredSqlRefused` when verification fails — **at save, never at 09:00**,
    which is the entire point of doing this here rather than in the dispatcher.
    """
    from aughor.semantic import trusted_verify
    from aughor.semantic.trusted_queries import get_trusted, save_trusted, TrustedQuery

    authored = [(i, e) for i, e in enumerate(automation.effects)
                if e.kind == "trusted_query" and (e.config or {}).get("sql")]
    if not authored:
        return automation

    conn_id = automation.conn_id
    if not conn_id:
        raise AuthoredSqlRefused(
            "This automation has no connection, so there is nothing to verify the SQL "
            "against. Pick a connection first.")

    effects = list(automation.effects)
    for index, effect in authored:
        question = str(effect.config.get("question", "")).strip()
        sql = str(effect.config.get("sql", "")).strip()

        # An EDIT re-uses the row this step already owns rather than minting a second
        # one. Without this, every save of an edited step would leave the previous row
        # orphaned in the store — invisible (it is chain-owned) and never collected.
        existing_id = str(effect.config.get("authored_query_id", "")).strip()
        prior = get_trusted(existing_id) if existing_id else None
        if prior is not None and prior.owner_automation != automation.id:
            # Not ours to rewrite. Mint a fresh one instead of editing another chain's
            # query — a copied step must not reach back into the chain it came from.
            prior = None

        try:
            report = trusted_verify.verify(conn_id, sql)
        except KeyError as exc:
            raise AuthoredSqlRefused(
                f"Connection {conn_id!r} not found, so the SQL could not be verified."
            ) from exc

        if not report.get("passed"):
            blockers = report.get("blockers") or []
            detail = "; ".join(str(b) for b in blockers) or "verification failed"
            raise AuthoredSqlRefused(
                f"This SQL did not verify against {conn_id}: {detail}. "
                f"It is not saved, because a query that has never run is a query that "
                f"fails at its first scheduled tick instead of now.", report)

        row = prior or TrustedQuery(
            id=f"tq_{uuid.uuid4().hex[:12]}", connection_id=conn_id,
            question=question, sql=sql, source=SOURCE)
        row.question, row.sql = question, sql
        row.connection_id = conn_id
        row.owner_automation = automation.id
        row.last_executed_at = _now()
        row.verification = report
        # The lifecycle, unchanged from the door: a verified edit lands `proposed` and
        # the prior approval stamp is cleared, because an approval covers the content it
        # approved and nothing later.
        row.status = "proposed"
        row.proposed_by, row.proposed_at = (actor or "node"), _now()
        row.verified_by = row.verified_at = ""

        # §6 item 26 (b), the user's call — verification is never optional; APPROVAL
        # follows the deployment's identity posture. With identity off there is exactly
        # one principal, so demanding a second click from the only account on the install
        # is theatre, and theatre is how a gate stops being read: the save self-approves
        # and RECORDS that it did, under a name that does not pretend to be a reviewer.
        # With identity on, a second principal approves through the door that already
        # exists, and until they do the step is `proposed` and the dispatcher will not
        # run it — a hold, stated, rather than a silent one.
        from aughor.org.context import current_user_id
        if not current_user_id():
            row.status = "approved"
            row.version += 1
            row.verified_by = f"self:{actor or 'local'}"
            row.verified_at = _now()
        save_trusted(row)

        config = {k: v for k, v in effect.config.items() if k not in ("sql", "question")}
        config["query_id"] = row.id
        # Kept so the NEXT save edits this row instead of orphaning it, and so the editor
        # can tell an authored query from a picked one without asking the store.
        config["authored_query_id"] = row.id
        effects[index] = effect.model_copy(update={"config": config})

    return automation.model_copy(update={"effects": effects})
