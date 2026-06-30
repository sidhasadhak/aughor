"""
Knowledge base loader — parses SQL pattern and domain knowledge JSONs into
normalised KBEntry objects ready for embedding and Qdrant indexing.

Two schema tiers are recognised automatically:
  Tier 1 — SQL patterns  (have: dialect_traps, mistake_patterns)
  Tier 2 — Domain know.  (have: business_definition, diagnostic_questions)
  Tier 3 — Stub patterns (everything else — still indexed, lower richness)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass
class KBEntry:
    pattern_id: str
    title: str
    tier: int               # 1=SQL patterns, 2=domain knowledge, 3=stub
    source_file: str
    embed_text: str         # rich text sent to the embedder
    payload: dict           # stored in Qdrant, returned at retrieval time


def _join(items, sep=". ") -> str:
    if isinstance(items, list):
        return sep.join(str(i) for i in items if i)
    return str(items) if items else ""


def _build_embed_text(entry: dict, tier: int) -> str:
    parts = [entry.get("title", "")]
    tags = entry.get("intent_tags", [])
    if tags:
        parts.append("Use for: " + ", ".join(tags))

    when = entry.get("when_to_use", [])
    if when:
        parts.append(_join(when))

    if tier == 1:
        ce = entry.get("concept_explanation", {})
        if isinstance(ce, dict):
            parts.append(ce.get("what_it_does", ""))
            parts.append(ce.get("mental_model", ""))
        for dt in entry.get("dialect_traps", []):
            parts.append(dt.get("construct", ""))
        for mp in entry.get("mistake_patterns", []):
            parts.append(mp.get("mistake", ""))
            parts.append(mp.get("symptom", ""))

    elif tier == 2:
        parts.append(entry.get("business_definition", ""))
        mn = entry.get("metric_nature", {})
        if isinstance(mn, dict):
            parts.append(mn.get("what_it_measures", ""))
            parts.append(mn.get("common_misconception", ""))
        parts.append(_join(entry.get("diagnostic_questions", [])))
        # causal_relationships: two shapes supported
        #   {symptom, check_in_order, detection_sql}  — Aughor native
        #   {if, then}                                 — talonsight shape
        for cr in entry.get("causal_relationships", []):
            if isinstance(cr, dict):
                parts.append(cr.get("symptom", "") or cr.get("if", ""))
                parts.append(_join(cr.get("check_in_order", [])) or cr.get("then", ""))
            else:
                parts.append(str(cr))
        for ic in entry.get("inflation_causes", []):
            if isinstance(ic, dict):
                parts.append(ic.get("cause", ""))
                parts.append(ic.get("how_it_inflates", ""))
            else:
                parts.append(str(ic))
        for dc in entry.get("deflation_causes", []):
            if isinstance(dc, dict):
                parts.append(dc.get("cause", ""))
                parts.append(dc.get("how_it_deflates", ""))
            else:
                parts.append(str(dc))
        for cs in entry.get("cross_metric_signals", []):
            if isinstance(cs, dict):
                parts.append(cs.get("if", "") + " " + cs.get("then", ""))
            else:
                parts.append(str(cs))
        parts.append(_join(entry.get("related_patterns", [])))

    else:
        notes = entry.get("notes", "") or entry.get("dialect_notes", "")
        if notes:
            parts.append(str(notes))
        for ap in entry.get("anti_patterns", []):
            parts.append(str(ap))

    return " | ".join(p for p in parts if p and str(p).strip())


def _build_payload(entry: dict, tier: int, source_file: str) -> dict:
    payload: dict = {
        "pattern_id": entry.get("id", ""),
        "title": entry.get("title", ""),
        "tier": tier,
        "source_file": source_file,
        "intent_tags": entry.get("intent_tags", []),
        "when_to_use": entry.get("when_to_use", []),
        "difficulty": entry.get("difficulty", ""),
        "pattern_type": entry.get("pattern_type", ""),
    }

    # Template — normalise to a string
    tmpl = entry.get("template", "")
    if isinstance(tmpl, dict):
        payload["template"] = tmpl.get("minimal") or tmpl.get("realistic") or next(iter(tmpl.values()), "")
    else:
        payload["template"] = tmpl or ""

    if tier == 1:
        payload["dialect_traps"] = entry.get("dialect_traps", [])
        payload["mistake_patterns"] = [
            {
                "mistake": mp.get("mistake", ""),
                "symptom": mp.get("symptom", ""),
                "good_sql": mp.get("good_sql", ""),
                "bad_sql": mp.get("bad_sql", ""),
            }
            for mp in entry.get("mistake_patterns", [])
        ]
        ce = entry.get("concept_explanation", {})
        payload["what_it_does"] = ce.get("what_it_does", "") if isinstance(ce, dict) else ""

    elif tier == 2:
        payload["business_definition"] = entry.get("business_definition", "")
        payload["metric_nature"] = entry.get("metric_nature", {})
        payload["diagnostic_questions"] = entry.get("diagnostic_questions", [])
        payload["causal_relationships"] = entry.get("causal_relationships", [])
        payload["inflation_causes"] = entry.get("inflation_causes", [])
        payload["deflation_causes"] = entry.get("deflation_causes", [])
        payload["cross_metric_signals"] = entry.get("cross_metric_signals", [])
        payload["related_patterns"] = entry.get("related_patterns", [])
        payload["anti_patterns"] = entry.get("anti_patterns", [])
        sql_assets = entry.get("sql_assets", {})
        if isinstance(sql_assets, dict):
            payload["sql_example"] = next(iter(sql_assets.values()), "")
        else:
            payload["sql_example"] = ""

    else:
        payload["anti_patterns"] = entry.get("anti_patterns", [])
        payload["notes"] = entry.get("notes", "") or entry.get("dialect_notes", "")

    return payload


def _detect_tier(entry: dict) -> int:
    keys = set(entry.keys())
    if "dialect_traps" in keys:
        return 1
    if "business_definition" in keys:
        return 2
    return 3


def load_kb_entries(kb_path: str) -> list[KBEntry]:
    """
    Load all JSON files in kb_path and return a flat list of KBEntry objects.
    Silently skips files that can't be parsed.
    """
    entries: list[KBEntry] = []
    if not kb_path or not os.path.isdir(kb_path):
        return entries

    for filename in sorted(os.listdir(kb_path)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(kb_path, filename)
        try:
            data = json.load(open(filepath, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue

        for raw in data:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            tier = _detect_tier(raw)
            embed_text = _build_embed_text(raw, tier)
            payload = _build_payload(raw, tier, filename)
            entries.append(KBEntry(
                pattern_id=raw["id"],
                title=raw.get("title", raw["id"]),
                tier=tier,
                source_file=filename,
                embed_text=embed_text,
                payload=payload,
            ))

    return entries
