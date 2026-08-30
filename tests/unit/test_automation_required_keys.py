"""The client's required-key map is the Python one, or it is a lie.

VA-12 let the canvas author automations, and an authoring surface has to say which step is
incomplete BEFORE it saves: the server's 422 names a config key, and a key says nothing
about which of five steps is carrying it. So `web/lib/api.ts` carries
`AUTOMATION_REQUIRED_KEYS`, a mirror of `_CONDITION_REQUIRED` / `_EFFECT_REQUIRED`.

A hand-copied mirror rots silently and in the worst direction: add a required key in
Python and the UI keeps cheerfully enabling Save, the user writes a step that cannot be
stored, and the failure arrives as a 422 at save time — exactly the experience the mirror
existed to prevent. This repo has shipped that failure mode more than once under a
different name (a guard whose matching key stopped matching), so the mirror gets a guard.

Deliberately one-directional on the effect side: the client offers a SUBSET of the
kinds the server accepts — `monitor` and `agent_alert` are adopted objects the model's own
docstring says are "not authored by hand", and `slack_post` needs a bot picker no client
API supports yet. So every kind the client declares must match Python; kinds the client
omits are its own business.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from aughor.automations.models import _CONDITION_REQUIRED, _EFFECT_REQUIRED

API_TS = Path(__file__).resolve().parents[2] / "web" / "lib" / "api.ts"


def _client_map() -> dict[str, list[str]]:
    """`AUTOMATION_REQUIRED_KEYS` parsed out of the TypeScript source."""
    src = API_TS.read_text()
    m = re.search(
        r"export const AUTOMATION_REQUIRED_KEYS:\s*Record<string,\s*string\[\]>\s*=\s*\{(.*?)\n\};",
        src, re.S)
    assert m, "AUTOMATION_REQUIRED_KEYS not found in web/lib/api.ts — the guard is reading nothing"
    body = m.group(1)
    out: dict[str, list[str]] = {}
    for kind, arr in re.findall(r"(\w+)\s*:\s*(\[[^\]]*\])", body):
        out[kind] = json.loads(arr.replace("'", '"'))
    return out


def test_the_guard_actually_parsed_something():
    """Vacuous-pass guard. A regex that stops matching returns {}, every comparison below
    iterates nothing, and the test reports green while the mirror is unchecked."""
    client = _client_map()
    assert len(client) >= 8, f"parsed only {len(client)} kinds out of api.ts: {client}"


@pytest.mark.parametrize("kind", sorted(_CONDITION_REQUIRED))
def test_every_condition_kind_is_mirrored(kind):
    client = _client_map()
    assert kind in client, f"condition '{kind}' is required by the model and absent from the client map"
    assert client[kind] == list(_CONDITION_REQUIRED[kind]), (
        f"condition '{kind}': client requires {client[kind]}, "
        f"the model requires {list(_CONDITION_REQUIRED[kind])}"
    )


def test_every_effect_kind_the_client_declares_matches_the_model():
    client = _client_map()
    for kind, keys in client.items():
        if kind in _CONDITION_REQUIRED:
            continue
        assert kind in _EFFECT_REQUIRED, (
            f"the client declares effect '{kind}', which the model does not accept at all"
        )
        assert keys == list(_EFFECT_REQUIRED[kind]), (
            f"effect '{kind}': client requires {keys}, "
            f"the model requires {list(_EFFECT_REQUIRED[kind])}"
        )


def test_every_kind_the_client_OFFERS_can_be_validated():
    """The dropdown and the map must agree.

    A kind offered in `EFFECT_KINDS` with no entry in the required-key map is a step a
    user can author and the surface can never call incomplete — it would sail past Save
    and fail at the server. This is the pairing that actually breaks when someone widens
    the dropdown, which is the likely next change here.
    """
    rows = (Path(__file__).resolve().parents[2] / "web" / "components" / "automations"
            / "AutomationRows.tsx").read_text()
    offered = set(re.findall(r'\{\s*value:\s*"(\w+)"', rows))
    assert offered, "no kinds parsed out of AutomationRows.tsx — the guard is reading nothing"
    client = _client_map()
    missing = sorted(k for k in offered if k not in client)
    assert not missing, f"offered in the UI but not validated by the client map: {missing}"
