"""Generate ``aughor/connectors/catalog.json`` and ``web/lib/connectors.gen.ts`` from the
engine declarations — DE-3b (ROADMAP §3.51): each engine declared once, every copy generated.

A tool (or coding agent) deciding whether it can connect a data source should not have
to import this package, boot the API, or read Python to find out what a connector needs.
The committed JSON carries every connector type, its config fields with secrets flagged,
the driver modules it imports, the pip extra that makes it runnable, any environment
variable it honours in place of a field — and, since DE-3b, the engine's dialect, whether
it runs SQL as written, its bind style, support tier and metadata strategy. The web map
carries what the five hand-kept maps used to: label, blurb, badge, brand colour, the
editor's dialect family, the form fields.

``aughor/connectors/declarations.py`` is the single authority — this script derives both
files from it, and ``tests/unit/test_connector_catalog.py`` / ``test_de3b_one_declaration.py``
fail whenever a declaration moves without a regeneration. The live counterpart is
``GET /connectors/types``, which adds per-install driver availability.

Usage:
    uv run python scripts/gen_connector_catalog.py           # rewrite both files
    uv run python scripts/gen_connector_catalog.py --check   # exit 1 on drift
"""
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "aughor" / "connectors" / "catalog.json"
WEB_GEN = REPO / "web" / "lib" / "connectors.gen.ts"

# Import THIS tree's declarations, not whichever tree an editable install points at — a
# worktree running this script would otherwise generate the main checkout's catalog.
sys.path.insert(0, str(REPO))
from aughor.connectors.declarations import ENGINES, EngineDeclaration  # noqa: E402
from aughor.connectors.registry import PROVIDED_BY  # noqa: E402


def _dependency_home(dist: str, pyproject: dict) -> str:
    """``"base"`` if the distribution is pinned in ``[project.dependencies]``, else the
    name of the extra that pins it. A distribution pinned nowhere is a generation error,
    not a catalog entry — the catalog must not claim an install path that does not exist.
    """
    def _pins(entries: list[str]) -> bool:
        for entry in entries:
            name = re.split(r"[\[><=~!;\s]", entry, maxsplit=1)[0]
            if name.casefold() == dist.casefold():
                return True
        return False

    if _pins(pyproject["project"]["dependencies"]):
        return "base"
    for extra, entries in pyproject["project"].get("optional-dependencies", {}).items():
        if _pins(entries):
            return extra
    raise SystemExit(
        f"{dist!r} is pinned in no dependency list — fix pyproject.toml or PROVIDED_BY "
        f"before generating the catalog"
    )


def build(engines: tuple[EngineDeclaration, ...] = ENGINES) -> dict:
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    entries = []
    for e in sorted(engines, key=lambda d: d.type):
        fields = [f.as_dict() for f in e.fields]
        drivers = list(e.drivers)
        extras = sorted({
            home
            for module in drivers
            if (home := _dependency_home(PROVIDED_BY[module], pyproject)) != "base"
        })
        # No connector currently spans two extras; the `install` field is a single
        # string, so a type that starts needing several must change the format here.
        assert len(extras) <= 1, f"{e.type} spans extras {extras} — widen `install`"
        entry = {
            "type": e.type,
            "label": e.label,
            "category": e.category,
            "blurb": e.blurb,
            "badge": e.badge,
            "support_tier": e.support_tier,
            "dsn_preview": e.dsn_preview or e.type,
            "fields": fields,
            "secret_fields": [f["key"] for f in fields if f.get("secret")],
            "drivers": drivers,
            "install": extras[0] if extras else "base",
            "connector": e.connector,
            "dialect": e.dialect,
            "native_sql": e.native_sql,
            "param_style": e.param_style,
            "engine_read_only": e.engine_read_only,
            "metadata_strategy": e.metadata_strategy,
            "refuses": {"functions": sorted(e.refuses_functions), "features": sorted(e.refuses_features)},
            "brand_color": e.brand_color,
            "engine_family": e.engine_family,
            # DE-3c: the coverage row — what a metadata read answers for each fact, and why.
            "metadata": dict(e.metadata_facts),
            "metadata_detail": e.metadata_detail,
        }
        if e.env_vars:
            entry["env"] = [dict(v) for v in e.env_vars]
        entries.append(entry)
    return {
        "version": 2,
        "generated_by": "scripts/gen_connector_catalog.py",
        "source": "aughor/connectors/declarations.py",
        "notes": {
            "secrets": (
                "Treat every key in `secret_fields` as a credential: never place it in "
                "a URL, a query string, or a log line. Aughor stores the `dsn` in its "
                "own Fernet-encrypted column and encrypts the other secret-flagged "
                "values in the connection registry."
            ),
            "install": (
                "`base` means the standard install already carries the driver; any "
                "other value is a pip extra — e.g. `pip install 'aughor[warehouse]'`."
            ),
            "env": (
                "`env` lists environment variables honoured in place of a form field; "
                "`fallback_for` names that field."
            ),
            "knowledge": (
                "`knowledge` connectors index documents for synthesis context; they "
                "are not SQL connectors and take no queries (`connector` and `dialect` are null)."
            ),
            "sql": (
                "`dialect` is the sqlglot dialect the engine reads. `native_sql` true means "
                "SQL runs as written; false means the DuckDB the writer authors is transpiled. "
                "`param_style` is the driver's bind style, null when the connector refuses to "
                "bind. `refuses` lists constructs that error on the engine. `support_tier` is "
                "core, supported or preview."
            ),
            "live": (
                "GET /connectors/types on a running API returns the same fields plus "
                "per-install driver availability."
            ),
        },
        "types": entries,
    }


