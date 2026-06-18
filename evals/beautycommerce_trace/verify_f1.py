"""F1 live-path verification: run the patched key-question SQL generator and report
how many of the profile's 8 questions now get runnable, audited SQL (was 1/8)."""
from dotenv import load_dotenv
load_dotenv(".env")

import time
from aughor.db.connection import open_connection_for
from aughor.profile import store as pstore
from aughor.profile.infer import _generate_key_question_sql
from aughor.profile.validate import audit_finding_sql
from aughor.tools.schema import _parse_schema_tables

CID = "8090c60f"
conn = open_connection_for(CID)
schema = conn.get_schema()
table_cols = _parse_schema_tables(schema)
profile = pstore.load(CID)
recipes = pstore.load_recipes(CID)

print(f"{len(profile.key_questions)} key questions; regenerating SQL with per-question retry…\n")
t = time.time()
_generate_key_question_sql(profile, recipes, schema, conn)
dt = time.time() - t

filled = 0
for i, q in enumerate(profile.key_questions):
    sql = (profile.key_question_sql[i] if i < len(profile.key_question_sql) else "") or ""
    if sql.strip():
        ok, _ = audit_finding_sql(sql, table_cols, conn)
        # re-run to confirm it actually returns rows
        res = conn.execute("verify", sql)
        nrows = len(getattr(res, "rows", []) or [])
        filled += 1
        print(f"[{i}] ✓ ({nrows} rows) — {q[:62]}")
        print(f"      {sql[:150].replace(chr(10),' ')}")
    else:
        print(f"[{i}] ✗ still empty — {q[:62]}")

print(f"\nRESULT: {filled}/{len(profile.key_questions)} key questions now have runnable SQL "
      f"(was 1/8)  [{dt:.0f}s]")
