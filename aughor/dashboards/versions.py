"""A dashboard's spec, kept as versions (Arc CT, CT-3; the home moved to a person in CT-7).

**No new store.** The Ledger already keeps versioned artifacts — ``artifact_write`` writes the
next version for a natural key and stamps ``superseded_by`` on the one before, with lineage
and a tenant — and BR-6 keeps every Briefing that way. A dashboard's spec is the same shape, so
it is an artifact of kind ``cockpit``, one natural key per person's dashboard
(``aughor/dashboards/home.py``). A person's dashboards are the current artifacts under their prefix.

**Keeping is an act of approval, and it can be refused.** That is the difference from a
Briefing's history, which is written in passing and must never break the page it records.
Here a person approved something, so every outcome is SAID: ``kept``, ``unchanged``,
``refused`` (the validator's sentences), ``not_checked`` (the validator could not run — and
then nothing is kept), or ``failed`` (the write itself went wrong).

**Provenance is required.** A spec is kept with the name of the person who approved it and
where it came from. Without both it is refused.

**Supersede, never delete.** An edit is the next version. Going back is the next version too:
``restore`` keeps an earlier spec again, checked against the cards as they are today. Retiring
a dashboard is a version that says so, and its history stays readable.

**A version is a change of the spec**, not an act of approving: approving the same spec twice
writes nothing, by the same reasoning that keeps a Briefing from versioning on every visit.

A dashboard that lived in a Data Canvas before the home moved is read here by its old key, and
retired when it moves (``canvas_*``); nothing new is kept under a canvas.

**An App publishes one version** (Arc ED, ED-4, behind ``dashboard.app_versions``; the user, 2026-10-24: readers see
the last published version). Each version then says where it stands on the platform's one publication axis
(``kernel/lifecycle.py``): a keep is a *draft*, a publish *published*, an unpublish or a retire *archived*. Who a
dashboard reaches is still its newest version's audience — an edit carries it, an unpublish clears it at once — but
what its readers read is the version last published, until the owner publishes again. Off: every version reaches the
audience the moment it is kept, as before, and nothing new is written.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from aughor.dashboards import validate as _validate
from aughor.dashboards.home import Home, prefix
from aughor.kernel import lifecycle
from aughor.kernel.errors import tolerate

#: Arc ED, ED-4 — a keep is a draft; an App's readers read the version last published.
APP_VERSIONS = "dashboard.app_versions"

#: The artifact kind, for a person's dashboard and a canvas's alike.
KIND = "cockpit"

KEPT = "kept"
UNCHANGED = "unchanged"
REFUSED = "refused"
NOT_CHECKED = "not_checked"
FAILED = "failed"


@dataclass(frozen=True)
class Kept:
    """What happened when a spec was offered for keeping. ``kept`` is True only when a new
    version was written."""
    status: str
    version: Optional[int] = None
    artifact_id: str = ""
    sentences: tuple[str, ...] = ()

    @property
    def kept(self) -> bool:
        return self.status == KEPT

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "kept": self.kept, "version": self.version,
                "artifact_id": self.artifact_id, "sentences": list(self.sentences)}


def app_versions() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(APP_VERSIONS)


def publication_of(payload: dict) -> lifecycle.PublicationState:
    """Where a version stands on the publication axis. A version kept before an App had versions of its own records
    no state; its audience read it the moment it was kept, so it projects as published when it reached anyone — what
    they read then is what they keep reading when App versions are switched on."""
    recorded = lifecycle.state_of(payload)
    if recorded:
        return recorded
    if payload.get("retired"):
        return "archived"
    return "published" if payload.get("published_to") else "draft"


def _stamped(payload: dict, state: lifecycle.PublicationState, by: str) -> dict:
    """The payload with its publication state, when App versions are on; without one when they are off — a stamp
    copied forward from a version kept while they were on would say a state the version does not have."""
    out = {k: v for k, v in payload.items() if k != "_lifecycle"}
    if app_versions():
        from aughor.util.time import now_iso_z
        out["_lifecycle"] = lifecycle.stamp(state, by=by.strip(),
                                            published_at=now_iso_z() if state == "published" else "")
    return out


def nothing_to_publish(published_to: Any, state: str, targets: list) -> bool:
    """Whether publishing to ``targets`` would change nothing a reader reads: the same audience as now and — with App
    versions on — nothing kept since the version they read."""
    same = list(targets) == list(published_to or [])
    if not same or not targets or not app_versions():
        return same
    return state == "published"


def canvas_key(canvas_id: str) -> str:
    """Where a canvas's dashboard was kept, before the home moved."""
    return f"cockpit:{canvas_id}"


