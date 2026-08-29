"""Generate ``aughor/connectors/catalog.json`` — the machine-readable connector catalog.

A tool (or coding agent) deciding whether it can connect a data source should not have
to import this package, boot the API, or read Python to find out what a connector needs.
The committed JSON carries every connector type, its config fields with secrets flagged,
the driver modules it imports, the pip extra that makes it runnable, and any environment
variable it honours in place of a field.

The registry (``aughor/connectors/registry.py``) stays the single authority — this
script derives the catalog from it, and ``tests/unit/test_connector_catalog.py`` fails
whenever the registry moves without a regeneration. The live counterpart is
``GET /connectors/types``, which adds per-install driver availability.

Usage:
    uv run python scripts/gen_connector_catalog.py           # rewrite the catalog
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

# Import THIS tree's registry, not whichever tree an editable install points at — a
# worktree running this script would otherwise generate the main checkout's catalog.
sys.path.insert(0, str(REPO))

from aughor.connectors.registry import (  # noqa: E402
    CATEGORIES,
    DRIVERS,
    DSN_PREVIEWS,
    ENV_VARS,
    FORM_FIELDS,
    PROVIDED_BY,
    REGISTRY,
)


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


def build() -> dict:
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    types = sorted(
        set(FORM_FIELDS) | set(DSN_PREVIEWS) | set(DRIVERS) | set(REGISTRY.supported_types())
    )
    entries = []
    for conn_type in types:
        fields = FORM_FIELDS.get(conn_type, [])
        drivers = list(DRIVERS.get(conn_type, ()))
        extras = sorted({
            home
            for module in drivers
            if (home := _dependency_home(PROVIDED_BY[module], pyproject)) != "base"
        })
        # No connector currently spans two extras; the `install` field is a single
        # string, so a type that starts needing several must change the format here.
        assert len(extras) <= 1, f"{conn_type} spans extras {extras} — widen `install`"
        entry = {
            # A type without a category is a registration mistake — fail loudly (KeyError)
            # rather than shipping an uncategorised tile.
            "type": conn_type,
            "category": CATEGORIES[conn_type],
            "dsn_preview": DSN_PREVIEWS.get(conn_type, conn_type),
            "fields": fields,
            "secret_fields": [f["key"] for f in fields if f.get("secret")],
            "drivers": drivers,
            "install": extras[0] if extras else "base",
        }
        if conn_type in ENV_VARS:
            entry["env"] = ENV_VARS[conn_type]
        entries.append(entry)
    return {
        "version": 1,
        "generated_by": "scripts/gen_connector_catalog.py",
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
                "are not SQL connectors and take no queries."
            ),
            "live": (
                "GET /connectors/types on a running API returns the same fields plus "
                "per-install driver availability."
            ),
        },
        "types": entries,
    }


def main() -> int:
    text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if "--check" in sys.argv[1:]:
        current = CATALOG.read_text() if CATALOG.exists() else ""
        if current != text:
            print(
                "catalog.json is stale — regenerate: "
                "uv run python scripts/gen_connector_catalog.py"
            )
            return 1
        print("catalog.json is current")
        return 0
    CATALOG.write_text(text)
    print(f"wrote {CATALOG.relative_to(REPO)} ({len(build()['types'])} types)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
