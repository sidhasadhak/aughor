"""The pack kit — validate, check and upload a pack of declarations (the 2027 study §Q; phase 7, P7-3).

The platform's equivalent of an app is the pack: a bundle of declarations the platform measures,
compiles and scores — never code that runs inside it. Until now a pack reached an install by being
written into its tree; the kit is the door an author uses instead:

- :func:`guide` — the authoring guide, read from the models that define the anatomy (every file, what
  it declares, its schema), the gates a pack passes, and the rules (declarations only; a prior says
  where it was measured; a template names what the kernel has);
- :func:`check` — the static gate over a set of files without writing anything: the loader, the
  structural validation, gate 3 for a package that declares the anatomy, the priors' rule;
- :func:`upload` — the same check, then the pack written as a DRAFT under the imported root with
  its provenance (who uploaded it, when, from where); a pack with errors is refused with them. A
  draft steers nothing and reaches no prompt until a person activates it through the same gate every
  pack passes (`packs/promote.set_status`), and it is listed from then on with its measured record.

What an upload cannot carry: anything but text declarations (YAML, Markdown, JSON), a path outside
the pack, more than :data:`MAX_FILES` files or :data:`MAX_BYTES` in all, or a manifest whose id is
not the pack's own.
"""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

ALLOWED_SUFFIXES: tuple[str, ...] = (".yaml", ".yml", ".md", ".json")
MAX_FILES = 200
MAX_BYTES = 2_000_000
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")


class KitRefused(ValueError):
    """The kit said no, and why."""


def path_problems(files: dict[str, str]) -> list[str]:
    """Every way a set of files is not a pack an install may hold."""
    problems: list[str] = []
    if not isinstance(files, dict) or not files:
        return ["no files"]
    if len(files) > MAX_FILES:
        problems.append(f"{len(files)} files; the kit takes at most {MAX_FILES}")
    total = 0
    for rel, text in files.items():
        if not isinstance(text, str):
            problems.append(f"{rel}: a pack is text declarations, not binary")
            continue
        total += len(text.encode("utf-8"))
        p = Path(rel)
        if p.is_absolute() or ".." in p.parts or not rel.strip() or rel.startswith("/"):
            problems.append(f"{rel!r}: a path stays inside the pack")
        if p.suffix.lower() not in ALLOWED_SUFFIXES:
            problems.append(f"{rel}: only {', '.join(ALLOWED_SUFFIXES)} files — a pack holds declarations, never code")
    if total > MAX_BYTES:
        problems.append(f"{total} bytes; the kit takes at most {MAX_BYTES}")
    if "pack.yaml" not in files:
        problems.append("no pack.yaml — the manifest is the one required file")
    return problems


def stage(files: dict[str, str]) -> Path:
    """Write the files into a fresh temporary directory (the caller removes it)."""
    root = Path(tempfile.mkdtemp(prefix="aughor-pack-kit-"))
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def check(files: dict[str, str]) -> dict[str, Any]:
    """The static gate over a set of files, writing nothing an install keeps."""
    problems = path_problems(files)
    if problems:
        return {"ok": False, "pack_id": "", "errors": problems, "warnings": [], "files": len(files or {})}
    root = stage(files)
    try:
        from aughor.packs.loader import PacksError, load_pack
        from aughor.packs.validate import validate_loaded
        try:
            pack = load_pack(root)
        except PacksError as exc:
            return {"ok": False, "pack_id": "", "errors": [f"load failed: {exc}"], "warnings": [], "files": len(files)}
        report = validate_loaded(pack)
        errors = list(report.errors)
        if not _ID.match(pack.id or ""):
            errors.append(f"pack id {pack.id!r} is 2 to 63 characters of lowercase letters, digits, '-' or '_'")
        from aughor.packs.gate3 import applies
        return {"ok": not errors, "pack_id": pack.id, "errors": errors, "warnings": list(report.warnings), "files": len(files),
                "anatomy": pack.manifest.anatomy, "static_gate": "gate 3 held" if applies(pack) else "gate 3 not declared (anatomy 0)",
                "declares": {"metrics": len(pack.metrics), "roles": len(pack.entities), "plays": len(pack.playbooks),
                             "goldens": len(pack.evals), "ontology": pack.ontology is not None, "monitors": len(pack.monitors),
                             "scenarios": len(pack.scenarios), "missions": len(pack.missions)}}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def upload(files: dict[str, str], *, by: str, source: str = "upload", source_url: str = "", overwrite: bool = False) -> dict[str, Any]:
    """Check, then write the pack as a draft under the imported root with its provenance. Refuses a
    pack with errors (said), an id that already exists unless ``overwrite``, and an uploader with no
    name."""
    if not (by or "").strip():
        raise KitRefused("an upload is made by a named principal")
    verdict = check(files)
    if not verdict["ok"]:
        raise KitRefused("the pack did not pass the static gate: " + "; ".join(verdict["errors"]))
    pack_id = verdict["pack_id"]
    from aughor.packs.roots import authored_root, imported_root
    if (authored_root() / pack_id / "pack.yaml").is_file():
        raise KitRefused(f"{pack_id!r} is an authored pack of this install; an upload cannot shadow it")
    root = imported_root() / pack_id
    if root.parent.resolve() != imported_root().resolve():
        raise KitRefused(f"{pack_id!r} does not resolve inside the imported root")
    if root.exists() and not overwrite:
        raise KitRefused(f"pack {pack_id!r} already exists; upload with overwrite to replace it")
    from aughor.util.time import now_iso_z
    staged = dict(files)
    raw = yaml.safe_load(staged["pack.yaml"]) or {}
    if not isinstance(raw, dict):
        raise KitRefused("pack.yaml must be a YAML mapping")
    # Provenance rides the manifest; status is forced to draft — a pack is inert on arrival.
    raw.update({"status": "draft", "source": source or "upload", "uploaded_by": by, "uploaded_at": now_iso_z()})
    if source_url:
        raw["source_url"] = source_url
    staged["pack.yaml"] = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in staged.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit("pack.uploaded", {"pack_id": pack_id, "by": by, "files": len(staged), "warnings": verdict["warnings"][:20],
                                                "source": source or "upload"})
    except Exception:  # noqa: BLE001 — the files are the authority; the event is the trail
        pass
    return {**verdict, "written_to": str(root), "status": "draft",
            "next": f"a person activates it: POST /packs/{pack_id}/status {{status: active}} — a grounded pack through its evals on a connection"}


