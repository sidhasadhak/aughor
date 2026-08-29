"""Every driver a connector imports has to be DECLARED somewhere, and every extra a
connector depends on has to be imported by something.

Both directions were broken, and both failed the same way: silently, at the worst moment.

* **`pyexasol` was declared nowhere.** Not in the base dependencies, not in `[warehouse]`,
  not in any other extra — while `exasol.py` imports it and its own `dep_check` names the
  pin. So the Exasol tile could not work in ANY install of this project, including a full
  `[warehouse]` one. The picker offered it, and the ImportError arrived *after* the user
  had filled in a connection form.
* **`[crm]` declared three vendor SDKs nothing imports** — `stripe`, `hubspot-api-client`,
  `simple-salesforce` — and omitted `requests`, which all three REST connectors import at
  MODULE level. It worked only because something else drags `requests` in transitively,
  which is a fact about today's resolution and not a declaration.

The registry already keeps `DRIVERS` so the picker can tell a user which tiles cannot run
here. This asserts the same list against the packaging, which is the half nobody could see:
a driver named in `DRIVERS` and in no dependency list means the tile is offered by a build
that can never satisfy it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from aughor.connectors.registry import DRIVERS, PROVIDED_BY

REPO = Path(__file__).resolve().parents[2]

#: The extras whose contents exist to serve connectors. Other extras (`export`, `docs`, …)
#: are out of scope here — this file is about the connector plane's packaging.
CONNECTOR_EXTRAS = ("warehouse", "crm")


def _pyproject() -> str:
    return (REPO / "pyproject.toml").read_text()


def _declared(dist: str) -> bool:
    """Is `dist` pinned anywhere in pyproject — base dependencies or any extra?"""
    return re.search(rf'^\s*"{re.escape(dist)}(\[[^\]]*\])?[><=~!]', _pyproject(),
                     re.MULTILINE | re.IGNORECASE) is not None


def _extra_entries(name: str) -> list[str]:
    block = re.search(rf"^{name} = \[(.*?)^\]", _pyproject(), re.MULTILINE | re.DOTALL)
    assert block, f"extra {name!r} not found — the parser drifted from pyproject.toml"
    return [m.group(1) for m in re.finditer(r'"([A-Za-z0-9_.\-]+)', block.group(1))]


@pytest.mark.parametrize("module", sorted({m for mods in DRIVERS.values() for m in mods}))
def test_every_driver_a_connector_imports_is_declared(module):
    """A driver in `DRIVERS` and in no dependency list means a tile the picker offers and
    no install can satisfy."""
    dist = PROVIDED_BY.get(module)
    assert dist, (f"{module!r} is imported by a registered connector but this map does not "
                  f"say which distribution provides it — add it, do not delete the driver")
    assert _declared(dist), (
        f"connectors import {module!r}, which comes from {dist!r} — pinned in NO dependency "
        f"list. Every install offering that tile fails at connect time")


@pytest.mark.parametrize("extra", CONNECTOR_EXTRAS)
def test_a_connector_extra_declares_nothing_the_code_ignores(extra):
    """The other direction. A dependency nothing imports is not free: it is weight on
    every install of that extra, and it reads as support the code does not have."""
    sources = "\n".join(p.read_text(errors="ignore")
                        for p in (REPO / "aughor").rglob("*.py"))
    by_dist = {d: m for m, d in PROVIDED_BY.items()}
    unused = []
    for dist in _extra_entries(extra):
        module = by_dist.get(dist)
        if module is None:
            unused.append(f"{dist} (not in PROVIDED_BY — is it a real import of ours?)")
            continue
        head = module.split(".")[0]
        if not re.search(rf"^\s*(?:import\s+{re.escape(head)}\b|from\s+{re.escape(head)}\b)",
                         sources, re.MULTILINE):
            unused.append(f"{dist} → nothing imports {module!r}")
    assert not unused, (
        f"[{extra}] declares dependencies the code never imports: {unused}. Either import "
        f"them or drop them — a vendor SDK nobody calls is weight that reads as support")


def test_the_rest_connectors_http_client_is_declared_not_inherited():
    """The specific failure worth naming: three connectors import `requests` at module
    level, and the extra that exists for them declared three SDKs they do not use. It
    resolved anyway, transitively — which is why nothing noticed."""
    for name in ("stripe", "hubspot", "salesforce"):
        src = (REPO / "aughor" / "connectors" / "api" / f"{name}.py").read_text()
        assert re.search(r"^import requests$", src, re.MULTILINE), (
            f"{name}.py no longer imports requests at module level — if the HTTP client "
            f"changed, [crm] has to change with it")
    assert "requests" in _extra_entries("crm")
