"""Connector registry — maps type strings to connector classes.

Usage:
    from aughor.connectors.registry import build_connector, REGISTRY

    conn = build_connector("bigquery", dsn="bigquery://my-project",
                           schema_name="analytics", connection_id="abc123")
    conn.test()

Adding a new connector (DE-3b, ROADMAP §3.51):
    1.  Declare it ONCE in aughor/connectors/declarations.py — identity, fields and which
        are secret, drivers, dialect, native or transpiled, bind style, writer rules, refused
        constructs, support tier, metadata strategy, the picker's label and colour.
    2.  Create aughor/connectors/<category>/<name>.py with the class the declaration names.
    3.  Regenerate the catalog and the web map: uv run python scripts/gen_connector_catalog.py

Every table this module exports — DSN previews, form fields, drivers, categories, environment
variables, the registrations themselves — is DERIVED from the declarations. They used to be six
parallel dicts kept by hand, and a seventeenth file for every engine. All registrations are
lazy-import — the module is only loaded when that connector type is first requested.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aughor.connectors.declarations import ENGINES, derive_registry_tables

if TYPE_CHECKING:
    from aughor.connectors.base import Connector

_TABLES = derive_registry_tables(ENGINES)

# ── DSN preview strings shown in the UI (no credentials) ─────────────────────
DSN_PREVIEWS: dict[str, str] = _TABLES["DSN_PREVIEWS"]

# ── Form field descriptors (used by the frontend to build connection forms) ───
# Each entry: [{"key": ..., "label": ..., "placeholder": ..., "secret": bool, "optional"?: True}]
FORM_FIELDS: dict[str, list[dict]] = _TABLES["FORM_FIELDS"]


def secret_field_keys(conn_type: str) -> set[str]:
    """Form field keys marked secret for a connector, EXCLUDING `dsn` (the DSN is
    stored in its own Fernet-encrypted column). These are the secret values that
    otherwise land in `meta` plaintext — the connection registry encrypts them."""
    return {f["key"] for f in FORM_FIELDS.get(conn_type, [])
            if f.get("secret") and f["key"] != "dsn"}


# ── Driver requirements, so a type can say whether it can actually run ───────
#
# Every connector defers its driver import to `connect()` (or, for the REST ones, to
# module import), which is right for startup cost and wrong for the UI: the picker
# offered fifteen tiles and only found out which ones work when a user filled a form
# in and it raised ImportError. The base install carries `duckdb` and `psycopg2`;
# the rest live in the `warehouse` and `crm` extras, and Vercel installs base
# dependencies only — so on the deployment most of this list is absent.
#
# Names are the module actually imported at the call site, not the distribution that
# provides it, because that is what determines whether the import succeeds. Two of them
# used to correspond to nothing this project declared, and recording them here made the
# picker tell the truth about that without fixing it: `pyexasol` was declared in NO extra
# (now pinned in `[warehouse]`), and `requests` — imported at MODULE level by the REST
# connectors — resolved only transitively (now declared by `[crm]`).
#
# `tests/unit/test_connector_dependencies.py` asserts this list against pyproject in both
# directions, so a driver added to a declaration without a pin — or a pin nothing imports —
# fails there rather than in someone's connection form.
DRIVERS: dict[str, tuple[str, ...]] = _TABLES["DRIVERS"]


#: Import module → the distribution that provides it. Hand-maintained on purpose: reading
#: it from the environment would only describe THIS machine's install, and the defect
#: `tests/unit/test_connector_dependencies.py` guards with it is precisely a module that
#: no install provides. The connector catalog generator uses the same map to say which
#: pip extra makes a connector runnable.
PROVIDED_BY: dict[str, str] = {
    "duckdb": "duckdb",
    "psycopg2": "psycopg2-binary",
    "google.cloud.bigquery": "google-cloud-bigquery",
    "snowflake.connector": "snowflake-connector-python",
    "pymysql": "PyMySQL",
    "pyexasol": "pyexasol",
    "trino": "trino",
    "ibis": "ibis-framework",
    "connectorx": "connectorx",
    "requests": "requests",
}


#: Connector type → picker category. `routers/system.py` paints the picker from this and
#: the catalog generator groups by it; both read the declaration, so they cannot disagree.
CATEGORIES: dict[str, str] = _TABLES["CATEGORIES"]


#: Environment variables a connector honours as an alternative to a form field. Only
#: code-verified entries belong on a declaration: `motherduck.py` reads MOTHERDUCK_TOKEN when
#: the token field is empty; BigQuery's client library resolves Application Default
#: Credentials (GOOGLE_APPLICATION_CREDENTIALS among them) when the credentials field is
#: blank — that resolution happens in google-auth, not in Aughor.
ENV_VARS: dict[str, list[dict]] = _TABLES["ENV_VARS"]


def missing_drivers(conn_type: str) -> list[str]:
    """Module names this connector imports that are not installed here.

    Uses `find_spec` rather than `import_module`: this is called to PAINT a picker,
    so it must not execute connector code or pay an import cost for fifteen types on
    every request. An unknown type reports nothing missing — it is not this
    function's job to decide a type is unknown, and claiming a driver gap for one
    would be a second wrong answer on top of the first.
    """
    import importlib.util

    out: list[str] = []
    for mod in DRIVERS.get(conn_type, ()):
        try:
            if importlib.util.find_spec(mod) is None:
                out.append(mod)
        except (ImportError, ValueError):
            # A missing PARENT package raises rather than returning None, and a
            # namespace package with no __spec__ raises ValueError. Both mean the
            # same thing to a caller: the import at the call site would fail.
            out.append(mod)
    return out


class ConnectorRegistry:
    """Lazy registry: type_string → connector class."""

    def __init__(self) -> None:
        self._builders: dict[str, str] = {}  # type_str → "module:ClassName"

    def register(self, conn_type: str, module_path: str, class_name: str) -> None:
        self._builders[conn_type] = f"{module_path}:{class_name}"

    def get_class(self, conn_type: str):  # type: ignore[return]
        if conn_type not in self._builders:
            return None
        spec = self._builders[conn_type]
        module_path, class_name = spec.rsplit(":", 1)
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)

    def supported_types(self) -> list[str]:
        return list(self._builders.keys())


REGISTRY = ConnectorRegistry()


def _register_defaults() -> None:
    """Register every declared connector. Called once at module import.

    The knowledge types (Confluence, Notion) declare no connector: they are stored in the
    registry for config/auth and synced separately — not DB connectors, `open_connection()`
    is never called on them — so they are categorised and never registered here.
    """
    for conn_type, spec in _TABLES["REGISTRATIONS"].items():
        module_path, class_name = spec.rsplit(":", 1)
        REGISTRY.register(conn_type, module_path, class_name)


_register_defaults()


def build_connector(
    conn_type: str,
    dsn: str,
    schema_name: str | None = None,
    connection_id: str = "",
    meta: dict | None = None,
) -> "Connector":
    """Instantiate a registered connector by type string.

    Raises:
        ValueError   — unknown conn_type
        ImportError  — optional dep not installed
    """
    cls = REGISTRY.get_class(conn_type)
    if cls is None:
        raise ValueError(
            f"Unknown connector type {conn_type!r}. "
            f"Registered types: {REGISTRY.supported_types()}"
        )
    return cls(dsn=dsn, schema_name=schema_name, connection_id=connection_id, meta=meta or {})
