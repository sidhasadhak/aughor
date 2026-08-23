"""VA-1 — SKILL.md → a pack, without pretending it is a whole one.

The library this reads is third-party prose in Anthropic's SKILL.md format: YAML
frontmatter naming the skill, then a markdown body of domain knowledge. A pack in this repo is
richer — entities, metrics, questions, goldens — and a skill supplies exactly ONE of
those layers. That gap is the whole design problem here, and it has an honest answer and
a dishonest one:

* dishonest — write the pack with empty `entities.yaml` / `metrics/` / `questions.yaml`.
  It loads, it looks complete, and every surface that reads a pack reports a specialist
  that knows nothing. An empty structure is indistinguishable from an unpopulated one.
* honest — write ONLY what the skill actually contains, mark the manifest `partial`, and
  leave the absent layers ABSENT. A reader can then tell a prose-only pack from a
  fully grounded pack, because the two do not look alike.

This module takes the second. `partial=True` is the flag; the missing files are simply
not created.

**Nothing here is active on arrival.** The manifest is written `status: draft`, and
`active_packs()` filters on `status == "active"` — so an imported skill is inert until a
human promotes it. That is deliberate: this content is untrusted, and the existing status
gate already means exactly "on disk, not yet in anyone's prompt". A new flag would have
been a second switch for one idea.

**Planning is separate from writing.** `plan_pack` returns the files it WOULD create and
touches no disk; `write_pack` commits a plan. The review screen the wave calls for is a
diff of a plan, and a function that both decides and writes cannot offer one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from aughor.packs.loader import PROSE_FILE as _PROSE_FILE

from aughor.skills.lint import Finding, Severity, blocks, lint_skill

#: The upstream library this was built for. Recorded on every pack so provenance
#: survives; overridable because it is not the only library in the format.
DEFAULT_SOURCE = "awesome-agent-skills"

#: Re-exported from the loader, which owns the frozen on-disk format. Imported rather
#: than repeated: one authority for the name a pack's prose file must have.
PROSE_FILE = _PROSE_FILE

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


class SkillIngestError(Exception):
    """A skill that cannot become a pack at all. Distinct from a lint BLOCK, which is a
    skill that could be a pack and must not be."""


def slugify(name: str) -> str:
    """A pack id from a skill name: lowercase, hyphenated, nothing else.

    Deliberately destructive rather than clever. This value becomes a DIRECTORY NAME, so
    the only safe rule is an allowlist — a skill called `../../etc/passwd` slugs to
    `etc-passwd` and lands where every other pack lands. A denylist of dangerous
    sequences is the version of this function that eventually ships a traversal.
    """
    return _SLUG_STRIP.sub("-", (name or "").strip().lower()).strip("-")


@dataclass(frozen=True)
class SkillDoc:
    """One parsed SKILL.md."""
    name: str
    description: str
    body: str
    frontmatter: dict


def parse_skill(text: str) -> SkillDoc:
    """Split a SKILL.md into its frontmatter and its prose.

    A skill with no frontmatter is refused rather than guessed at: the frontmatter is
    where the NAME lives, and a pack with an invented name is one nobody can find again.
    """
    m = _FRONTMATTER.match(text or "")
    if not m:
        raise SkillIngestError(
            "no YAML frontmatter — a SKILL.md must open with a --- block naming the skill")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillIngestError(f"frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise SkillIngestError("frontmatter is not a mapping")

    name = str(meta.get("name") or "").strip()
    if not name:
        raise SkillIngestError("frontmatter has no 'name'")
    body = (m.group(2) or "").strip()
    if not body:
        raise SkillIngestError(f"'{name}' has frontmatter but no body — there is no "
                               "knowledge to import")
    return SkillDoc(name=name, description=str(meta.get("description") or "").strip(),
                    body=body, frontmatter=meta)


@dataclass(frozen=True)
class PackPlan:
    """What an import WOULD create. Nothing here has touched the disk."""
    pack_id: str
    name: str
    #: Relative path → file content. Exactly the files the skill justifies, no more.
    files: dict[str, str]
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(blocks(self.findings))

    @property
    def warnings(self) -> list[Finding]:
        """The spot-check's worklist. Decision ② made the linter the primary defence and
        a hand-reviewed sample the secondary one — this is what that review reads."""
        return [f for f in self.findings if f.severity is Severity.WARN]


def plan_pack(text: str, *, source: str = DEFAULT_SOURCE, source_url: str = "",
              licence: str = "", pack_id: str = "", namespace: str = "") -> PackPlan:
    """Lint a skill and describe the pack it becomes. Writes nothing.

    The lint runs FIRST and its result is carried on the plan, so a caller cannot obtain
    a set of files without also obtaining the verdict on them. Returning the plan even
    when blocked is deliberate — the review screen must be able to show what was refused
    and why, and a bare exception carries neither.
    """
    doc = parse_skill(text)
    # `namespace` is not decoration. Skill names in the wild are generic — a sweep of 28
    # real SKILL.md files here produced `access` three times and `configure` three times,
    # from three different plugins. Bulk import (decision ②) walks straight into that on
    # the third file, so the caller needs a way to disambiguate that is not "rename
    # someone else's skill".
    pid = (pack_id or slugify(doc.name))
    if namespace.strip() and not pack_id:
        pid = f"{slugify(namespace)}-{pid}".strip("-")
    if not pid:
        raise SkillIngestError(f"'{doc.name}' does not reduce to a usable pack id")

    findings = lint_skill(text, name=doc.name)
    if not licence.strip():
        findings = findings + [Finding(
            "licence", Severity.WARN, 1, "(none recorded)",
            "arrives with no licence recorded. Third-party prose redistributed inside "
            "this repo needs its terms known — record them before promoting the pack.")]

    if blocks(findings):
        # No files. A blocked skill must not leave a half-written pack behind for a
        # later import to find and mistake for reviewed content.
        return PackPlan(pack_id=pid, name=doc.name, files={}, findings=findings)

    manifest = {
        "id": pid,
        "name": doc.name,
        "version": 1,
        "domains": _domains(doc),
        "extends": [],
        "scope": {"connections": ["*"]},
        # Inert until a human promotes it. `active_packs()` reads this.
        "status": "draft",
        # Provenance. Recorded on the pack rather than in a sidecar so it cannot be
        # separated from the content it describes.
        "source": source,
        "source_url": source_url,
        "licence": licence,
        # The honest flag: prose only, no entities/metrics/goldens.
        "partial": True,
    }

    files = {
        "pack.yaml": yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        PROSE_FILE: _prose(doc),
    }
    return PackPlan(pack_id=pid, name=doc.name, files=files, findings=findings)


def _domains(doc: SkillDoc) -> list[str]:
    """Routing hints, taken only from what the author actually declared.

    Never inferred from the prose. A guessed domain routes real questions to a pack that
    was never about them, and a wrong routing hint is harder to notice than a missing one.

    ``metadata.category`` counts as declared. Google's skills carry their subject there
    rather than in `domains` — `BigDataAndAnalytics`, `Databases` — and reading a field the
    author filled in is not inference. Measured 2026-08-24: without it, every skill in that
    library imported with `domains: []`, which is a pack that can never be routed to.
    """
    fm = doc.frontmatter
    raw = fm.get("domains") or fm.get("tags") or []
    if isinstance(raw, str):
        raw = [raw]
    out = [str(d).strip() for d in raw if str(d).strip()]
    meta = fm.get("metadata")
    if not out and isinstance(meta, dict) and meta.get("category"):
        out = [str(meta["category"]).strip()]
    return out


def _prose(doc: SkillDoc) -> str:
    """The skill's body, with a header saying where it came from and what it is not."""
    head = [f"# {doc.name}", ""]
    if doc.description:
        head += [doc.description, ""]
    head += [
        "> Imported from a third-party agent skill. This pack carries **prose "
        "only** — it declares no entities, metrics or goldens, so nothing here is bound "
        "to your data or checked against it.",
        "",
    ]
    return "\n".join(head) + doc.body.rstrip() + "\n"