def _canonical(spec: Any) -> str:
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), default=str)


def changes(before: Optional[dict], after: Optional[dict]) -> dict[str, list[str]]:
    """Which elements a version added, removed or changed, by their keys. What a history
    shows beside a version, so a reader need not compare two specs by eye."""
    b = (before or {}).get("elements") or {}
    a = (after or {}).get("elements") or {}
    return {
        "added": sorted(k for k in a if k not in b),
        "removed": sorted(k for k in b if k not in a),
        "changed": sorted(k for k in a if k in b and a[k] != b[k]),
    }


def _mine(row: Optional[dict]) -> Optional[dict]:
    """The row, if it is this tenant's dashboard. The Ledger reads a natural key across
    tenants; a key is not a secret, so the tenant is checked here."""
    from aughor.org.context import current_org_id
    if not row or row.get("kind") != KIND:
        return None
    if (row.get("org_id") or "default") != current_org_id():
        return None
    return row if isinstance(row.get("payload"), dict) else None


def is_mine(row: Optional[dict]) -> bool:
    """Whether a Ledger row is a dashboard version of this tenant's — the read every lister makes."""
    return _mine(row) is not None


def title_of(spec: Any) -> str:
    try:
        return str(spec["elements"][spec["root"]]["props"]["title"])
    except (KeyError, TypeError):
        return ""


def _entry(row: dict, *, with_spec: bool) -> dict[str, Any]:
    p = row["payload"]
    out = {
        "version": row.get("version"),
        "artifact_id": row.get("id") or "",
        "kept_at": row.get("created_at") or "",
        "current": row.get("superseded_by") is None,
        "retired": bool(p.get("retired")),
        "approved_by": p.get("approved_by") or "",
        "source": p.get("source") or "",
        "note": p.get("note") or "",
        "vocabulary_version": p.get("vocabulary_version") or 0,
        "written_by_model": bool(p.get("written_by_model", True)),
        "cards": list(p.get("cards") or []),
        "changes": p.get("changes") or {"added": [], "removed": [], "changed": []},
        # Who this version reaches beyond its owner, and who published it (the canvas, B5).
        "published_to": list(p.get("published_to") or []),
        "published_by": p.get("published_by") or "",
        # Arc OC-4 — the ontology release a version holding pieces was composed against.
        **({"ontology_release": p["ontology_release"]} if p.get("ontology_release") else {}),
        # Arc ED-4 — draft, published or archived: whether this version is one an App's readers read.
        **({"state": publication_of(p)} if app_versions() else {}),
    }
    if with_spec:
        out["spec"] = p.get("spec")
    return out


def _latest_row(key: str) -> Optional[dict]:
    from aughor.kernel.ledger import Ledger
    return _mine(Ledger.default().artifact_latest(key))


def latest(home: Home) -> Optional[dict]:
    """The newest version, with its spec — or None when this person has no such dashboard.
    A retired dashboard is returned, with ``retired`` True and no spec: that it was retired,
    when and by whom is something a reader is owed. With App versions on it also says which
    version the App's readers read (``published_version``), None while it reaches nobody."""
    row = _latest_row(home.key)
    if not row:
        return None
    out = _entry(row, with_spec=True)
    if app_versions():
        reached = not out["retired"] and bool(out["published_to"])
        read = published(home.key) if reached else None
        out["published_version"] = read["version"] if read else None
    return out


def published(key: str) -> Optional[dict]:
    """The version an App's readers read, by the dashboard's natural key (``Home.key``), with its spec: the newest one
    published — or None when none is. Who it reaches is the newest version's audience, which the caller checks first
    (:func:`latest`)."""
    from aughor.kernel.ledger import Ledger
    for row in Ledger.default().artifact_versions(key, limit=1000):
        if _mine(row) and publication_of(row["payload"]) == "published":
            return _entry(row, with_spec=True)
    return None


