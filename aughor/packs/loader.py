"""Load a specialist pack from its folder (P0).

`pack.yaml` is the only required file; every other part is optional so a pack can grow
incrementally. The loader is pure I/O + parsing — it does NOT touch a connection or the LLM
(that's the resolver, P1) — so it's cheap and deterministic.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

import yaml
from pydantic import ValidationError

from aughor.packs.models import (
    Pack, PackDataset, PackFunction, PackManifest, PackMetric, PackOntology, PackQuestions, PackPlaybook,
    PackSource, PackSurface, PackEval, RoleSpec,
)


#: The on-disk filename this loader reads prose from, and the `Pack` field it lands in.
#: Frozen format — named here, where the format is owned, so callers and their tests can
#: refer to it without re-typing a string the glossary has retired as a WORD.
PROSE_FILE = "expertise.md"
PROSE_FIELD = PROSE_FILE.removesuffix(".md")


class PacksError(Exception):
    """A pack folder is missing its manifest or has unparseable YAML."""


def _read_yaml(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise PacksError(f"invalid YAML in {path.name}: {e}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise PacksError(f"{path.name} must be a YAML mapping, got {type(data).__name__}")
    return data


def _read_yaml_list(path: Path) -> list:
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise PacksError(f"invalid YAML in {path.name}: {e}") from e
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


def load_pack(path: Union[str, Path]) -> Pack:
    """Load the pack rooted at `path`. Raises PacksError if `pack.yaml` is absent or invalid, or when any other
    file does not fit its model — every caller catches PacksError, and a pydantic error from a metric or an
    ontology file used to escape them all (the roster route included)."""
    try:
        return _load_pack(Path(path))
    except ValidationError as e:
        raise PacksError(f"invalid pack file in {path}: {e}") from e


def _load_pack(root: Path) -> Pack:
    manifest_file = root / "pack.yaml"
    if not manifest_file.is_file():
        raise PacksError(f"no pack.yaml in {root}")
    try:
        manifest = PackManifest(**_read_yaml(manifest_file))
    except ValidationError as e:
        raise PacksError(f"invalid pack.yaml in {root}: {e}") from e
    if not (manifest.id or "").strip():
        raise PacksError(f"pack.yaml in {root} is missing a non-empty 'id'")

    expertise = ""
    exp_file = root / PROSE_FILE
    if exp_file.is_file():
        expertise = exp_file.read_text(encoding="utf-8")

    metrics: list[PackMetric] = []
    metrics_dir = root / "metrics"
    if metrics_dir.is_dir():
        for f in sorted(metrics_dir.glob("*.yaml")):
            metrics.append(PackMetric(**_read_yaml(f)))

    entities: dict[str, RoleSpec] = {}
    ent_file = root / "entities.yaml"
    if ent_file.is_file():
        raw = _read_yaml(ent_file).get("roles", {}) or {}
        entities = {name: RoleSpec(**(spec or {})) for name, spec in raw.items()}

    questions = PackQuestions()
    q_file = root / "questions.yaml"
    if q_file.is_file():
        questions = PackQuestions(**_read_yaml(q_file))

    playbooks: list[PackPlaybook] = []
    pb_dir = root / "playbooks"
    if pb_dir.is_dir():
        for f in sorted(pb_dir.glob("*.yaml")):
            playbooks.append(PackPlaybook(**_read_yaml(f)))

    surface = None
    s_file = root / "surface.yaml"
    if s_file.is_file():
        surface = PackSurface(**_read_yaml(s_file))

    evals: list[PackEval] = []
    ev_dir = root / "evals"
    if ev_dir.is_dir():
        for f in sorted(ev_dir.glob("*.yaml")):
            for item in _read_yaml_list(f):
                if isinstance(item, dict) and item.get("question"):
                    evals.append(PackEval(**item))

    ontology = None
    o_file = root / "ontology.yaml"
    if o_file.is_file():
        ontology = PackOntology(**(_read_yaml(o_file) or {}))

    function = None
    f_file = root / "function.yaml"
    if f_file.is_file():
        function = PackFunction(**(_read_yaml(f_file) or {}))

    # IP-3 — the cited sources and the named datasets of a full-anatomy package.
    sources: list[PackSource] = []
    src_file = root / "sources.yaml"
    if src_file.is_file():
        for item in (_read_yaml(src_file).get("sources") or []):
            if not isinstance(item, dict):
                raise PacksError(f"sources.yaml: every source must be a mapping, got {type(item).__name__}")
            sources.append(PackSource(**item))

    datasets: list[PackDataset] = []
    ds_dir = root / "datasets"
    if ds_dir.is_dir():
        for f in sorted(ds_dir.glob("*.yaml")):
            datasets.append(PackDataset(**_read_yaml(f)))

    return Pack(
        manifest=manifest, expertise=expertise, metrics=metrics, entities=entities,
        questions=questions, playbooks=playbooks, surface=surface, evals=evals,
        ontology=ontology, function=function, sources=sources, datasets=datasets, path=str(root),
    )


def list_packs(packs_dir: Union[str, Path]) -> list[str]:
    """Ids of every loadable pack under `packs_dir` (a subdir with a valid pack.yaml).
    Skips folders whose manifest can't be read, so one broken pack never hides the rest."""
    base = Path(packs_dir)
    if not base.is_dir():
        return []
    ids: list[str] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or not (child / "pack.yaml").is_file():
            continue
        try:
            ids.append(load_pack(child).id)
        except PacksError as e:
            from aughor.kernel.errors import tolerate
            tolerate(e, f"skip unloadable pack dir {child.name}", counter="packs.list_skip")
            continue
    return ids
