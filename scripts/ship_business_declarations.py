#!/usr/bin/env python3
"""PENDING item 14 — write the Olist and LuxExperience business declarations into the SHIPPED
overrides tree, filed under each host's scope key, so a fresh clone carries them.

The declarations behind §3.15's receipts (1 process and 2 rules on Olist; 2 processes, 7 rules and
an action on LuxExperience) lived only on the builder's machine, in untracked override files keyed
by that machine's random connection ids. Their measured, served form IS tracked — the two eval
snapshots below, saved from `GET /ontology` — so the declarations are re-materialised from them
with the same field and binding helpers the declare doors use, each file carrying the measurement
it was served with. Deterministic: a fixed timestamp, so a re-run writes the same bytes.

Usage: .venv/bin/python scripts/ship_business_declarations.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

HOSTS = {   # scope key → (tracked snapshot, the schema its declarations are filed under)
    "luxexperience": ("evals/ablation_luxexperience_business_ontology.json", "luxexperience"),
    "olist": ("evals/ablation_olist_business_ontology.json", "ecommerce"),
}
#: The measurement these snapshots were served with (ROADMAP §3.15, the 2026-09-15 re-runs).
STAMP = "2026-09-15T00:00:00+00:00"
SHIPPED = REPO / "data" / "shipped" / "ontology_overrides"


def main() -> int:
    import yaml

    from aughor.ontology.business_rules import rule_entry, rule_fields
    from aughor.ontology.models import BusinessRule, Process
    from aughor.ontology.overrides import _EDITABLE, OntologyOverride
    from aughor.ontology.processes import process_entry, process_fields

    written = 0
    for key, (snapshot, schema) in HOSTS.items():
        g = json.loads((REPO / snapshot).read_text())
        base = SHIPPED / f"key={key}" / schema
        note = f"shipped from {snapshot} (the served, measured form, {STAMP[:10]}) — PENDING item 14"
        overrides = []
        for pid, proc in sorted((g.get("processes") or {}).items()):
            fields = process_fields(proc)
            overrides.append(OntologyOverride(target_kind="process", target_id=pid, fields=fields,
                                              binding={"process": process_entry(fields, Process.model_validate(proc))},
                                              source=proc.get("origin") or "human", edited_at=STAMP, note=note))
        for rid, rule in sorted((g.get("rules") or {}).items()):
            fields = rule_fields(rule)
            entry = {**rule_entry(fields, BusinessRule.model_validate(rule)), "measured_at": STAMP}
            overrides.append(OntologyOverride(target_kind="rule", target_id=rid, fields=fields,
                                              binding={"rule": entry}, source=rule.get("origin") or "human",
                                              edited_at=STAMP, note=note))
        from aughor.ontology.models import OntologyGraph
        for action in sorted(OntologyGraph.model_validate(g).declared_actions(), key=lambda a: a.id):
            aid = action.id
            fields = {k: v for k, v in action.model_dump(mode="json").items() if k in _EDITABLE["action"]}
            overrides.append(OntologyOverride(target_kind="action", target_id=aid, fields=fields,
                                              source="human", edited_at=STAMP, note=note))
        for ov in overrides:
            path = base / ov.target_kind / f"{ov.target_id}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(ov.model_dump(), sort_keys=False, allow_unicode=True))
            written += 1
        print(f"key={key}/{schema}: {len(overrides)} declarations")
    print(f"{written} files under {SHIPPED.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
