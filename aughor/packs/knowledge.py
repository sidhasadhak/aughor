"""IP-1 — the package seam: ONE reader for the knowledge that packages carry.

Before this wave the knowledge base lived under `data/kb/`, and four modules each read it
their own way: the playbook seeder walked every file recursively, the profiler read the
root files for fact-table names, the industry KB read an `industry/` folder plus the file
names each industry claimed, and the vector retriever read the root files as tiers. They
agreed on a path and on nothing else. The knowledge now lives in PACKAGES (ROADMAP §3.17),
and this module is the only thing that finds it:

- a **package** is a pack whose manifest declares a knowledge `layer`: `industry` (one
  industry — `industry.json`, its curated metrics and aliases, plus `kb/*.json`),
  `function` (finance, marketing, product, customer — read by every industry) or `base`
  (what every analysis shares);
- an entry's **industry is the industry of the package that carries it** — ownership by
  place, where it used to be a list of file names each industry had to keep in step with
  the folder (`industry.json`'s `kb_files` still says it, and `problems()` holds the two
  equal);
- authored packages win an id collision (the roots' rule), a **deprecated** package is
  not read, and a draft one is: knowledge is reference, not steering (§3.17);
- every file is read as **UTF-8** — three of the four old loaders used the platform
  default, so on a Windows install three KB files failed to decode and were skipped
  without a word.

The INDEX (which packages, which files, the curated industries, which industry owns which
entry) is resolved once per set of pack roots and cached; the KB payloads themselves are
re-read from disk on each `iter_kb_payloads()` pass, because their readers run at boot,
at import or when an index is empty, and holding ~2 MB of JSON parsed for the life of the
process would buy nothing. `reset()` drops the index for a caller that rewrites a package
in place.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterator

import yaml

from aughor.packs.models import KNOWLEDGE_LAYERS, PackManifest
from aughor.packs.roots import pack_roots

logger = logging.getLogger(__name__)

#: An industry package's curated knowledge: its display name, aliases (specific and
#: generic), the KB files it carries, a description and its metric recipes — moved
#: unchanged from `data/kb/industry/<id>.json`.
INDUSTRY_FILE = "industry.json"
#: A package's knowledge-base entries: causes, detection SQL, fixes, patterns.
KB_DIR = "kb"


@dataclass(frozen=True)
class KbFile:
    """One `kb/*.json` file and the package that carries it."""
    pack_id: str
    layer: str
    industry: str           # "" unless the package is an industry's
    path: Path

    @property
    def name(self) -> str:
        """The bare file name — what a retriever's vector id and a source label use, and
        what stays the same across the move out of `data/kb`."""
        return self.path.name

    @property
    def stem(self) -> str:
        return self.path.stem


@dataclass(frozen=True)
class Package:
    pack_id: str
    layer: str
    industry: str
    directory: Path


@dataclass(frozen=True)
class KnowledgeIndex:
    packages: tuple[Package, ...] = ()
    files: tuple[KbFile, ...] = ()
    industries: tuple[dict, ...] = ()
    entry_industry: dict = field(default_factory=dict)
    problems: tuple[str, ...] = ()


def cache_token() -> tuple[str, ...]:
    """The pack roots the index is resolved for. A cache elsewhere that derives from the
    index keys on this, so moving a root (a test does) never serves another root's KB."""
    return tuple(str(root) for root in pack_roots())


def knowledge_index() -> KnowledgeIndex:
    return _resolve(cache_token())


def reset() -> None:
    """Forget the resolved index — for a caller that rewrites a package in place."""
    _resolve.cache_clear()


def packages() -> tuple[Package, ...]:
    return knowledge_index().packages


def kb_files() -> tuple[KbFile, ...]:
    """Every `kb/*.json` file across the knowledge packages, ordered by file name — the
    order the flat `data/kb` listing had, so nothing downstream reorders."""
    return knowledge_index().files


def industry_kbs() -> tuple[dict, ...]:
    """The curated industries, ordered by industry id: each package's `industry.json` with
    `id` set to the id its manifest declares. Shared objects — treat as read-only."""
    return knowledge_index().industries


def entry_industry(entry_id: str | None) -> str:
    """The industry that owns a KB entry — the industry of the package carrying it — or ""
    for an entry every industry reads (a function's, a base's, or an unknown id)."""
    if not entry_id:
        return ""
    return knowledge_index().entry_industry.get(entry_id, "")


def problems() -> tuple[str, ...]:
    """What is structurally wrong with the packages as found, in sentences. Each problem
    names what was skipped so the index never silently guesses."""
    return knowledge_index().problems


def iter_kb_payloads() -> Iterator[tuple[KbFile, object]]:
    """Each KB file with its parsed JSON (a list of entries, or one entry), read from disk
    as UTF-8 on every pass. A file that no longer parses is skipped with a warning — the
    index recorded it when it was resolved."""
    for kb_file in kb_files():
        data = _read_json(kb_file.path)
        if data is not None:
            yield kb_file, data