def _card_titles(specs) -> dict:
    """The title of every card the specs place, by card id — History names a card by what it is called, never its id."""
    from aughor.cards.store import get_card
    ids = {str((el.get("props") or {}).get("card") or "") for spec in specs if isinstance(spec, dict)
           for el in (spec.get("elements") or {}).values() if isinstance(el, dict) and el.get("type") == "Card"}
    out = {}
    for card_id in sorted(i for i in ids if i):
        card = get_card(card_id)
        if card is not None and card.title:
            out[card_id] = card.title
    return out


def history(home: Home, *, limit: int = 50) -> list[dict]:
    """Every version, newest first, without the specs — each saying in words what it changed of the one before it
    (Arc AP-6, `changelog`), read from the two specs the ledger keeps."""
    from aughor.dashboards import changelog
    from aughor.kernel.ledger import Ledger
    rows = [r for r in Ledger.default().artifact_versions(home.key, limit=limit + 1) if _mine(r)]
    titles = _card_titles(r["payload"].get("spec") for r in rows)
    out = []
    for i, row in enumerate(rows[:limit]):
        entry = _entry(row, with_spec=False)
        payload = row["payload"]
        before = rows[i + 1]["payload"] if i + 1 < len(rows) else {}
        if payload.get("retired"):
            entry["said"] = ["Retired the dashboard"]
        elif before.get("retired"):
            entry["said"] = ["Brought the dashboard back"]
        elif before and _canonical(before.get("spec")) == _canonical(payload.get("spec")):
            entry["said"] = []                  # published, unpublished or re-pinned: its source says which
        else:
            entry["said"] = changelog.said(before.get("spec"), payload.get("spec"), titles)
        out.append(entry)
    return out


def version(home: Home, number: int) -> Optional[dict]:
    """One version, with its spec."""
    from aughor.kernel.ledger import Ledger
    for row in Ledger.default().artifact_versions(home.key, limit=1000):
        if row.get("version") == number and _mine(row):
            return _entry(row, with_spec=True)
    return None


def of_person(connection_id: str, owner: str) -> list[dict]:
    """This person's dashboards on this connection, as they stand now — retired ones included,
    and said to be — oldest first, so the strip keeps its order as dashboards are added."""
    from aughor.kernel.ledger import Ledger
    mine = prefix(connection_id, owner)
    rows = [r for r in Ledger.default().artifacts_of_kind(KIND, conn_id=connection_id, limit=1000)
            if str(r.get("natural_key") or "").startswith(mine) and _mine(r)]
    out = []
    for row in rows:
        entry = _entry(row, with_spec=False)
        first = _first_kept(row["natural_key"])
        out.append({"cockpit_id": row["natural_key"][len(mine):],
                    "title": title_of(row["payload"].get("spec")) or row["payload"].get("title") or "",
                    "started_at": first, **entry})
    return sorted(out, key=lambda c: (c["started_at"], c["cockpit_id"]))


def _first_kept(key: str) -> str:
    from aughor.kernel.ledger import Ledger
    rows = Ledger.default().artifact_versions(key, limit=1000)
    return str(rows[-1].get("created_at") or "") if rows else ""


def _provenance_missing(approved_by: str, source: str) -> Optional[Kept]:
    if not (approved_by or "").strip():
        return Kept(REFUSED, sentences=(
            "A dashboard is kept with the name of the person who approved it. None was given.",))
    if not (source or "").strip():
        return Kept(REFUSED, sentences=(
            "A dashboard is kept with where it came from — a proposal, or a person's own hand. "
            "Nothing was given.",))
    return None


def _write(key: str, connection_id: Optional[str], payload: dict, prior: Optional[dict], why: str,
           *, canvas_id: Optional[str] = None, also: Iterable[tuple[str, str, str]] = ()) -> Kept:
    from aughor.kernel.ledger import Ledger
    try:
        art_id = Ledger.default().artifact_write(
            KIND, key, payload, conn_id=connection_id or None, canvas_id=canvas_id,
            lineage=[*([("supersedes", prior["id"], why)] if prior else []), *also] or None)
    except Exception as exc:
        tolerate(exc, f"a dashboard's version ({key}) could not be written; the caller is told it FAILED",
                 counter="cockpit.version.write", conn_id=connection_id or None, canvas_id=canvas_id)
        return Kept(FAILED, sentences=(
            f"The dashboard could not be kept: {type(exc).__name__}: {exc}. Nothing was changed.",))
    return Kept(KEPT, version=int((prior or {}).get("version") or 0) + 1, artifact_id=art_id)