def render_web(engines: tuple[EngineDeclaration, ...] = ENGINES) -> str:
    """The TypeScript module the web's maps import — one object per engine."""
    rows = []
    for e in sorted(engines, key=lambda d: d.type):
        obj = {
            "type": e.type, "label": e.label, "category": e.category, "blurb": e.blurb,
            "badge": e.badge, "supportTier": e.support_tier, "dsnPreview": e.dsn_preview or e.type,
            "fields": [{"key": f.key, "label": f.label, "placeholder": f.placeholder, "secret": f.secret,
                        "optional": f.optional} for f in e.fields],
            "secretFields": e.secret_fields, "brandColor": e.brand_color, "engineFamily": e.engine_family,
            "dialect": e.dialect, "nativeSql": e.native_sql, "metadataStrategy": e.metadata_strategy,
            "metadata": dict(e.metadata_facts),
        }
        rows.append(f"  {json.dumps(e.type)}: {json.dumps(obj, ensure_ascii=False)},")
    body = "\n".join(rows)
    return f"""// GENERATED by scripts/gen_connector_catalog.py from aughor/connectors/declarations.py — DO NOT EDIT.
// DE-3b (ROADMAP §3.51): each engine is declared once, and this is the web's copy of that
// declaration. Regenerate: uv run python scripts/gen_connector_catalog.py

export interface ConnectorField {{
  key: string;
  label: string;
  placeholder: string;
  secret: boolean;
  optional: boolean;
}}

export interface ConnectorDeclaration {{
  type: string;
  label: string;
  category: "built-in" | "file" | "warehouse" | "api" | "federation" | "knowledge";
  blurb: string;
  badge: string | null;
  supportTier: "core" | "supported" | "preview";
  dsnPreview: string;
  fields: ConnectorField[];
  secretFields: string[];
  brandColor: string;
  engineFamily: "postgres" | "mysql" | "sqlite" | "bigquery" | "snowflake" | "standard";
  dialect: string | null;
  nativeSql: boolean;
  metadataStrategy: string;
  /** DE-3c: for columns, primary_keys, foreign_keys and comments — supported, unsupported or unknown. */
  metadata: Record<"columns" | "primary_keys" | "foreign_keys" | "comments", "supported" | "unsupported" | "unknown">;
}}

export const CONNECTORS: Record<string, ConnectorDeclaration> = {{
{body}
}};

export const CONNECTOR_TYPES: string[] = Object.keys(CONNECTORS);
"""


def main() -> int:
    catalog_text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    web_text = render_web()
    if "--check" in sys.argv[1:]:
        stale = []
        if (CATALOG.read_text() if CATALOG.exists() else "") != catalog_text:
            stale.append(str(CATALOG.relative_to(REPO)))
        if (WEB_GEN.read_text() if WEB_GEN.exists() else "") != web_text:
            stale.append(str(WEB_GEN.relative_to(REPO)))
        if stale:
            print(f"stale: {', '.join(stale)} — regenerate: uv run python scripts/gen_connector_catalog.py")
            return 1
        print("catalog.json and connectors.gen.ts are current")
        return 0
    CATALOG.write_text(catalog_text)
    WEB_GEN.write_text(web_text)
    print(f"wrote {CATALOG.relative_to(REPO)} and {WEB_GEN.relative_to(REPO)} ({len(build()['types'])} types)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
