"""IP-2 — the industries this deployment chose: one small file every industry read goes through.

The install asks which industries Aughor is for (ROADMAP §3.17 "Chosen at install"; §6 item 21, answers 1
and 2) and writes the answer here, in the state directory:

    data/industries.json   {"industries": ["retail", "saas"], "source": "installer", "updated_at": "…"}

Three writers, one format: `aughor/installer.py` (standard library only, so it mirrors `CHOICE_FILE`, the
path rule and this shape — `tests/unit/test_installer.py` holds the two equal), `aughor industries`, and
Settings → Organization (`PUT /org-settings/industries`).

What the answer means:

- **no file, or `"industries": null`** — every shipped industry package stays available and each
  connection's industry is detected on its own (answer 1: skipping is the default, not a lesser mode).
  A skipped question is written as null so a re-run of the installer does not ask again;
- **a list** narrows what a connection's profile may resolve to: an industry text that names a package
  outside the list resolves to no package, and a read that knows nothing about its connection's industry
  reads the chosen packages and the shared knowledge — never another industry's;
- **an empty list** keeps only the knowledge every industry shares (the functions and the analytics base):
  a business whose industry ships no package yet is not handed a retailer's playbook.

An id no shipped package carries any more is ignored and reported, never guessed at. The file is re-read
when it changes on disk (keyed on its modification time and size), so a choice made in Settings or with
`aughor industries` reaches a running API without a restart.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from aughor.db.paths import state_dir
from aughor.db.sqlite_util import resolve_db_path

#: Overrides where the choice lives. Registered with tests/conftest.py and scripts/dump_openapi.py.
CHOICE_ENV = "AUGHOR_INDUSTRIES_FILE"
#: The file's name inside the state directory — mirrored in aughor/installer.py.
CHOICE_FILE = "industries.json"


@dataclass(frozen=True)
class ShippedIndustry:
    """An industry package this checkout carries, as a person picks it."""
    id: str             # the closed id `industry_scope` returns ("food_delivery")
    name: str           # the package's name ("Food delivery")
    title: str          # its curated industry ("Food Delivery / On-Demand Marketplace")
    description: str


@dataclass(frozen=True)
class IndustryChoice:
    """What the file says. ``industries`` is None for every industry, else the chosen ids (possibly none)."""
    industries: Optional[tuple[str, ...]] = None
    source: str = ""
    updated_at: str = ""
    #: Ids in the file that no shipped package carries — ignored, and named so a person can see why.
    ignored: tuple[str, ...] = ()
    #: Why the file was not read, when it could not be ("" when it was, or when there is none).
    problem: str = ""

    @property
    def chosen(self) -> bool:
        return self.industries is not None


class UnknownIndustry(ValueError):
    """A write named an industry no shipped package carries."""

    def __init__(self, unknown: list[str], shipped: list[str]) -> None:
        super().__init__(f"no industry package carries {', '.join(unknown)} — "
                         f"the shipped industries are {', '.join(shipped) or 'none'}")
        self.unknown = unknown
        self.shipped = shipped


def choice_path() -> Path:
    """Where the choice lives: ``AUGHOR_INDUSTRIES_FILE``, else ``industries.json`` in the state directory."""
    return resolve_db_path(CHOICE_ENV, state_dir() / CHOICE_FILE)


def choice_token() -> tuple:
    """Changes whenever the file does — for a cache that derives from the choice."""
    path = choice_path()
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def shipped_industries() -> tuple[ShippedIndustry, ...]:
    """Every industry package the knowledge resolver reads as its industry, ordered by id."""
    from aughor.packs.knowledge import industry_kbs, packages

    names: dict[str, str] = {}
    for package in packages():
        if package.layer == "industry" and package.industry:
            names.setdefault(package.industry, package.name)
    return tuple(ShippedIndustry(id=kb["id"], name=names.get(kb["id"]) or str(kb.get("industry") or kb["id"]),
                                 title=str(kb.get("industry") or ""),
                                 description=" ".join(str(kb.get("description") or "").split()))
                 for kb in industry_kbs())


def read_choice() -> IndustryChoice:
    """The choice as the file states it now. A missing file is every industry; an unreadable one is too,
    with the reason in ``problem``."""
    path, mtime, size = choice_token()
    if mtime is None:
        return IndustryChoice()
    return _parse(path, mtime, size, tuple(i.id for i in shipped_industries()))


def available_industries() -> tuple[str, ...]:
    """The industry ids a connection may resolve to: the chosen ones a package still carries, or every one."""
    shipped = tuple(i.id for i in shipped_industries())
    chosen = read_choice().industries
    return shipped if chosen is None else tuple(i for i in shipped if i in chosen)


def readable_industries(scope: Optional[str]) -> Optional[frozenset[str]]:
    """The entry industries a read in ``scope`` may see — "" is the knowledge every industry shares — or
    None when nothing is filtered.

    ``scope`` is `metric_kb.industry_scope`: an id reads that industry and the shared entries, "" the
    shared ones only, and None (nothing known about the connection) every AVAILABLE industry — which, with
    no choice made, is all of them, as before IP-2."""
    if scope:
        return frozenset(("", scope))
    if scope is not None:
        return frozenset(("",))
    if not read_choice().chosen:
        return None
    return frozenset(("", *available_industries()))


def write_choice(industries: Optional[Iterable[str]], *, source: str) -> IndustryChoice:
    """Record a choice: None for every industry, else the ids to keep (none is a choice too). Refuses an id
    no shipped package carries. Written whole, then moved into place, so a reader never sees half a file."""
    shipped = [i.id for i in shipped_industries()]
    value: Optional[list[str]] = None
    if industries is not None:
        ids = sorted({str(i).strip() for i in industries if str(i).strip()})
        unknown = [i for i in ids if i not in shipped]
        if unknown:
            raise UnknownIndustry(unknown, shipped)
        value = ids
    path = choice_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"industries": value, "source": source,
               "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    fd, tmp = tempfile.mkstemp(prefix=".industries-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, indent=2) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return read_choice()


def describe(choice: IndustryChoice) -> str:
    """The choice in words, for a terminal or a log line."""
    if not choice.chosen:
        return "every industry, detected per connection"
    if not choice.industries:
        return "none — only the knowledge every industry shares"
    names = {i.id: i.name for i in shipped_industries()}
    return ", ".join(names.get(i, i) for i in choice.industries)


@lru_cache(maxsize=8)
def _parse(path: str, _mtime: int, _size: int, shipped: tuple[str, ...]) -> IndustryChoice:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return IndustryChoice(problem=f"{path} could not be read ({type(exc).__name__}) — "
                                      f"every industry stays available")
    if not isinstance(data, dict):
        return IndustryChoice(problem=f"{path} is not an object — every industry stays available")
    raw = data.get("industries")
    source, updated_at = str(data.get("source") or ""), str(data.get("updated_at") or "")
    if raw is None:
        return IndustryChoice(source=source, updated_at=updated_at)
    if not isinstance(raw, list) or not all(isinstance(i, str) for i in raw):
        return IndustryChoice(source=source, updated_at=updated_at,
                              problem=f"{path}: industries must be a list of ids or null — "
                                      f"every industry stays available")
    ids = tuple(sorted({i.strip() for i in raw if i.strip()}))
    return IndustryChoice(industries=tuple(i for i in ids if i in shipped), source=source,
                          updated_at=updated_at, ignored=tuple(i for i in ids if i not in shipped))