def twin_cards(placed: Iterable[str], before: Iterable[str] = ()) -> list[str]:
    """A sentence for each card this keep places a second time under another id — the same metric or
    the same query (the user, 2026-10-08: the Executive Dashboard showed Revenue and Gross Margin Rate
    twice and the return rate three times). Only copies this keep ADDS are refused: a dashboard kept
    with copies before can still be kept, and is told nothing new."""
    from aughor.dashboards.cards import same_card_key
    from aughor.cards.store import get_card

    def groups(ids: Iterable[str]) -> dict[str, list]:
        out: dict[str, list] = {}
        for card_id in dict.fromkeys(str(i) for i in ids):
            card = get_card(card_id)
            key = same_card_key(card) if card is not None else ""
            if key:
                out.setdefault(key, []).append(card)
        return out

    was = {k: len(v) for k, v in groups(before).items()}
    said = []
    for key, cards in groups(placed).items():
        if len(cards) > 1 and len(cards) > was.get(key, 0):
            title = cards[0].title or cards[0].id
            said.append(f'"{title}" would be on this dashboard {len(cards)} times — cards '
                        f'{", ".join(c.id for c in cards)} measure the same thing. Keep one.')
    return said


def stamp_notes(spec: Any, before: Any, approved_by: str, *, now: Optional[str] = None,
                stamps_are_ours: bool = False) -> Any:
    """A note's author and date are the server's to write (the canvas, 2026-10-08): whatever a
    client sent in their place is replaced. A note whose words are the version before's keeps
    that version's stamps; one that is new, or whose words changed, is stamped with the person
    keeping it, now. ``stamps_are_ours`` is for a restore, whose spec was read back from the
    Ledger with stamps this server wrote: they are carried as they are."""
    if not isinstance(spec, dict) or not isinstance(spec.get("elements"), dict):
        return spec
    from aughor.util.time import now_iso_z
    stamp = now or now_iso_z()
    prior = before.get("elements") if isinstance(before, dict) and isinstance(before.get("elements"), dict) else {}
    out = copy.deepcopy(spec)
    for key, el in out["elements"].items():
        if not isinstance(el, dict) or el.get("type") != "Note" or not isinstance(el.get("props"), dict):
            continue
        props = el["props"]
        was = prior.get(key) if isinstance(prior.get(key), dict) else None
        kept = (was is not None and was.get("type") == "Note" and isinstance(was.get("props"), dict)
                and was["props"].get("text") == props.get("text") and was["props"].get("author"))
        if kept:
            props["author"] = str(was["props"]["author"])
            props["written_at"] = str(was["props"].get("written_at") or stamp)
        elif stamps_are_ours and props.get("author"):
            props["written_at"] = str(props.get("written_at") or stamp)
        else:
            props["author"] = approved_by.strip()
            props["written_at"] = stamp
    return out


