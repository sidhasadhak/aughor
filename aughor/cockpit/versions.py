"""A cockpit's spec, kept as versions (Arc CT, CT-3; the home moved to a person in CT-7).

**No new store.** The Ledger already keeps versioned artifacts — ``artifact_write`` writes the
next version for a natural key and stamps ``superseded_by`` on the one before, with lineage
and a tenant — and BR-6 keeps every Briefing that way. A cockpit's spec is the same shape, so
it is an artifact of kind ``cockpit``, one natural key per person's cockpit
(``aughor/cockpit/home.py``). A person's cockpits are the current artifacts under their prefix.

**Keeping is an act of approval, and it can be refused.** That is the difference from a
Briefing's history, which is written in passing and must never break the page it records.
Here a person approved something, so every outcome is SAID: ``kept``, ``unchanged``,
``refused`` (the validator's sentences), ``not_checked`` (the validator could not run — and
then nothing is kept), or ``failed`` (the write itself went wrong).

**Provenance is required.** A spec is kept with the name of the person who approved it and
where it came from. Without both it is refused.

**Supersede, never delete.** An edit is the next version. Going back is the next version too:
``restore`` keeps an earlier spec again, checked against the cards as they are today. Retiring
a cockpit is a version that says so, and its history stays readable.

**A version is a change of the spec**, not an act of approving: approving the same spec twice
writes nothing, by the same reasoning that keeps a Briefing from versioning on every visit.

A cockpit that lived in a Data Canvas before the home moved is read here by its old key, and
retired when it moves (``canvas_*``); nothing new is kept under a canvas.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from aughor.cockpit import validate as _validate
from aughor.cockpit.home import Home, prefix
from aughor.kernel.errors import tolerate

#: The artifact kind, for a person's cockpit and a canvas's alike.
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


def canvas_key(canvas_id: str) -> str:
    """Where a canvas's cockpit was kept, before the home moved."""
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
    """The row, if it is this tenant's cockpit. The Ledger reads a natural key across
    tenants; a key is not a secret, so the tenant is checked here."""
    from aughor.org.context import current_org_id
    if not row or row.get("kind") != KIND:
        return None
    if (row.get("org_id") or "default") != current_org_id():
        return None
    return row if isinstance(row.get("payload"), dict) else None


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
    }
    if with_spec:
        out["spec"] = p.get("spec")
    return out


def _latest_row(key: str) -> Optional[dict]:
    from aughor.kernel.ledger import Ledger
    return _mine(Ledger.default().artifact_latest(key))


def latest(home: Home) -> Optional[dict]:
    """The newest version, with its spec — or None when this person has no such cockpit.
    A retired cockpit is returned, with ``retired`` True and no spec: that it was retired,
    when and by whom is something a reader is owed."""
    row = _latest_row(home.key)
    return _entry(row, with_spec=True) if row else None


def history(home: Home, *, limit: int = 50) -> list[dict]:
    """Every version, newest first, without the specs."""
    from aughor.kernel.ledger import Ledger
    rows = Ledger.default().artifact_versions(home.key, limit=limit)
    return [_entry(r, with_spec=False) for r in rows if _mine(r)]


def version(home: Home, number: int) -> Optional[dict]:
    """One version, with its spec."""
    from aughor.kernel.ledger import Ledger
    for row in Ledger.default().artifact_versions(home.key, limit=1000):
        if row.get("version") == number and _mine(row):
            return _entry(row, with_spec=True)
    return None