def write_pack(plan: PackPlan, packs_dir: Path | str, *, overwrite: bool = False) -> Path:
    """Commit a plan to disk. Refuses a blocked plan and refuses to clobber by default."""
    if plan.blocked:
        raise SkillIngestError(
            f"'{plan.name}' did not pass the import gate: "
            + "; ".join(f"{f.rule} (line {f.line})" for f in blocks(plan.findings)))
    if not plan.files:
        raise SkillIngestError(f"'{plan.name}' produced no files to write")

    root = Path(packs_dir) / plan.pack_id
    # The slug is an allowlist, but this is the assertion that makes the guarantee local:
    # a caller-supplied `pack_id` reaches here too.
    if root.parent.resolve() != Path(packs_dir).resolve():
        raise SkillIngestError(f"'{plan.pack_id}' does not resolve inside the packs dir")
    if root.exists() and not overwrite:
        raise SkillIngestError(
            f"pack '{plan.pack_id}' already exists. Re-import with overwrite to replace it.")

    root.mkdir(parents=True, exist_ok=True)
    for rel, content in plan.files.items():
        (root / rel).write_text(content)
    return root


def ingest_skill(text: str, packs_dir: Path | str, *, source: str = DEFAULT_SOURCE,
                 source_url: str = "", licence: str = "", pack_id: str = "",
                 namespace: str = "", overwrite: bool = False
                 ) -> tuple[Optional[Path], PackPlan]:
    """Plan and write in one call. Returns `(path or None, plan)` — the plan always, so a
    refusal is as inspectable as a success."""
    plan = plan_pack(text, source=source, source_url=source_url, licence=licence,
                     pack_id=pack_id, namespace=namespace)
    if plan.blocked:
        return None, plan
    return write_pack(plan, packs_dir, overwrite=overwrite), plan