def keep(home: Home, spec: Any, *, approved_by: str, source: str, note: str = "",
         also_known: Iterable[str] = (), written_by_model: bool = True,
         came_from: Iterable[tuple[str, str, str]] = (), stamps_are_ours: bool = False,
         repin: bool = False) -> Kept:
    """Keep ``spec`` as this person's dashboard: the next version, or nothing at all.

    ``approved_by`` is the person who approved it; ``source`` is where it came from.
    ``also_known`` names cards the same approval has just created. ``written_by_model`` says
    whose words its titles are; it defaults to True, the strict reading, and is kept with the
    version so that going back to it holds it to the rule it was first held to.
    ``came_from`` is lineage beyond the version before — where a dashboard moved from.
    ``repin`` (Arc OC-4) pins a dashboard holding pieces to the ontology release in force now — a person read what
    changed since the release it was composed against, and keeps it; the spec may be unchanged.
    """
    missing = _provenance_missing(approved_by, source)
    if missing:
        return missing

    prior = _latest_row(home.key)
    before = (prior or {}).get("payload") or {}
    spec = stamp_notes(spec, before.get("spec"), approved_by, stamps_are_ours=stamps_are_ours)

    verdict = _validate.check_spec_for_home(spec, home, also_known=also_known,
                                            model_written=written_by_model)
    if verdict.status == _validate.NOT_CHECKED:
        return Kept(NOT_CHECKED, sentences=verdict.sentences)
    if not verdict.accepted:
        return Kept(REFUSED, sentences=verdict.sentences)

    from aughor.dashboards import images
    not_held = images.not_held(home.connection_id, spec)
    if not_held:
        return Kept(REFUSED, sentences=tuple(not_held))
    from aughor.dashboards import app_pieces, builder, pieces, questions, variables, wiring
    off = builder.refused(spec) + wiring.refused_off(spec) + app_pieces.refused_off(spec) + variables.refused_off(spec) \
        + questions.refused_off(spec)
    if off:
        return Kept(REFUSED, sentences=tuple(off))
    # Arc AP-2 — what each set reads, as the web reads it, once: the pieces that read a set are probed over it
    wired = wiring.read(spec)
    unresolved = pieces.not_resolved(home.connection_id, spec, wiring=wired) \
        + wiring.not_resolved(home.connection_id, spec, wiring=wired) \
        + variables.not_resolved(home.connection_id, spec, wiring=wired) + variables.unheld(spec, verdict.cards) \
        + questions.not_resolved(home.connection_id, spec)
    if unresolved:
        return Kept(REFUSED, sentences=tuple(unresolved))
    copies = twin_cards(verdict.cards, before.get("cards") or [])
    if copies:
        return Kept(REFUSED, sentences=tuple(copies))
    pin = pieces.pin_for(home.connection_id, before, spec, repin=repin)
    if prior and not before.get("retired") and _canonical(before.get("spec")) == _canonical(spec) \
            and pin == str(before.get("ontology_release") or ""):
        return Kept(UNCHANGED, version=prior.get("version"), artifact_id=prior.get("id") or "")

    vocab = _validate.vocabulary() or {}
    payload = {
        "spec": spec, "retired": False,
        "approved_by": approved_by.strip(), "source": source.strip(), "note": note.strip(),
        "vocabulary_version": int(vocab.get("version") or 0),
        "written_by_model": bool(written_by_model),
        "cards": list(verdict.cards),
        "changes": changes(before.get("spec"), spec),
        # An edit does not unpublish: who the dashboard reaches carries to the next version. With App versions on
        # it is a draft, and they read the version last published until it is published.
        "published_to": list(before.get("published_to") or []) if not before.get("retired") else [],
        "published_by": (before.get("published_by") or "") if not before.get("retired") else "",
        **({"ontology_release": pin} if pin else {}),
    }
    payload = _stamped(payload, "draft", approved_by)
    kept = _write(home.key, home.connection_id, payload, prior, "the spec changed", also=came_from)
    if kept.status == KEPT:
        # PENDING 54 — a question taken off stops being asked; one put back (or kept again after a retire) is asked again
        from aughor.dashboards import questions
        questions.follow(None if before.get("retired") else before.get("spec"), spec)
    return kept


def publish(home: Home, to: list[dict], *, approved_by: str) -> Kept:
    """Publish the dashboard as it stands to ``to`` — groups and roles, each ``{"kind", "id", "name"}``
    as :mod:`aughor.dashboards.sharing` resolved them — or, with an empty ``to``, unpublish it.
    Either is a version: the spec is the same, and who it reaches changed."""
    missing = _provenance_missing(approved_by, "published")
    if missing:
        return missing
    prior = _latest_row(home.key)
    if prior is None:
        return Kept(REFUSED, sentences=("There is no such dashboard to publish.",))
    before = prior["payload"]
    if before.get("retired") or not before.get("spec"):
        return Kept(REFUSED, sentences=("A retired dashboard is not published. Bring it back first.",))
    targets = [{"kind": str(t["kind"]), "id": str(t["id"]), "name": str(t.get("name") or t["id"])} for t in to]
    if nothing_to_publish(before.get("published_to"), publication_of(before), targets):
        return Kept(UNCHANGED, version=prior.get("version"), artifact_id=prior.get("id") or "")
    names = ", ".join(t["name"] for t in targets)
    payload = {
        **before,
        "approved_by": approved_by.strip(),
        "source": f"published to {names}" if targets else "unpublished",
        "note": "",
        "changes": {"added": [], "removed": [], "changed": []},
        "published_to": targets,
        "published_by": approved_by.strip() if targets else "",
    }
    # Arc ED-4 — publishing makes the dashboard as it stands what its readers read; unpublishing reaches nobody
    payload = _stamped(payload, "published" if targets else "archived", approved_by)
    return _write(home.key, home.connection_id, payload, prior, "published" if targets else "unpublished")


