"""Connector registry — maps type strings to connector classes.

Usage:
    from aughor.connectors.registry import build_connector, REGISTRY

    conn = build_connector("bigquery", dsn="bigquery://my-project",
                           schema_name="analytics", connection_id="abc123")
    conn.test()

Adding a new connector:
    1.  Create aughor/connectors/<category>/<name>.py with a class extending Connector.
    2.  Register it here in _register_defaults().

All registrations are lazy-import — the module is only loaded when that
connector type is first requested.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aughor.connectors.base import Connector

# ── DSN preview strings shown in the UI (no credentials) ─────────────────────

DSN_PREVIEWS: dict[str, str] = {
    "duckdb":       "*.duckdb",
    "sqlite":       "*.sqlite / *.db",
    "postgres":     "postgresql://***",
    "bigquery":     "bigquery://project-id",
    "snowflake":    "snowflake://account.region",
    "mysql":        "mysql://host:3306/db",
    "motherduck":   "md:my_database",
    "exasol":       "exa://host:8563",
    "gsheets":      "gsheet://spreadsheet-id",
    "local_upload": "local://uploads/",
    "s3":           "s3://bucket/prefix",
    "federated":    "federated://",
    "stripe":       "stripe://",
    "hubspot":      "hubspot://",
    "salesforce":   "salesforce://",
    "confluence":   "https://org.atlassian.net",
    "notion":       "notion://",
}

# ── Form field descriptors (used by the frontend to build connection forms) ───
# Each entry: [{"key": ..., "label": ..., "placeholder": ..., "secret": bool}]


def secret_field_keys(conn_type: str) -> set[str]:
    """Form field keys marked secret for a connector, EXCLUDING `dsn` (the DSN is
    stored in its own Fernet-encrypted column). These are the secret values that
    otherwise land in `meta` plaintext — the connection registry encrypts them."""
    return {f["key"] for f in FORM_FIELDS.get(conn_type, [])
            if f.get("secret") and f["key"] != "dsn"}


FORM_FIELDS: dict[str, list[dict]] = {
    "duckdb": [
        {"key": "dsn", "label": "File path", "placeholder": "/path/to/file.duckdb", "secret": False},
        {"key": "schema_name", "label": "Schema (optional)", "placeholder": "main", "secret": False},
    ],
    "sqlite": [
        {"key": "dsn", "label": "File path", "placeholder": "/path/to/file.sqlite", "secret": False},
    ],
    "postgres": [
        {"key": "dsn", "label": "Connection string", "placeholder": "postgresql://user:pass@host:5432/db", "secret": True},
        {"key": "schema_name", "label": "Schema", "placeholder": "public", "secret": False},
    ],
    "bigquery": [
        {"key": "project_id",   "label": "Project ID",           "placeholder": "my-gcp-project",       "secret": False},
        {"key": "dataset",      "label": "Dataset",              "placeholder": "analytics",             "secret": False},
        {"key": "credentials",  "label": "Service account JSON path (or blank for ADC)",
                                "placeholder": "/path/to/sa.json",                                         "secret": True},
    ],
    "snowflake": [
        {"key": "account",    "label": "Account identifier",   "placeholder": "xy12345.us-east-1",     "secret": False},
        {"key": "user",       "label": "Username",             "placeholder": "analyst",                "secret": False},
        {"key": "password",   "label": "Password",             "placeholder": "",                       "secret": True},
        {"key": "database",   "label": "Database",             "placeholder": "PROD",                   "secret": False},
        {"key": "schema_name","label": "Schema",               "placeholder": "PUBLIC",                 "secret": False},
        {"key": "warehouse",  "label": "Warehouse",            "placeholder": "COMPUTE_WH",             "secret": False},
    ],
    "mysql": [
        {"key": "host",        "label": "Host",     "placeholder": "localhost",  "secret": False},
        {"key": "port",        "label": "Port",     "placeholder": "3306",       "secret": False},
        {"key": "user",        "label": "Username", "placeholder": "root",       "secret": False},
        {"key": "password",    "label": "Password", "placeholder": "",           "secret": True},
        {"key": "database",    "label": "Database", "placeholder": "mydb",       "secret": False},
    ],
    "motherduck": [
        {"key": "token",       "label": "MotherDuck token", "placeholder": "eyJhbGc… (or set MOTHERDUCK_TOKEN)", "secret": True},
        {"key": "database",    "label": "Database",         "placeholder": "my_database",                         "secret": False},
        {"key": "schema_name", "label": "Schema",           "placeholder": "main",                                "secret": False},
    ],
    "exasol": [
        {"key": "host",        "label": "Host:Port",        "placeholder": "demodb.exasol.com:8563", "secret": False},
        {"key": "user",        "label": "Username",         "placeholder": "sys",                    "secret": False},
        {"key": "password",    "label": "Password",         "placeholder": "",                       "secret": True},
        {"key": "schema_name", "label": "Schema",           "placeholder": "RETAIL",                 "secret": False},
    ],
    "gsheets": [
        {"key": "spreadsheet_id", "label": "Spreadsheet ID or URL", "placeholder": "https://docs.google.com/spreadsheets/d/…", "secret": False},
        {"key": "sheets",         "label": "Sheet/tab names",       "placeholder": "Sheet1,Sheet2 (empty = first sheet)",      "secret": False},
        # The sheet must be shared "Anyone with the link can view" — read via the
        # public CSV export. No API key field: a key alone cannot unlock a private
        # sheet (that needs OAuth), so offering one would over-promise.
    ],
    "local_upload": [
        # No config fields — file upload is handled separately via POST /connections/{id}/files
    ],
    "federated": [
        # No config fields — members selected via POST /connections/federate
    ],
    "confluence": [
        {"key": "base_url",    "label": "Base URL",      "placeholder": "https://yourorg.atlassian.net", "secret": False},
        {"key": "username",    "label": "Username",      "placeholder": "user@example.com",              "secret": False},
        {"key": "api_token",   "label": "API token",     "placeholder": "ATATT3…",                       "secret": True},
        {"key": "space_keys",  "label": "Space keys",    "placeholder": "ENG,PROD (empty = all)",        "secret": False},
    ],
    "notion": [
        {"key": "integration_token", "label": "Integration token", "placeholder": "secret_…",  "secret": True},
        {"key": "database_ids",      "label": "Database IDs",      "placeholder": "id1,id2 (optional)", "secret": False},
    ],
    "stripe": [
        {"key": "secret_key",  "label": "Secret key",      "placeholder": "sk_live_…",  "secret": True},
        {"key": "objects",     "label": "Objects to sync (optional)", "placeholder": "charges,customers,subscriptions,invoices", "secret": False},
    ],
    "hubspot": [
        {"key": "access_token","label": "Access token",    "placeholder": "pat-na1-…",   "secret": True},
        {"key": "objects",     "label": "Objects to sync (optional)", "placeholder": "contacts,companies,deals,tickets", "secret": False},
    ],
    "salesforce": [
        {"key": "username",        "label": "Username",        "placeholder": "user@org.com",   "secret": False},
        {"key": "password",        "label": "Password",        "placeholder": "",               "secret": True},
        {"key": "security_token",  "label": "Security token",  "placeholder": "token123…",      "secret": True},
        {"key": "domain",          "label": "Domain",          "placeholder": "login (or test)", "secret": False},
        {"key": "objects",         "label": "Objects to sync (optional)", "placeholder": "Account,Contact,Opportunity,Lead,Case", "secret": False},
    ],
    "s3": [
        {"key": "bucket",     "label": "Bucket",             "placeholder": "my-data-bucket",   "secret": False},
        {"key": "prefix",     "label": "Key prefix",         "placeholder": "data/sales/",      "secret": False},
        {"key": "region",     "label": "Region",             "placeholder": "us-east-1",        "secret": False},
        {"key": "key_id",     "label": "Access Key ID",      "placeholder": "AKIA…",            "secret": True},
        {"key": "secret",     "label": "Secret Access Key",  "placeholder": "",                 "secret": True},
    ],
}


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
    """Register all built-in connectors. Called once at module import."""
    # Warehouse
    REGISTRY.register("bigquery",     "aughor.connectors.warehouse.bigquery",  "BigQueryConnection")
    REGISTRY.register("snowflake",    "aughor.connectors.warehouse.snowflake", "SnowflakeConnection")
    REGISTRY.register("mysql",        "aughor.connectors.warehouse.mysql",     "MySQLConnection")
    REGISTRY.register("motherduck",   "aughor.connectors.warehouse.motherduck", "MotherDuckConnection")
    REGISTRY.register("exasol",       "aughor.connectors.warehouse.exasol",    "ExasolConnection")
    # File
    REGISTRY.register("local_upload", "aughor.connectors.file.local_upload",   "LocalUploadConnection")
    REGISTRY.register("s3",           "aughor.connectors.file.s3",             "S3Connection")
    REGISTRY.register("sqlite",       "aughor.connectors.file.sqlite",         "SQLiteConnection")
    # Federation
    REGISTRY.register("federated",    "aughor.connectors.federated",           "FederatedConnection")
    # API/CRM
    REGISTRY.register("stripe",       "aughor.connectors.api.stripe",          "StripeConnector")
    REGISTRY.register("hubspot",      "aughor.connectors.api.hubspot",         "HubSpotConnector")
    REGISTRY.register("salesforce",   "aughor.connectors.api.salesforce",      "SalesforceConnector")
    REGISTRY.register("gsheets",      "aughor.connectors.api.gsheets",         "GoogleSheetsConnector")
    # Knowledge (stored in registry for config/auth; sync handled separately)
    # These types are not DB connectors — open_connection() is not called on them


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
