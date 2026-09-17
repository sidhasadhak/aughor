"""Install a pack's FUNCTION LAYER — the group it ships, tagged and subscribed (HB-6).

§6 item 24 (c): a function pack ships its group, its tags, its default grants and
subscriptions, and its automations. This module is the one place that act happens, and
three decisions shape it:

**Install is not activation.** `status` governs whether prose may steer a prompt; the
function layer is organisational structure. A draft pack installs (like `pack.bind`,
install is part of the path to a working function), a deprecated one refuses. Everything
install creates is inert by construction — an empty group waiting for members,
subscribe-level grants, and automations that land DISARMED and on probation — so the act
is safe before anyone reviews it, and worth reviewing because it is on the journal.

**Validate everything, then write.** The writes span three stores (rbac groups, metastore
grants, the automations library) with no shared transaction, so a bad entry found halfway
would leave a partial install. Every group id, securable, privilege and automation is
checked first; the first problem refuses the whole install and nothing has been written.

**"Tagged" is spelled as grants by tag.** A group is a principal, not a securable, so it
cannot carry a govern tag. What the layer means by its tags is the pack's `domains`:
install subscribes the group to `domain:<value>` for each one, and `securable_chain`
already walks `domain:x` for anything tagged `domain=x` — the group covers every object
the organisation later tags into its function, which is what makes it self-maintaining
(§6 24 b). Tags themselves stay human-set; install grants reach, it never tags data.
"""
from __future__ import annotations

import logging
from typing import Optional

from aughor.packs.loader import PacksError, load_pack
from aughor.packs.models import Pack, PackFunction
from aughor.packs.roots import pack_dir

logger = logging.getLogger(__name__)

#: A pack automation lands with this lineage, and the map shows it verbatim.
def pack_declarer(pack_id: str) -> str:
    return f"pack:{pack_id}"


def pack_automation_id(pack_id: str, spec_id: str) -> str:
    """Deterministic, so a re-install updates the same row instead of minting a twin."""
    return f"pack-{pack_id}-{spec_id}"


class InstallRefused(Exception):
    """The install was refused whole; nothing was written."""


def function_layer_problems(pack: Pack) -> list[str]:
    """Static problems in a pack's function layer — shared by `validate_pack` (so the
    roster names them) and `install_pack` (so a broken layer refuses before writing)."""
    fn = pack.function
    if fn is None:
        return []
    from aughor.rbac.groups import valid_group_id
    from aughor.rbac.levels import EDIT, MANAGE, OWN, SUBSCRIBE, VIEW
    from aughor.metastore.models import securable_kind

    problems: list[str] = []
    gid = (fn.group.id or pack.id).strip()
    if not valid_group_id(gid):
        problems.append(f"function: group id {gid!r} is not a group slug "
                        "(lowercase, digits, '-'/'_', max 64)")
    ladder = (VIEW, SUBSCRIBE, EDIT, MANAGE, OWN)
    for g in fn.grants:
        if g.privilege not in ladder:
            problems.append(f"function: grant privilege {g.privilege!r} not in {ladder}")
        if not securable_kind(g.securable):
            problems.append(f"function: grant securable {g.securable!r} has no known kind")
    for s in fn.subscriptions:
        if not securable_kind(s):
            problems.append(f"function: subscription {s!r} has no known kind")
    for n, spec in enumerate(fn.automations):
        if not isinstance(spec, dict) or not str(spec.get("id") or "").strip():
            problems.append(f"function: automations[{n}] needs an 'id' "
                            "(re-install updates by id; without one it would mint twins)")
    return problems


def _wanted_grants(pack: Pack, fn: PackFunction, gid: str) -> list[tuple[str, str]]:
    """(securable, privilege) pairs the layer asks for, in install order. The pack's
    domains come first — they are the layer's tags."""
    from aughor.rbac.levels import SUBSCRIBE
    wanted: list[tuple[str, str]] = []
    for d in pack.manifest.domains:
        wanted.append((f"domain:{d}", SUBSCRIBE))
    for s in fn.subscriptions:
        wanted.append((s, SUBSCRIBE))
    for g in fn.grants:
        wanted.append((g.securable, g.privilege))
    # Dedup, first spelling wins — a domain repeated under `subscriptions` is one grant.
    seen: set[tuple[str, str]] = set()
    return [w for w in wanted if not (w in seen or seen.add(w))]