def restore(home: Home, number: int, *, approved_by: str) -> Kept:
    """Go back to an earlier version by keeping its spec AGAIN, as the newest. It is checked
    against the cards as they are today: a card removed since then makes the restore a
    refusal, which is the honest answer."""
    earlier = version(home, number)
    if earlier is None:
        return Kept(REFUSED, sentences=(f"This dashboard has no version {number}.",))
    if earlier["retired"] or earlier.get("spec") is None:
        return Kept(REFUSED, sentences=(
            f"Version {number} is the one that retired the dashboard; it holds no spec to go back to.",))
    return keep(home, earlier["spec"], approved_by=approved_by,
                source=f"restored from version {number}",
                written_by_model=earlier["written_by_model"], stamps_are_ours=True)


def _retired_payload(before: dict, approved_by: str, note: str) -> dict:
    return _stamped(_retired_fields(before, approved_by, note), "archived", approved_by)


def _retired_fields(before: dict, approved_by: str, note: str) -> dict:
    return {
        "spec": None, "retired": True, "title": title_of(before.get("spec")),
        "approved_by": approved_by.strip(), "source": "retired", "note": note.strip(),
        "vocabulary_version": before.get("vocabulary_version") or 0,
        "written_by_model": False,
        "cards": [],
        "changes": changes(before.get("spec"), None),
        # A retired dashboard reaches nobody.
        "published_to": [],
        "published_by": "",
    }


def retire(home: Home, *, approved_by: str, note: str = "") -> Kept:
    """Retire this dashboard. Written as a version that says so: the history stays, and a later
    ``keep`` or ``restore`` brings it back as the version after it."""
    missing = _provenance_missing(approved_by, "retired")
    if missing:
        return missing
    prior = _latest_row(home.key)
    if prior is None:
        return Kept(REFUSED, sentences=("There is no such dashboard to retire.",))
    before = prior["payload"]
    if before.get("retired"):
        return Kept(UNCHANGED, version=prior.get("version"), artifact_id=prior.get("id") or "")
    kept = _write(home.key, home.connection_id, _retired_payload(before, approved_by, note), prior,
                  "the dashboard was retired")
    if kept.status == KEPT:
        from aughor.dashboards import questions
        questions.follow(before.get("spec"), None)       # a retired dashboard's questions stop being asked
    return kept


# ── a dashboard that lived in a canvas ────────────────────────────────────────────────────────

def canvas_latest(canvas_id: str) -> Optional[dict]:
    """A canvas's dashboard as it was left, with its spec — or None."""
    row = _latest_row(canvas_key(canvas_id))
    return _entry(row, with_spec=True) if row else None


def canvas_dashboards(connection_id: str) -> list[dict]:
    """The canvas dashboards on this connection that still stand — each one waiting to be moved
    to a person's Briefing. A retired one is not listed: it has moved, or was let go."""
    from aughor.kernel.ledger import Ledger
    out = []
    for row in Ledger.default().artifacts_of_kind(KIND, conn_id=connection_id, limit=1000):
        key = str(row.get("natural_key") or "")
        if key.startswith("cockpit:person:") or not _mine(row) or row["payload"].get("retired"):
            continue
        out.append({"canvas_id": row.get("canvas_id") or key[len("cockpit:"):],
                    "title": title_of(row["payload"].get("spec")), **_entry(row, with_spec=False)})
    return out


def retire_canvas(canvas_id: str, *, approved_by: str, note: str) -> Kept:
    """Retire a canvas's dashboard — the last version it will have under the canvas."""
    prior = _latest_row(canvas_key(canvas_id))
    if prior is None:
        return Kept(REFUSED, sentences=("This canvas has no dashboard.",))
    before = prior["payload"]
    if before.get("retired"):
        return Kept(UNCHANGED, version=prior.get("version"), artifact_id=prior.get("id") or "")
    return _write(canvas_key(canvas_id), prior.get("conn_id"), _retired_payload(before, approved_by, note),
                  prior, "the dashboard moved", canvas_id=canvas_id)
