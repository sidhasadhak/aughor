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
    Pack, PackManifest, PackMetric, PackQuestions, PackPlaybook, PackSurface, PackEval, RoleSpec,
)


class PacksError(Exception):
    """A pack folder is missing its manifest or has unparseable YAML."""


def _read_yaml(path: Path) -> dict:
    try:
        with path.open() as f:
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
        with path.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise PacksError(f"invalid YAML in {path.name}: {e}") from e
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


def load_pack(path: Union[str, Path]) -> Pack:
    """Load the pack rooted at `path`. Raises PacksError if `pack.yaml` is absent or invalid."""
    root = Path(path)
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
    exp_file = root / "expertise.md"
    if exp_file.is_file():
        expertise = exp_file.read_text()

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

    return Pack(
        manifest=manifest, expertise=expertise, metrics=metrics, entities=entities,
        questions=questions, playbooks=playbooks, surface=surface, evals=evals,
        path=str(root),
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
        except PacksError:
            continue
    return ids
