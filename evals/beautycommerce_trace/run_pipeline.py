"""Run Aughor's REAL onboarding/intelligence pipeline on the fresh connection, live LLM.

Captures every artifact to evidence/ so the diff can measure my cold trace against what
Aughor's automated pipeline actually produces:
  1. get_schema()            → autoseed glossary + join inference (LLM per table)
  2. infer_business_profile  → BusinessProfile (industry, metrics, value_sql, key questions)
                               + recipe resolution + value_sql audit + key-question SQL gen
"""
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

EV = Path("evals/beautycommerce_trace/evidence")
EV.mkdir(parents=True, exist_ok=True)

CONN_NAME = "BeautyCommerce-Analytics"
SCHEMA = "analytics"


def conn_id():
    from aughor.db.registry import list_connections
    for c in list_connections():
        if c.get("name") == CONN_NAME:
            return c["id"]
    raise SystemExit(f"connection {CONN_NAME!r} not registered — run build/register first")


def main():
    cid = conn_id()
    print(f"connection: {cid}  schema: {SCHEMA}")

    # ── Step 1: get_schema() triggers autoseed glossary + join inference ──────────────
    from aughor.db.connection import open_connection_for
    db = open_connection_for(cid)
    t = time.time()
    enriched = db.get_schema()
    print(f"[1] get_schema + autoseed: {time.time()-t:.1f}s, {len(enriched)} chars")
    (EV / "pipeline_enriched_schema.txt").write_text(enriched)

    # dump the freshly auto-generated glossary entries for analytics.*
    import yaml
    g = yaml.safe_load(open("data/glossary.yaml"))
    fresh = {k: v for k, v in g.get("tables", {}).items() if k.startswith("analytics.")}
    yaml.safe_dump({"tables": fresh}, open(EV / "pipeline_glossary_analytics.yaml", "w"),
                   sort_keys=True, default_flow_style=False)
    print(f"    autoseed wrote {len(fresh)} analytics.* glossary entries")

    # ── Step 2: infer the Business/Industry Profile (the keystone) ────────────────────
    from aughor.profile.infer import infer_business_profile
    t = time.time()
    profile = infer_business_profile(cid, schema_name=SCHEMA)
    print(f"[2] infer_business_profile: {time.time()-t:.1f}s")

    # persist a readable dump of the profile + resolved recipes
    from aughor.profile import store as pstore
    recipes = pstore.load_recipes(cid)
    out = {
        "industry": profile.industry,
        "business_model": profile.business_model,
        "summary": profile.summary,
        "confidence": profile.confidence,
        "evidence": profile.evidence,
        "north_star_metrics": [
            {"name": m.name, "definition": m.definition, "maps_to": m.maps_to,
             "unit_or_range": m.unit_or_range, "value_sql": m.value_sql, "chart_sql": m.chart_sql,
             "why_it_matters": m.why_it_matters}
            for m in profile.north_star_metrics
        ],
        "key_questions": profile.key_questions,
        "key_question_sql": profile.key_question_sql,
        "recipes": recipes,
    }
    (EV / "pipeline_profile.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"    industry={profile.industry!r} model={profile.business_model!r} "
          f"metrics={len(profile.north_star_metrics)} questions={len(profile.key_questions)} "
          f"conf={profile.confidence}")
    print("\nWrote artifacts to", EV)


if __name__ == "__main__":
    sys.exit(main())