def package_checks(pack) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one loaded pack's knowledge layer — what `validate_loaded` and the
    roster report, so a malformed package is named before an agent reads around the hole."""
    m = pack.manifest
    errors: list[str] = []
    warnings: list[str] = []
    if not (m.layer or m.industry):
        return errors, warnings
    if m.layer not in KNOWLEDGE_LAYERS:
        errors.append(f"manifest: layer {m.layer!r} not in {KNOWLEDGE_LAYERS}")
        return errors, warnings
    if m.layer == "industry" and not m.industry:
        errors.append("manifest: layer industry needs an industry id")
    if m.layer != "industry" and m.industry:
        errors.append(f"manifest: industry {m.industry!r} is only meaningful on layer industry")
    directory = Path(pack.path)
    if m.layer == "industry" and not isinstance(_read_json(directory / INDUSTRY_FILE), dict):
        errors.append(f"an industry package needs {INDUSTRY_FILE} (an object)")
    if not sorted((directory / KB_DIR).glob("*.json")):
        warnings.append(f"no {KB_DIR}/*.json — the package carries no knowledge entries")
    own = (f"package {m.id}:", f"pack {m.id}:")
    errors.extend(p for p in problems() if p.startswith(own))
    return errors, warnings


# ── resolution ──────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=4)
def _resolve(roots: tuple[str, ...]) -> KnowledgeIndex:
    problems: list[str] = []
    found = _find_packages([Path(r) for r in roots], problems)

    # The industries first: an industry package is read AS its industry only when its
    # curated file is there and no earlier package already carries that industry.
    industries: list[dict] = []
    industry_pack: dict[str, str] = {}
    for package in found:
        if package.layer != "industry" or not package.industry:
            continue
        if package.industry in industry_pack:
            problems.append(f"package {package.pack_id}: industry '{package.industry}' is "
                            f"already carried by package {industry_pack[package.industry]} — "
                            f"this one is not read as that industry")
            continue
        curated = _read_json(package.directory / INDUSTRY_FILE)
        if not isinstance(curated, dict):
            problems.append(f"package {package.pack_id}: an industry package needs "
                            f"{INDUSTRY_FILE} (an object) — none was read")
            continue
        industry_pack[package.industry] = package.pack_id
        industries.append({**curated, "id": package.industry})
    industries.sort(key=lambda kb: kb["id"])

    files: list[KbFile] = []
    carried_by: dict[str, str] = {}
    owners: dict[str, str] = {}
    for package in found:
        owns = industry_pack.get(package.industry) == package.pack_id
        for path in sorted((package.directory / KB_DIR).glob("*.json")):
            if path.name in carried_by:
                # A retriever indexes an entry as kb::<file name>::<entry id>; the same file
                # name in two packages would make one overwrite the other.
                problems.append(f"package {package.pack_id}: kb/{path.name} is also carried "
                                f"by package {carried_by[path.name]} — the second copy is not read")
                continue
            data = _read_json(path)
            if data is None:
                problems.append(f"package {package.pack_id}: kb/{path.name} could not be "
                                f"parsed as JSON — not read")
                continue
            carried_by[path.name] = package.pack_id
            industry = package.industry if owns else ""
            files.append(KbFile(pack_id=package.pack_id, layer=package.layer,
                                industry=industry, path=path))
            if not industry:
                continue
            for entry in (data if isinstance(data, list) else [data]):
                entry_id = entry.get("id") if isinstance(entry, dict) else None
                if not entry_id:
                    continue
                if owners.get(entry_id, industry) != industry:
                    problems.append(f"entry {entry_id} is carried by industries "
                                    f"{owners[entry_id]} and {industry} — kept as {owners[entry_id]}")
                    continue
                owners[entry_id] = industry
    files.sort(key=lambda f: (f.name, f.pack_id))

    for kb in industries:
        pack_id = industry_pack[kb["id"]]
        declared = sorted(str(s) for s in (kb.get("kb_files") or []))
        carried = sorted(f.stem for f in files if f.pack_id == pack_id)
        if declared != carried:
            problems.append(f"package {pack_id}: {INDUSTRY_FILE} lists kb_files {declared} "
                            f"but the package carries {carried}")

    return KnowledgeIndex(packages=tuple(found), files=tuple(files),
                          industries=tuple(industries), entry_industry=owners,
                          problems=tuple(problems))


def _find_packages(roots: list[Path], problems: list[str]) -> list[Package]:
    """Knowledge packages across the roots, authored first; an id already found in an
    earlier root is shadowed. Reads manifests only — a package's KB must not become
    unreadable because an unrelated file elsewhere in its pack is malformed."""
    found: list[Package] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for directory in sorted(p for p in root.iterdir() if (p / "pack.yaml").is_file()):
            try:
                raw = yaml.safe_load((directory / "pack.yaml").read_text(encoding="utf-8")) or {}
                manifest = PackManifest.model_validate(raw)
            except Exception as exc:
                problems.append(f"pack {directory.name}: pack.yaml could not be read "
                                f"({type(exc).__name__}) — skipped")
                continue
            if not manifest.layer:
                if manifest.industry:
                    problems.append(f"pack {manifest.id}: declares industry "
                                    f"'{manifest.industry}' without layer: industry — not read")
                continue
            if manifest.layer not in KNOWLEDGE_LAYERS:
                problems.append(f"pack {manifest.id}: layer '{manifest.layer}' is not one of "
                                f"{', '.join(KNOWLEDGE_LAYERS)} — not read")
                continue
            if manifest.id in seen:
                continue                                    # authored wins
            seen.add(manifest.id)
            if manifest.status == "deprecated":
                continue
            if manifest.layer == "industry" and not manifest.industry:
                problems.append(f"pack {manifest.id}: layer industry needs an industry id — "
                                f"read as knowledge every industry shares")
            if manifest.layer != "industry" and manifest.industry:
                problems.append(f"pack {manifest.id}: industry '{manifest.industry}' is only "
                                f"meaningful on layer industry — ignored")
            found.append(Package(pack_id=manifest.id, layer=manifest.layer,
                                 industry=manifest.industry if manifest.layer == "industry" else "",
                                 directory=directory))
    return found


def _read_json(path: Path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("knowledge package file %s could not be read: %s", path, exc)
        return None
