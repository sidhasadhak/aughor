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
    # PENDING item 26, 2026-09-24: theLook had NO process and NO rule — its 2026-09-14 explorer
    # run (version 1) said only parts and links, so the connection the platform is demonstrated
    # on shipped no business term at all. Re-running the CURRENT explorer proposed a process and
    # two rules; a person confirmed the process and `completed_orders` (the third was refused —
    # Order already has a segment of that name). Each was measured on the warehouse before it
    # landed: the process reaches 4 of 4 stages over 124,778 Order objects (placed 124,778 ·
    # shipped 80,963 · delivered 43,599 · returned 12,518), and `completed_orders` admits 31,081
    # of those 124,778. The model proposed; the person declared — the file keeps both.
    "thelook": ("evals/ablation_thelook_business_ontology.json", "thelook"),
    # PENDING item 26, the half that actually closes it: the SAMPLES warehouse is the only
    # built-in one — a local DuckDB every clone has, needing no credentials and no billed scan —
    # so terms here are what let a clone reproduce the ontology's gain unaided. Explored
    # 2026-09-24 (it never had been): the user confirmed the process and `fulfilled_orders`
    # (5,000 Orders, 3 of 3 stages reached: placed 5,000 · shipped 3,600 · delivered 2,500;
    # the rule admits 3,900 of 5,000) and declined `north_america`, which `is_human` keeps out.
    "samples": ("evals/ablation_samples_business_ontology.json", "ecommerce"),
}
#: The measurement these snapshots were served with (ROADMAP §3.15, the 2026-09-15 re-runs).
STAMP = "2026-09-15T00:00:00+00:00"
#: theLook's declarations were made on 2026-09-24, not in the 2026-09-15 re-runs, so they carry
#: their own date rather than borrowing a measurement they were never served with.
STAMPS = {"thelook": "2026-09-24T00:00:00+00:00", "samples": "2026-09-24T00:00:00+00:00"}
SHIPPED = REPO / "data" / "shipped" / "ontology_overrides"


def is_human(spec: dict) -> bool:
    """Ship only what a PERSON declared — the gate, and the one definition of it.

    The served graph carries the explorer's unconfirmed proposals beside the declarations
    (`origin: model` vs `origin: human`), and this script used to take a declaration's origin as
    given — `source=rule.get("origin") or "human"` — so a proposal nobody confirmed would have
    been written into the SHIPPED tree and handed to every clone as a declaration. Found
    2026-09-24 on the samples warehouse: the explorer proposed `north_america`, the user confirmed
    the other two, and only this gate keeps the third out. A shipped declaration is a person's word
    (AGENTS.md: provenance — no model authors a fact), so an unconfirmed proposal is skipped, not
    downgraded.

    Public, and at module scope, so the clone test filters its expectation through THIS function
    rather than a second copy of the rule written beside its own assertion.
    """
    return str(spec.get("origin") or "human") == "human"


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
        stamp = STAMPS.get(key, STAMP)
        item = "PENDING item 26" if key in STAMPS else "PENDING item 14"
        note = f"shipped from {snapshot} (the served, measured form, {stamp[:10]}) — {item}"
        overrides, skipped = [], []
        for pid, proc in sorted((g.get("processes") or {}).items()):
            if not is_human(proc):
                skipped.append(f"process:{pid}")
                continue
            fields = process_fields(proc)
            overrides.append(OntologyOverride(target_kind="process", target_id=pid, fields=fields,
                                              binding={"process": process_entry(fields, Process.model_validate(proc))},
                                              source=proc.get("origin") or "human", edited_at=stamp, note=note))
        for rid, rule in sorted((g.get("rules") or {}).items()):
            if not is_human(rule):
                skipped.append(f"rule:{rid}")
                continue
            fields = rule_fields(rule)
            entry = {**rule_entry(fields, BusinessRule.model_validate(rule)), "measured_at": stamp}
            overrides.append(OntologyOverride(target_kind="rule", target_id=rid, fields=fields,
                                              binding={"rule": entry}, source=rule.get("origin") or "human",
                                              edited_at=stamp, note=note))
        from aughor.ontology.models import OntologyGraph
        for action in sorted(OntologyGraph.model_validate(g).declared_actions(), key=lambda a: a.id):
            aid = action.id
            fields = {k: v for k, v in action.model_dump(mode="json").items() if k in _EDITABLE["action"]}
            overrides.append(OntologyOverride(target_kind="action", target_id=aid, fields=fields,
                                              source="human", edited_at=stamp, note=note))
        # Prune before writing, but ONLY the kinds this script generates. It used to just ADD, so a
        # declaration that stops shipping — withdrawn by the person, or an unconfirmed proposal that
        # `is_human` now refuses — kept its file and went on being handed to every clone (proved
        # 2026-09-24: disabling the gate once wrote `rule/north_america.yaml`, and re-running with
        # the gate restored left it sitting there).
        #
        # 🔴 The kind filter is the whole safety of this. The shipped tree is NOT all ours: the
        # `entity/`, `link/` and `metric/` files under key=luxexperience were written by item 26's
        # own binding work, not by this script, and a prune that owned the whole directory deleted
        # eight TRACKED governed artifacts on its first run. Only sweep what we could have written.
        OURS = {"process", "rule", "action"}
        keep = {base / ov.target_kind / f"{ov.target_id}.yaml" for ov in overrides}
        for kind in sorted(OURS):
            for stale in sorted((base / kind).glob("*.yaml")) if (base / kind).exists() else []:
                if stale not in keep:
                    stale.unlink()
                    skipped.append(f"removed:{kind}/{stale.stem}")
        for ov in overrides:
            path = base / ov.target_kind / f"{ov.target_id}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(ov.model_dump(), sort_keys=False, allow_unicode=True))
            written += 1
        note_skip = f"  (skipped {len(skipped)} unconfirmed model proposal(s): {', '.join(skipped)})" if skipped else ""
        print(f"key={key}/{schema}: {len(overrides)} declarations{note_skip}")
    print(f"{written} files under {SHIPPED.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