def guide() -> dict[str, Any]:
    """The authoring guide, read from the models that define the anatomy."""
    from aughor.packs import models as M
    from aughor.packs.loader import PROSE_FILE
    from aughor.record.mission import CADENCE_DAYS
    from aughor.record.scenario import METHODS

    def schema(model) -> dict:
        s = model.model_json_schema()
        return {"fields": {k: {kk: vv for kk, vv in v.items() if kk in ("type", "description", "default", "enum", "items")}
                           for k, v in (s.get("properties") or {}).items()}, "required": s.get("required", [])}

    anatomy = [
        {"file": "pack.yaml", "required": True, "declares": "identity, status (always draft on arrival), domains, extends, scope, layer", "schema": schema(M.PackManifest)},
        {"file": "ontology.yaml", "declares": "the industry's map as CLAIMS measured on connect: objects, links, lifecycles, processes with promises, rules", "schema": schema(M.PackOntology)},
        {"file": "entities.yaml", "declares": "roles (never tables) with their attributes; a dataset binds them", "schema": schema(M.RoleSpec)},
        {"file": "metrics/*.yaml", "declares": "a metric's statement over role attributes, its unit, a sourced sane range", "schema": schema(M.PackMetric)},
        {"file": "playbooks/*.yaml", "declares": "a play: trigger metric, recommendation, kind, sources; a base rate with where it was measured", "schema": schema(M.PackPlaybook)},
        {"file": "monitors/*.yaml", "declares": "a watch with its PRIOR normal range and where it was measured — or unmeasured, said", "schema": schema(M.PackMonitorPrior)},
        {"file": "scenarios/*.yaml", "declares": "a projection template over a method of the ladder", "schema": schema(M.PackScenarioTemplate)},
        {"file": "missions/*.yaml", "declares": "a mission template a person writes a mission from", "schema": schema(M.PackMissionTemplate)},
        {"file": "questions.yaml", "declares": "canonical and diagnostic questions, routing tags", "schema": schema(M.PackQuestions)},
        {"file": "evals/*.yaml", "declares": "golden questions, each with the expected metric, dataset, value and tolerance", "schema": schema(M.PackEval)},
        {"file": "sources.yaml", "declares": "the cited sources a range, a play or a golden rests on", "schema": schema(M.PackSource)},
        {"file": "datasets/*.yaml", "declares": "the public dataset gate 4 measures the package on — the one place a pack names tables", "schema": schema(M.PackDataset)},
        {"file": "function.yaml", "declares": "the group, subscriptions and automations a function layer ships", "schema": schema(M.PackFunction)},
        {"file": PROSE_FILE, "declares": "prose for the planner; linted before activation; a prose-only pack is `partial`"},
    ]
    return {
        "version": "2027.1",
        "principle": "a pack is data over one kernel: declarations the platform measures, compiles and scores — never code. "
                     "It cannot add a store, a screen type or a code path.",
        "anatomy": anatomy,
        "gates": [
            {"gate": "static validation", "when": "check, upload", "what": "the manifest, roles ↔ metric bindings, plays on declared metrics (`packs/validate.py`)"},
            {"gate": "gate 3", "when": "check, upload — a package declaring anatomy 1", "what": "sources, sane ranges with a source, roles not tables, no alias collision, plays bound, goldens, datasets"},
            {"gate": "the priors' rule", "when": "check, upload — every pack", "what": "a prior states where it was measured or says none; a template names a method the ladder has "
                                                                                       f"({', '.join(METHODS)}) and a cadence the report keeps ({', '.join(CADENCE_DAYS)})"},
            {"gate": "prose lint", "when": "activation", "what": f"the skill-import linter over {PROSE_FILE}; blocked prose cannot be activated"},
            {"gate": "activation by evals", "when": "activation", "what": "a grounded pack is activated by its golden questions passing on a connection with every role bound (Bet 2)"},
            {"gate": "gate 4", "when": "measure", "what": "the package's metrics on its named public dataset, each inside its sane range; the receipt lands in measurements/"},
            {"gate": "the measured record", "when": "always, on every install that binds it", "what": "the pack's claims measured on connect are booked into the Record; a pack whose claims keep failing is demoted by that record (GET /packs/{id}/record)"},
        ],
        "steps": ["write the declarations", "POST /packs/check with the files — fix every error", "POST /packs/upload — the pack lands as a draft with its provenance",
                  "bind it against a connection (POST /packs/{id}/propose-bindings, /bind)", "POST /packs/{id}/evaluate — the goldens on that connection",
                  "a person activates it (POST /packs/{id}/status) — it steers from then on", "read its record as installs measure it (GET /packs/{id}/record)"],
        "limits": {"files": MAX_FILES, "bytes": MAX_BYTES, "suffixes": list(ALLOWED_SUFFIXES)},
        "doors": {"check": "POST /packs/check {files: {path: text}}", "upload": "POST /packs/upload {files, source_url?, overwrite?}",
                  "record": "GET /packs/{id}/record", "listing": "GET /packs/listing", "demote": "POST /packs/{id}/demote"},
    }