def install_pack(pack_id: str, *, actor: str = "", connection_id: str = "",
                 org_id: Optional[str] = None) -> dict:
    """Install `pack_id`'s function layer for the caller's organisation.

    Idempotent: the group upserts (its operator-attached channel is preserved), grants
    upsert on their unique key, and automations update by their deterministic id — with
    `declared_by` first-writer-wins and `probation` preserved by the store, so a
    graduation earned between installs survives the next one.

    Automations need a connection to run against; with no `connection_id` they are
    reported as waiting, and the rest of the layer still installs.

    Raises `PacksError` (unknown pack) and `InstallRefused` (deprecated pack, no
    function layer, or an invalid entry — refused whole, nothing written).
    """
    root = pack_dir(pack_id)
    if root is None:
        raise PacksError(f"no pack '{pack_id}' in any pack root")
    pack = load_pack(root)

    if pack.manifest.status == "deprecated":
        raise InstallRefused(f"'{pack_id}' is deprecated — a retired pack does not "
                             "install a function")
    fn = pack.function
    if fn is None:
        raise InstallRefused(f"'{pack_id}' ships no function.yaml — nothing to install")

    problems = function_layer_problems(pack)
    if problems:
        raise InstallRefused(f"'{pack_id}' function layer refused: " + "; ".join(problems))

    from aughor.org.context import current_org_id
    oid = org_id or current_org_id()
    gid = (fn.group.id or pack.id).strip()

    # ── validate the automations by CONSTRUCTING them (the plane's own laws) ──────
    from aughor.automations.models import Automation
    from aughor.automations.store import get_automation
    built: list[Automation] = []
    if fn.automations and connection_id:
        for spec in fn.automations:
            auto_id = pack_automation_id(pack.id, str(spec["id"]).strip())
            prev = get_automation(auto_id)
            forced = {
                "id": auto_id,
                "conn_id": connection_id,
                "declared_by": pack_declarer(pack.id),
                # A pack automation never arms itself: declared, on probation, and
                # DISARMED until a person enables it — the same posture as its group,
                # which installs waiting for members. On a RE-install the switch is the
                # operator's, like the group's channel: an arming earned between
                # installs survives the next one (probation/declared_by are preserved
                # one layer down, by the store's upsert).
                "probation": True,
                "enabled": prev.enabled if prev else False,
            }
            try:
                built.append(Automation(**{**spec, **forced}))
            except Exception as exc:
                raise InstallRefused(
                    f"'{pack_id}' automations[{spec.get('id')!r}] failed the save-time "
                    f"validators: {exc}") from exc

    # ── all valid — write ─────────────────────────────────────────────────────────
    from aughor.rbac.groups import get_group, list_members, upsert_group
    existing_group = get_group(oid, gid)
    upsert_group(
        oid, gid,
        name=fn.group.name or pack.manifest.name or gid,
        description=fn.group.description,
        # The channel is operator-attached, never the pack's to set or reset.
        channel_trigger_id=existing_group.channel_trigger_id if existing_group else "",
    )

    from aughor.metastore.store import add_grant, list_grants
    principal = f"group:{gid}"
    already = {(g.securable, g.privilege) for g in list_grants(org_id=oid, principal=principal)}
    grants_report: list[dict] = []
    for securable, privilege in _wanted_grants(pack, fn, gid):
        add_grant(principal, securable, privilege, source=pack_declarer(pack.id), org_id=oid)
        grants_report.append({"securable": securable, "privilege": privilege,
                              "existed": (securable, privilege) in already})

    from aughor.automations.store import upsert_automation
    autos_report: list[dict] = []
    if fn.automations and not connection_id:
        autos_report = [{"id": str(s.get("id") or ""), "state": "waiting",
                         "reason": "automations run against a connection — install "
                                   "with connection_id to land them"}
                        for s in fn.automations]
    for a in built:
        existed = get_automation(a.id) is not None
        saved = upsert_automation(a)
        autos_report.append({"id": saved.id, "state": "updated" if existed else "installed",
                             "enabled": saved.enabled, "probation": saved.probation,
                             "declared_by": saved.declared_by})

    report = {
        "pack_id": pack.id,
        "group": {"id": gid, "name": fn.group.name or pack.manifest.name or gid,
                  "existed": existing_group is not None,
                  "members": len(list_members(oid, gid))},
        "tags": list(pack.manifest.domains),
        "grants": grants_report,
        "automations": autos_report,
        "connection_id": connection_id,
    }
    _journal(report, actor)
    return report


def _journal(report: dict, actor: str) -> None:
    """The record ships with the act (promote.py's law). Best-effort for the same
    reason: the stores are the authority, this is the trail."""
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit("pack.installed", {
            "pack_id": report["pack_id"],
            "group_id": report["group"]["id"],
            "actor": actor,
            "tags": report["tags"],
            "grants": len(report["grants"]),
            "automations": [a["id"] for a in report["automations"] if a.get("state") != "waiting"],
            "connection_id": report["connection_id"],
        })
    except Exception as exc:
        logger.warning("pack %s function layer installed but not journalled: %s",
                       report.get("pack_id"), exc)