def of_person(connection_id: str, owner: str) -> list[dict]:
    """This person's cockpits on this connection, as they stand now — retired ones included,
    and said to be — oldest first, so the strip keeps its order as cockpits are added."""
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
            "A cockpit is kept with the name of the person who approved it. None was given.",))
    if not (source or "").strip():
        return Kept(REFUSED, sentences=(
            "A cockpit is kept with where it came from — a proposal, or a person's own hand. "
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
        tolerate(exc, f"a cockpit's version ({key}) could not be written; the caller is told it FAILED",
                 counter="cockpit.version.write", conn_id=connection_id or None, canvas_id=canvas_id)
        return Kept(FAILED, sentences=(
            f"The cockpit could not be kept: {type(exc).__name__}: {exc}. Nothing was changed.",))
    return Kept(KEPT, version=int((prior or {}).get("version") or 0) + 1, artifact_id=art_id)


def twin_cards(placed: Iterable[str], before: Iterable[str] = ()) -> list[str]:
    """A sentence for each card this keep places a second time under another id — the same metric or
    the same query (the user, 2026-10-08: the Executive Cockpit showed Revenue and Gross Margin Rate
    twice and the return rate three times). Only copies this keep ADDS are refused: a cockpit kept
    with copies before can still be kept, and is told nothing new."""
    from aughor.cockpit.cards import same_card_key
    from aughor.dashboard.store import get_card

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
            said.append(f'"{title}" would be on this cockpit {len(cards)} times — cards '
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
         came_from: Iterable[tuple[str, str, str]] = (), stamps_are_ours: bool = False) -> Kept:
    """Keep ``spec`` as this person's cockpit: the next version, or nothing at all.

    ``approved_by`` is the person who approved it; ``source`` is where it came from.
    ``also_known`` names cards the same approval has just created. ``written_by_model`` says
    whose words its titles are; it defaults to True, the strict reading, and is kept with the
    version so that going back to it holds it to the rule it was first held to.
    ``came_from`` is lineage beyond the version before — where a cockpit moved from.
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

    from aughor.cockpit import images
    not_held = images.not_held(home.connection_id, spec)
    if not_held:
        return Kept(REFUSED, sentences=tuple(not_held))
    copies = twin_cards(verdict.cards, before.get("cards") or [])
    if copies:
        return Kept(REFUSED, sentences=tuple(copies))
    if prior and not before.get("retired") and _canonical(before.get("spec")) == _canonical(spec):
        return Kept(UNCHANGED, version=prior.get("version"), artifact_id=prior.get("id") or "")

    vocab = _validate.vocabulary() or {}
    payload = {
        "spec": spec, "retired": False,
        "approved_by": approved_by.strip(), "source": source.strip(), "note": note.strip(),
        "vocabulary_version": int(vocab.get("version") or 0),
        "written_by_model": bool(written_by_model),
        "cards": list(verdict.cards),
        "changes": changes(before.get("spec"), spec),
    }
    return _write(home.key, home.connection_id, payload, prior, "the spec changed", also=came_from)


def restore(home: Home, number: int, *, approved_by: str) -> Kept:
    """Go back to an earlier version by keeping its spec AGAIN, as the newest. It is checked
    against the cards as they are today: a card removed since then makes the restore a
    refusal, which is the honest answer."""
    earlier = version(home, number)
    if earlier is None:
        return Kept(REFUSED, sentences=(f"This cockpit has no version {number}.",))
    if earlier["retired"] or earlier.get("spec") is None:
        return Kept(REFUSED, sentences=(
            f"Version {number} is the one that retired the cockpit; it holds no spec to go back to.",))
    return keep(home, earlier["spec"], approved_by=approved_by,
                source=f"restored from version {number}",
                written_by_model=earlier["written_by_model"], stamps_are_ours=True)


def _retired_payload(before: dict, approved_by: str, note: str) -> dict:
    return {
        "spec": None, "retired": True, "title": title_of(before.get("spec")),
        "approved_by": approved_by.strip(), "source": "retired", "note": note.strip(),
        "vocabulary_version": before.get("vocabulary_version") or 0,
        "written_by_model": False,
        "cards": [],
        "changes": changes(before.get("spec"), None),
    }


def retire(home: Home, *, approved_by: str, note: str = "") -> Kept:
    """Retire this cockpit. Written as a version that says so: the history stays, and a later
    ``keep`` or ``restore`` brings it back as the version after it."""
    missing = _provenance_missing(approved_by, "retired")
    if missing:
        return missing
    prior = _latest_row(home.key)
    if prior is None:
        return Kept(REFUSED, sentences=("There is no such cockpit to retire.",))
    before = prior["payload"]
    if before.get("retired"):
        return Kept(UNCHANGED, version=prior.get("version"), artifact_id=prior.get("id") or "")
    return _write(home.key, home.connection_id, _retired_payload(before, approved_by, note), prior,
                  "the cockpit was retired")


# ── a cockpit that lived in a canvas ────────────────────────────────────────────────────────

def canvas_latest(canvas_id: str) -> Optional[dict]:
    """A canvas's cockpit as it was left, with its spec — or None."""
    row = _latest_row(canvas_key(canvas_id))
    return _entry(row, with_spec=True) if row else None


def canvas_cockpits(connection_id: str) -> list[dict]:
    """The canvas cockpits on this connection that still stand — each one waiting to be moved
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
    """Retire a canvas's cockpit — the last version it will have under the canvas."""
    prior = _latest_row(canvas_key(canvas_id))
    if prior is None:
        return Kept(REFUSED, sentences=("This canvas has no cockpit.",))
    before = prior["payload"]
    if before.get("retired"):
        return Kept(UNCHANGED, version=prior.get("version"), artifact_id=prior.get("id") or "")
    return _write(canvas_key(canvas_id), prior.get("conn_id"), _retired_payload(before, approved_by, note),
                  prior, "the cockpit moved", canvas_id=canvas_id)
