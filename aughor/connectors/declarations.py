"""DE-3b (ROADMAP §3.51; §6 item 37(d)) — each engine, declared ONCE.

Before this module an engine was spread over fourteen to seventeen files: six parallel dicts in
the registry (DSN preview, form fields, drivers, categories, environment variables, the
registration itself), the writer rules in `db/dialects.py`, the refused constructs in
`db/capabilities.py`, the display name in `agent/sql_context.py`, the class's own `dialect` /
`writes_native_sql` / `param_style`, the catalog JSON, and five hand-kept maps in the web (the
picker's label and badge, the brand colour, the editor's dialect family, a second copy of the
form fields and a tag map) — two of which had drifted: the connection modal and the catalog
tags knew nothing of MotherDuck, Exasol, Google Sheets or SQLite.

Now one `EngineDeclaration` per engine holds every fact, and everything else is DERIVED from
the tuple below: the registry's tables, the writer rules, the capability rows, the prompt's
engine names, `connectors/catalog.json` and `web/lib/connectors.gen.ts` (both written by
`scripts/gen_connector_catalog.py`, both held current by a test). Each connector class reads
its `dialect`, `writes_native_sql` and `param_style` from its declaration, so the fact is
stated once and referenced, never copied. Adding an engine is one declaration here and its
connector module.

This module imports nothing from the rest of the package, so anything may import it.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, Optional

Category = Literal["built-in", "file", "warehouse", "api", "federation", "knowledge"]
Tier = Literal["core", "supported", "preview"]
MetadataStrategy = Literal[
    "information_schema",   # INFORMATION_SCHEMA.COLUMNS (or TABLES + DESCRIBE)
    "driver_api",           # the driver's own client API (BigQuery's get_table)
    "engine_catalog",       # the engine's own catalog views (Exasol's EXA_ALL_COLUMNS)
    "pragma",               # SQLite's PRAGMA table_info
    "cursor_description",   # SELECT … LIMIT 0 and the cursor's description
    "none",                 # not a SQL connector
]
EngineFamily = Literal["postgres", "mysql", "sqlite", "bigquery", "snowflake", "standard"]

#: DE-3c — what a metadata read of this engine answers for each fact. ``supported``: the
#: platform reads it (`db/metadata.py` has the recipe); ``unsupported``: the engine has no such
#: fact to read; ``unknown``: the engine may carry it and the platform does not read it yet. The
#: four facts are `columns`, `primary_keys`, `foreign_keys`, `comments`; every engine states all
#: four, and a test holds every engine to its row.
MetadataStatus = Literal["supported", "unsupported", "unknown"]
METADATA_FACTS = ("columns", "primary_keys", "foreign_keys", "comments")

#: DE-5d — what running the same statement AGAIN costs on this engine, which decides whether a cut result
#: may be paged (`routers/query.py` `/query/more`). ``local``: the engine is this process or a local file,
#: nothing is billed. ``compute``: a re-run spends the engine's time (a warehouse's credits, a server's CPU)
#: and no metered byte bill. ``bytes_scanned``: every statement reads its tables' bytes again and THAT is
#: what is billed — so each page of a result costs a full scan, where one re-run with a higher limit costs
#: one. ``unknown``: not a SQL engine, or not measured. The study's falsifier (§6): paging is wrong where it
#: costs more than re-running, so on a `bytes_scanned` engine the page is refused and the refusal says why.
RerunCost = Literal["local", "compute", "bytes_scanned", "unknown"]


def _facts(columns: MetadataStatus = "supported", primary_keys: MetadataStatus = "unknown",
           foreign_keys: MetadataStatus = "unknown", comments: MetadataStatus = "unknown") -> dict[str, MetadataStatus]:
    return {"columns": columns, "primary_keys": primary_keys, "foreign_keys": foreign_keys, "comments": comments}


_META_ALL = _facts("supported", "supported", "supported", "supported")
_META_NO_KEYS = _facts("supported", "unsupported", "unsupported", "unsupported")
_META_NOT_READ_YET = _facts("supported", "unknown", "unknown", "unknown")
_META_NONE = _facts("unsupported", "unsupported", "unsupported", "unsupported")


@dataclass(frozen=True)
class Field:
    """One connection-form field. `secret` values are encrypted at rest and never logged."""
    key: str
    label: str
    placeholder: str = ""
    secret: bool = False
    optional: bool = False

    def as_dict(self) -> dict:
        d = {"key": self.key, "label": self.label, "placeholder": self.placeholder, "secret": self.secret}
        if self.optional:
            d["optional"] = True
        return d


@dataclass(frozen=True)
class EngineDeclaration:
    type: str
    label: str
    category: Category
    blurb: str = ""
    dsn_preview: str = ""
    fields: tuple[Field, ...] = ()
    #: Import modules the connector needs (`registry.DRIVERS`); `registry.PROVIDED_BY` maps each
    #: to the distribution that provides it.
    drivers: tuple[str, ...] = ()
    #: ``"module:Class"`` of the connector; None for a knowledge type (not a SQL connector) and
    #: for the two built-ins that live in `db/connection.py`.
    connector: Optional[str] = None
    #: The sqlglot dialect the engine reads; None for a non-SQL connector.
    dialect: Optional[str] = None
    #: Runs SQL as written (True) or transpiled from the DuckDB the writer authors (False).
    native_sql: bool = False
    #: The driver's bind style (`sql/params._PLACEHOLDER`): duckdb | pyformat | named | at; None
    #: when the connector deliberately refuses to bind (a visible refusal beats a silent format).
    param_style: Optional[str] = None
    #: Whether the engine itself enforces read-only for the session; None = unknown or decided
    #: per connection at runtime (SQLite: a file is, memory is not).
    engine_read_only: Optional[bool] = None
    #: The SQL-writer's rule block for a native engine; shared by every engine of the dialect.
    writer_rules: Optional[str] = None
    #: Constructs that hard-error on this dialect (`db/capabilities.py`).
    refuses_functions: frozenset[str] = frozenset()
    refuses_features: frozenset[str] = frozenset()
    support_tier: Tier = "supported"
    metadata_strategy: MetadataStrategy = "information_schema"
    #: Environment variables honoured in place of a form field (`registry.ENV_VARS`).
    env_vars: tuple[dict, ...] = ()
    #: The accent the web tints tiles and borders with.
    brand_color: str = "#8a8a93"
    #: The editor's grammar family (`web/lib/query/dialect.ts`).
    engine_family: EngineFamily = "standard"
    #: The picker's badge, when it carries one.
    badge: Optional[str] = None
    #: The engine's name as a person writing SQL for it would say it (the prompt); the label
    #: when unset.
    sql_name: Optional[str] = None
    #: The driver's exception class names that are, on their own, a lost connection, a timeout
    #: or a cancelled statement (`db/errors.py` types a failure by them, importing no driver).
    connection_errors: tuple[str, ...] = ()
    timeout_errors: tuple[str, ...] = ()
    cancelled_errors: tuple[str, ...] = ()
    #: DE-3c — the coverage row: what a metadata read answers for columns, primary keys,
    #: foreign keys and comments, and why where it is not `supported`.
    metadata_facts: dict[str, MetadataStatus] = field(default_factory=lambda: dict(_META_NOT_READ_YET))
    metadata_detail: str = ""
    #: DE-5d — what a re-run of the same statement costs here (`RerunCost`); decides whether a cut
    #: result may be paged.
    rerun_cost: RerunCost = "unknown"

    @property
    def secret_fields(self) -> list[str]:
        return [f.key for f in self.fields if f.secret]

    @property
    def registered(self) -> bool:
        """Registered as a SQL connector type (the knowledge types are categorised, not registered)."""
        return self.connector is not None


# ── the writer's rule blocks (native engines; Postgres keeps one for rules_for_dialect) ──

_BIGQUERY_RULES = """
BIGQUERY (GoogleSQL) DIALECT RULES (violations cause query errors):
- Date bucketing: DATE_TRUNC(date_col, MONTH) or TIMESTAMP_TRUNC(ts, MONTH) / DATETIME_TRUNC(dt, MONTH). The grain (DAY/WEEK/MONTH/QUARTER/YEAR) is an UNQUOTED keyword, and the column is the FIRST arg — NOT date_trunc('month', col).
- Date differences: DATE_DIFF(d1, d2, DAY) / TIMESTAMP_DIFF(a, b, SECOND) (unit is an unquoted keyword, last arg).
- TIMESTAMP vs DATE: BigQuery does NOT coerce between them in comparisons. This is the single most common error in generated SQL here, and it has TWO forms — a bare '2026-08-01' literal IS a DATE, and an explicit DATE '2026-08-01' is one too. So BOTH `ts_col >= '2026-08-01'` and `ts_col >= DATE '2026-08-01'` are type errors against a TIMESTAMP column. Write `ts_col >= TIMESTAMP '2026-08-01'`, or `DATE(ts_col) >= '2026-08-01'` when day precision is meant. Writing DATE in front of the literal does NOT make it match a TIMESTAMP column — it is what makes it a DATE.
- Division: use SAFE_DIVIDE(a, b) to avoid divide-by-zero errors (returns NULL).
- Type casting: CAST(x AS INT64 | FLOAT64 | NUMERIC | STRING | DATE | TIMESTAMP). Use INT64/FLOAT64/STRING — NOT INTEGER/VARCHAR. SAFE_CAST(...) returns NULL on failure.
- String aggregation: STRING_AGG(col, ',').
- Identifiers: backtick-quote `project.dataset.table`. Reference SELECT aliases in GROUP BY/ORDER BY by position or alias (allowed), but NOT in WHERE/HAVING.
""".strip()

_SNOWFLAKE_RULES = """
SNOWFLAKE DIALECT RULES (violations cause query errors):
- Date bucketing: DATE_TRUNC('MONTH', ts) (grain quoted, column second). Supports MINUTE/HOUR/DAY/WEEK/MONTH/QUARTER/YEAR.
- Date differences: DATEDIFF('day', d1, d2) / DATEDIFF('second', a, b) (unit quoted, FIRST arg). TIMESTAMPDIFF(unit, a, b) is also valid — do not "fix" it away.
- Division: use DIV0(a, b) (returns 0 on zero denominator) or IFF(b = 0, NULL, a / b).
- Type casting: x::NUMBER / x::VARCHAR / CAST(x AS NUMBER). TRY_CAST(...) returns NULL on failure.
- String aggregation: LISTAGG(col, ',') WITHIN GROUP (ORDER BY col); to build an array use ARRAY_AGG(col).
- Filter by a window function: use QUALIFY (e.g. QUALIFY ROW_NUMBER() OVER (PARTITION BY x ORDER BY y) = 1) — you CANNOT put a window function in WHERE.
- Semi-structured (VARIANT/OBJECT/ARRAY): navigate with colon/bracket paths — col:field, col:a.b, col['k']; cast the leaf with ::STRING/::NUMBER. Expand an array into rows with LATERAL FLATTEN(input => col) f, then read f.value.
- Case-insensitive match: ILIKE '%text%' (not LOWER(col) LIKE).
- Identifiers fold to UPPERCASE unless double-quoted. You CANNOT reference SELECT aliases in WHERE/HAVING.
""".strip()

_MYSQL_RULES = """
MYSQL DIALECT RULES (violations cause query errors):
- Date bucketing: MySQL has NO date_trunc. Month → DATE_FORMAT(ts, '%Y-%m-01'); day → DATE(ts); year → DATE_FORMAT(ts, '%Y-01-01'); week (Mon start) → DATE_SUB(DATE(ts), INTERVAL WEEKDAY(ts) DAY). NEVER call date_trunc().
- Date differences: DATEDIFF(d1, d2) for whole days; TIMESTAMPDIFF(SECOND, a, b) for seconds (note: DATEDIFF takes exactly 2 args, no unit).
- Division: guard zero denominators with NULLIF — a / NULLIF(b, 0).
- Type casting: CAST(x AS SIGNED | DECIMAL(38,6) | CHAR | DATE | DATETIME). MySQL has no ::TYPE syntax and no CAST AS INT/VARCHAR (use SIGNED/CHAR).
- String aggregation: GROUP_CONCAT(col SEPARATOR ',').
- Identifiers: backtick-quote. You CAN reference SELECT aliases in GROUP BY/HAVING (MySQL extension).
""".strip()

_EXASOL_RULES = """
EXASOL DIALECT RULES (violations cause query errors):
- Date bucketing: DATE_TRUNC('MONTH', ts) (grain quoted, column second) or TRUNC(d, 'MM'); grains DAY/WEEK/MONTH/QUARTER/YEAR.
- Date differences: DAYS_BETWEEN(d1, d2) for days, SECONDS_BETWEEN(a, b) for seconds, MONTHS_BETWEEN(a, b) for months. There is NO DATEDIFF.
- Division: guard zero denominators with NULLIF — a / NULLIF(b, 0).
- Type casting: CAST(x AS DECIMAL(36,6)) / CAST(x AS VARCHAR(2000)) / CAST(x AS DATE) / CAST(x AS TIMESTAMP). A VARCHAR needs a length; there is no ::TYPE syntax.
- String aggregation: LISTAGG(col, ',') WITHIN GROUP (ORDER BY col), or GROUP_CONCAT(col SEPARATOR ',').
- Filter by a window function: QUALIFY is supported (QUALIFY ROW_NUMBER() OVER (PARTITION BY x ORDER BY y) = 1).
- Identifiers fold to UPPERCASE unless double-quoted. You CANNOT reference SELECT aliases in WHERE/HAVING.
- Row limit: LIMIT n [OFFSET m].
""".strip()

_POSTGRES_RULES = """
POSTGRESQL DIALECT RULES (violations cause query errors):
- Date bucketing: DATE_TRUNC('month'|'week'|'day'|'quarter'|'year', ts).
- Date differences: (d1 - d2) yields an INTEGER day count for dates; EXTRACT(EPOCH FROM (a - b)) for seconds between timestamps.
- Division: integer/integer truncates — cast one side (a::numeric / b) and guard zero with NULLIF(b, 0).
- Type casting: x::numeric / x::text / CAST(x AS date).
- String aggregation: STRING_AGG(col, ',').
- You CANNOT reference SELECT aliases in WHERE/HAVING/GROUP BY.
""".strip()

# DE-3b's proving engine (§6 item 37(d)): declared from Trino's documentation; the live receipt
# on a local Trino container is owed from the user's machine.
_TRINO_RULES = """
TRINO DIALECT RULES (violations cause query errors):
- Date bucketing: DATE_TRUNC('month', ts) (grain quoted lower-case, column second); grains second/minute/hour/day/week/month/quarter/year.
- Date differences: DATE_DIFF('day', d1, d2) / DATE_DIFF('second', a, b) (unit quoted, FIRST arg). There is NO DATEDIFF and NO TIMESTAMPDIFF.
- Division: integer/integer truncates — CAST one side AS DOUBLE and guard zero with NULLIF(b, 0); TRY(a / b) returns NULL instead of failing.
- Type casting: CAST(x AS BIGINT | DOUBLE | DECIMAL(38,6) | VARCHAR | DATE | TIMESTAMP). There is no ::TYPE syntax. TRY_CAST(...) returns NULL on failure.
- String aggregation: ARRAY_JOIN(ARRAY_AGG(col), ','); LISTAGG(col, ',') WITHIN GROUP (ORDER BY col) is also valid.
- Approximate counts: APPROX_DISTINCT(col).
- No QUALIFY and no ILIKE: filter a window function in an outer query, and match case-insensitively with LOWER(col) LIKE LOWER('%text%').
- Identifiers fold to lower case unless double-quoted; tables are catalog.schema.table.
- Row limit: LIMIT n; OFFSET n is supported.
""".strip()


def _f(key: str, label: str, placeholder: str = "", *, secret: bool = False, optional: bool = False) -> Field:
    return Field(key, label, placeholder, secret, optional)


ENGINES: tuple[EngineDeclaration, ...] = (
    EngineDeclaration(
        type="duckdb", label="DuckDB", category="built-in", blurb="Local analytical database file",
        rerun_cost="local",
        dsn_preview="*.duckdb",
        fields=(_f("dsn", "File path", "/path/to/file.duckdb"),
                _f("schema_name", "Schema (optional)", "main", optional=True)),
        drivers=("duckdb",), connector=None, dialect="duckdb", native_sql=False, engine_read_only=True,
        support_tier="core", metadata_strategy="information_schema",
        brand_color="#FBBF24", engine_family="postgres",
        connection_errors=("ConnectionException",), cancelled_errors=("InterruptException",),
        metadata_facts=_META_ALL, metadata_detail="duckdb_constraints(), duckdb_columns() and duckdb_tables()",
    ),
    EngineDeclaration(
        type="postgres", label="PostgreSQL", category="built-in", blurb="Connect to a Postgres database",
        rerun_cost="compute",
        dsn_preview="postgresql://***",
        fields=(_f("dsn", "Connection string", "postgresql://user:pass@host:5432/db", secret=True),
                _f("schema_name", "Schema", "public")),
        drivers=("psycopg2",), connector=None, dialect="postgres", native_sql=False, engine_read_only=True,
        writer_rules=_POSTGRES_RULES,
        refuses_functions=frozenset({"SAFE_DIVIDE", "DIV0", "IFF"}), refuses_features=frozenset({"qualify"}),
        support_tier="core", metadata_strategy="information_schema",
        brand_color="#6f9bcc", engine_family="postgres",
        connection_errors=("InterfaceError",), cancelled_errors=("QueryCanceledError", "QueryCanceled"),
        metadata_facts=_META_ALL,
        metadata_detail="information_schema.table_constraints / key_column_usage; pg_description for comments",
    ),
    EngineDeclaration(
        type="bigquery", label="BigQuery", category="warehouse", blurb="Google Cloud data warehouse",
        rerun_cost="bytes_scanned",
        dsn_preview="bigquery://project-id",
        fields=(_f("project_id", "Project ID", "my-gcp-project"),
                _f("dataset", "Dataset", "analytics"),
                _f("credentials", "Service account JSON path (or blank for ADC)", "/path/to/sa.json",
                   secret=True, optional=True)),
        drivers=("google.cloud.bigquery",),
        connector="aughor.connectors.warehouse.bigquery:BigQueryConnection",
        dialect="bigquery", native_sql=True, param_style="at", engine_read_only=False,
        writer_rules=_BIGQUERY_RULES,
        refuses_functions=frozenset({"DIV0", "IFF", "DATEDIFF"}), refuses_features=frozenset({"ilike"}),
        metadata_strategy="driver_api",
        env_vars=({"name": "GOOGLE_APPLICATION_CREDENTIALS", "secret": True, "fallback_for": "credentials",
                   "note": "resolved by the Google client library as part of Application Default "
                           "Credentials when the credentials field is blank"},),
        brand_color="#4285F4", engine_family="bigquery", sql_name="BigQuery (GoogleSQL)",
        connection_errors=("ServiceUnavailable", "InternalServerError", "RetryError"),
        timeout_errors=("DeadlineExceeded",),
        metadata_facts=_META_NOT_READ_YET,
        metadata_detail="INFORMATION_SCHEMA.TABLE_CONSTRAINTS carries unenforced keys and the schema API carries "
                        "field descriptions; neither is read yet",
    ),
    EngineDeclaration(
        type="snowflake", label="Snowflake", category="warehouse", blurb="Cloud data warehouse",
        rerun_cost="compute",
        dsn_preview="snowflake://account.region",
        fields=(_f("account", "Account identifier", "xy12345.us-east-1"),
                _f("user", "Username", "analyst"),
                _f("password", "Password", "", secret=True),
                _f("database", "Database", "PROD"),
                _f("schema_name", "Schema", "PUBLIC"),
                _f("warehouse", "Warehouse", "COMPUTE_WH")),
        drivers=("snowflake.connector",),
        connector="aughor.connectors.warehouse.snowflake:SnowflakeConnection",
        dialect="snowflake", native_sql=True, param_style="pyformat", engine_read_only=False,
        writer_rules=_SNOWFLAKE_RULES, refuses_functions=frozenset({"SAFE_DIVIDE"}),
        brand_color="#29B5E8", engine_family="snowflake",
        connection_errors=("InterfaceError",),
        metadata_facts=_META_NOT_READ_YET,
        metadata_detail="SHOW PRIMARY KEYS / SHOW IMPORTED KEYS and INFORMATION_SCHEMA.COLUMNS.COMMENT; not read yet",
    ),
    EngineDeclaration(
        type="mysql", label="MySQL", category="warehouse", blurb="Connect to a MySQL database",
        rerun_cost="compute",
        dsn_preview="mysql://host:3306/db",
        fields=(_f("host", "Host", "localhost"), _f("port", "Port", "3306"), _f("user", "Username", "root"),
                _f("password", "Password", "", secret=True), _f("database", "Database", "mydb")),
        drivers=("pymysql",), connector="aughor.connectors.warehouse.mysql:MySQLConnection",
        dialect="mysql", native_sql=True, param_style="pyformat", engine_read_only=True,
        writer_rules=_MYSQL_RULES,
        refuses_functions=frozenset({"DATE_TRUNC", "DATE_DIFF", "SAFE_DIVIDE", "DIV0", "IFF"}),
        refuses_features=frozenset({"qualify", "ilike"}),
        brand_color="#00A3C7", engine_family="mysql",
        # pymysql's OperationalError is decided by errno in db/errors.py; InterfaceError is a closed connection.
        connection_errors=("InterfaceError",),
        metadata_facts=_META_ALL,
        metadata_detail="information_schema.KEY_COLUMN_USAGE / TABLE_CONSTRAINTS; COLUMN_COMMENT and TABLE_COMMENT",
    ),
    EngineDeclaration(
        type="motherduck", label="MotherDuck", category="warehouse", blurb="DuckDB in the cloud", badge="New",
        rerun_cost="compute",
        dsn_preview="md:my_database",
        fields=(_f("token", "MotherDuck token", "eyJhbGc… (or set MOTHERDUCK_TOKEN)", secret=True),
                _f("database", "Database", "my_database"), _f("schema_name", "Schema", "main")),
        drivers=("duckdb",), connector="aughor.connectors.warehouse.motherduck:MotherDuckConnection",
        dialect="duckdb", native_sql=False, param_style="duckdb", engine_read_only=False,
        env_vars=({"name": "MOTHERDUCK_TOKEN", "secret": True, "fallback_for": "token"},),
        brand_color="#FFD000", engine_family="postgres",
        metadata_facts=_META_ALL, metadata_detail="a DuckDB database: duckdb_constraints() and the comment columns",
    ),
    EngineDeclaration(
        type="exasol", label="Exasol", category="warehouse", blurb="In-memory analytics database", badge="New",
        rerun_cost="compute",
        dsn_preview="exa://host:8563",
        fields=(_f("host", "Host:Port", "demodb.exasol.com:8563"), _f("user", "Username", "sys"),
                _f("password", "Password", "", secret=True), _f("schema_name", "Schema", "RETAIL")),
        drivers=("pyexasol",), connector="aughor.connectors.warehouse.exasol:ExasolConnection",
        dialect="exasol", native_sql=True, param_style=None, engine_read_only=False,
        writer_rules=_EXASOL_RULES, refuses_functions=frozenset({"SAFE_DIVIDE", "IFF", "DATEDIFF"}),
        support_tier="preview", metadata_strategy="engine_catalog",
        brand_color="#1B68DF", engine_family="postgres",
        connection_errors=("ExaCommunicationError", "ExaConnectionError", "ExaConnectionDsnError",
                           "ExaConnectionFailedError"),
        timeout_errors=("ExaQueryTimeoutError",), cancelled_errors=("ExaQueryAbortError",),
        metadata_facts=_META_NOT_READ_YET,
        metadata_detail="EXA_ALL_CONSTRAINTS / EXA_ALL_CONSTRAINT_COLUMNS and EXA_ALL_COLUMNS.COLUMN_COMMENT; not read yet",
    ),
    EngineDeclaration(
        type="trino", label="Trino", category="warehouse", blurb="Distributed SQL over many sources",
        rerun_cost="compute",
        badge="Preview", dsn_preview="trino://host:8080",
        fields=(_f("host", "Host:Port", "trino.example.com:8080"), _f("user", "Username", "analyst"),
                _f("password", "Password (blank when the cluster takes none)", "", secret=True, optional=True),
                _f("catalog", "Catalog", "hive"), _f("schema_name", "Schema", "default")),
        drivers=("trino",), connector="aughor.connectors.warehouse.trino:TrinoConnection",
        dialect="trino", native_sql=True, param_style=None, engine_read_only=False,
        writer_rules=_TRINO_RULES,
        refuses_functions=frozenset({"SAFE_DIVIDE", "DIV0", "IFF", "DATEDIFF", "TIMESTAMPDIFF"}),
        refuses_features=frozenset({"qualify", "ilike"}),
        support_tier="preview", metadata_strategy="information_schema",
        brand_color="#DD00A1", engine_family="standard",
        connection_errors=("TrinoConnectionError",),
        metadata_facts=_facts("supported", "unsupported", "unsupported", "unknown"),
        metadata_detail="Trino declares no primary or foreign keys; INFORMATION_SCHEMA.COLUMNS.COMMENT is not read yet",
    ),
    EngineDeclaration(
        type="gsheets", label="Google Sheets", category="api", blurb="Read worksheets as tables", badge="New",
        rerun_cost="local",
        dsn_preview="gsheet://spreadsheet-id",
        fields=(_f("spreadsheet_id", "Spreadsheet ID or URL", "https://docs.google.com/spreadsheets/d/…"),
                # The sheet must be shared "Anyone with the link can view" — read via the public CSV
                # export. No API key field: a key alone cannot unlock a private sheet (that needs
                # OAuth), so offering one would over-promise.
                _f("sheets", "Sheet/tab names", "Sheet1,Sheet2 (empty = first sheet)", optional=True)),
        drivers=("duckdb",), connector="aughor.connectors.api.gsheets:GoogleSheetsConnector",
        dialect="duckdb", native_sql=False, param_style="duckdb", engine_read_only=False,
        brand_color="#0F9D58", engine_family="postgres",
        metadata_facts=_META_NO_KEYS, metadata_detail="a worksheet declares no keys and carries no comments",
    ),
    EngineDeclaration(
        type="local_upload", label="Create or modify table", category="file",
        rerun_cost="local",
        blurb="Upload CSV, Parquet, Excel or JSON into your Workspace", dsn_preview="local://uploads/",
        fields=(),   # no config fields — files arrive through POST /connections/{id}/files
        drivers=("duckdb",), connector="aughor.connectors.file.local_upload:LocalUploadConnection",
        dialect="duckdb", native_sql=False, param_style=None, engine_read_only=False,
        support_tier="core", metadata_strategy="information_schema",
        brand_color="#3B82F6", engine_family="postgres",
        metadata_facts=_META_NO_KEYS, metadata_detail="an uploaded file declares no keys and carries no comments",
    ),
    EngineDeclaration(
        type="s3", label="Amazon S3", category="file", blurb="Object storage bucket",
        rerun_cost="bytes_scanned",
        dsn_preview="s3://bucket/prefix",
        fields=(_f("bucket", "Bucket", "my-data-bucket"), _f("prefix", "Key prefix", "data/sales/"),
                _f("region", "Region", "us-east-1"), _f("key_id", "Access Key ID", "AKIA…", secret=True),
                _f("secret", "Secret Access Key", "", secret=True)),
        drivers=("duckdb",), connector="aughor.connectors.file.s3:S3Connection",
        dialect="duckdb", native_sql=False, param_style="duckdb", engine_read_only=False,
        brand_color="#569A31", engine_family="postgres",
        metadata_facts=_META_NO_KEYS, metadata_detail="files in a bucket declare no keys and carry no comments",
    ),
    EngineDeclaration(
        type="sqlite", label="SQLite", category="file", blurb="A SQLite database file",
        rerun_cost="local",
        dsn_preview="*.sqlite / *.db",
        fields=(_f("dsn", "File path", "/path/to/file.sqlite"),),
        drivers=("ibis",), connector="aughor.connectors.file.sqlite:SQLiteConnection",
        dialect="sqlite", native_sql=False, param_style="named", engine_read_only=None,
        metadata_strategy="pragma", brand_color="#0F80CC", engine_family="sqlite",
        metadata_facts=_facts("supported", "supported", "supported", "unsupported"),
        metadata_detail="pragma_table_info and pragma_foreign_key_list; SQLite has no comments",
    ),
    EngineDeclaration(
        type="federated", label="Federated", category="federation", blurb="Combine existing connections",
        rerun_cost="compute",
        dsn_preview="federated://",
        fields=(),   # no config fields — members are chosen through POST /connections/federate
        drivers=("duckdb",), connector="aughor.connectors.federated:FederatedConnection",
        dialect="duckdb", native_sql=False, param_style="duckdb", engine_read_only=False,
        metadata_strategy="cursor_description", brand_color="#34d399", engine_family="postgres",
        metadata_facts=_META_NO_KEYS,
        metadata_detail="members are attached as views; a member's declared keys and comments do not survive the attach",
    ),
    EngineDeclaration(
        type="stripe", label="Stripe", category="api", blurb="Payments & billing data", badge="Preview",
        rerun_cost="local",
        dsn_preview="stripe://",
        fields=(_f("secret_key", "Secret key", "sk_live_…", secret=True),
                _f("objects", "Objects to sync (optional)", "charges,customers,subscriptions,invoices", optional=True)),
        drivers=("requests",), connector="aughor.connectors.api.stripe:StripeConnector",
        dialect="duckdb", native_sql=False, param_style="duckdb", engine_read_only=False,
        support_tier="preview", brand_color="#7a73ff", engine_family="postgres",
        metadata_facts=_META_NO_KEYS, metadata_detail="synced objects land as tables with no declared keys or comments",
    ),
    EngineDeclaration(
        type="hubspot", label="HubSpot", category="api", blurb="CRM & marketing data", dsn_preview="hubspot://",
        rerun_cost="local",
        fields=(_f("access_token", "Access token", "pat-na1-…", secret=True),
                _f("objects", "Objects to sync (optional)", "contacts,companies,deals,tickets", optional=True)),
        drivers=("requests",), connector="aughor.connectors.api.hubspot:HubSpotConnector",
        dialect="duckdb", native_sql=False, param_style="duckdb", engine_read_only=False,
        brand_color="#FF7A59", engine_family="postgres",
        metadata_facts=_META_NO_KEYS, metadata_detail="synced objects land as tables with no declared keys or comments",
    ),
    EngineDeclaration(
        type="salesforce", label="Salesforce", category="api", blurb="CRM objects & pipelines",
        rerun_cost="local",
        dsn_preview="salesforce://",
        fields=(_f("username", "Username", "user@org.com"), _f("password", "Password", "", secret=True),
                _f("security_token", "Security token", "token123…", secret=True),
                _f("domain", "Domain", "login (or test)"),
                _f("objects", "Objects to sync (optional)", "Account,Contact,Opportunity,Lead,Case", optional=True)),
        drivers=("requests",), connector="aughor.connectors.api.salesforce:SalesforceConnector",
        dialect="duckdb", native_sql=False, param_style="duckdb", engine_read_only=False,
        brand_color="#00A1E0", engine_family="postgres",
        metadata_facts=_META_NO_KEYS, metadata_detail="synced objects land as tables with no declared keys or comments",
    ),
    # Knowledge connectors index documents for synthesis context; they are not SQL connectors,
    # take no queries, and are categorised but not registered (`open_connection` never sees them).
    EngineDeclaration(
        type="confluence", label="Confluence", category="knowledge", blurb="Team wiki & knowledge",
        rerun_cost="unknown",
        dsn_preview="https://org.atlassian.net",
        fields=(_f("base_url", "Base URL", "https://yourorg.atlassian.net"),
                _f("username", "Username", "user@example.com"),
                _f("api_token", "API token", "ATATT3…", secret=True),
                _f("space_keys", "Space keys", "ENG,PROD (empty = all)", optional=True)),
        drivers=("requests",), connector=None, dialect=None, metadata_strategy="none",
        brand_color="#2684FF", metadata_facts=_META_NONE, metadata_detail="not a SQL connector",
    ),
    EngineDeclaration(
        type="notion", label="Notion", category="knowledge", blurb="Docs & databases", dsn_preview="notion://",
        rerun_cost="unknown",
        fields=(_f("integration_token", "Integration token", "secret_…", secret=True),
                _f("database_ids", "Database IDs", "id1,id2 (optional)", optional=True)),
        drivers=("requests",), connector=None, dialect=None, metadata_strategy="none",
        brand_color="#c4c4cc", metadata_facts=_META_NONE, metadata_detail="not a SQL connector",
    ),
)

# ── engines that speak another's protocol: one declaration each, no new driver ──────────
# The tile is what a person looks for; the wire is what connects. `badge="Preview"` until its server has passed
# `tests/integration/test_connectors_on_real_servers.py`, which is what `proven=True` says (and, on the two written out below,
# no badge). Run on 2026-11-03 against CockroachDB, TimescaleDB, MySQL, MariaDB, TiDB, ClickHouse, SQL Server and Oracle.

_POSTGRES = next(e for e in ENGINES if e.type == "postgres")
_MYSQL = next(e for e in ENGINES if e.type == "mysql")
_TRINO = next(e for e in ENGINES if e.type == "trino")


def _postgres_wire(type_: str, label: str, blurb: str, example: str, color: str, *, proven: bool = False,
                   schema: str = "public") -> EngineDeclaration:
    return replace(_POSTGRES, type=type_, label=label, category="warehouse", blurb=blurb,
                   dsn_preview=f"{type_}://***", brand_color=color,
                   fields=(_f("dsn", "Connection string", example, secret=True), _f("schema_name", "Schema", schema)),
                   connector="aughor.connectors.warehouse.wire:PostgresWireConnection",
                   badge=None if proven else "Preview", support_tier="supported" if proven else "preview")


def _mysql_wire(type_: str, label: str, blurb: str, port: str, color: str, *, proven: bool = False,
                read_only: Optional[bool] = None) -> EngineDeclaration:
    """``read_only`` is what its server was seen to do. The connection measures it again each time it opens (`wire.py`)."""
    return replace(_MYSQL, type=type_, label=label, blurb=blurb, dsn_preview=f"{type_}://host:{port}/db", brand_color=color,
                   connector="aughor.connectors.warehouse.wire:MySQLWireConnection", engine_read_only=read_only,
                   fields=(_f("host", "Host", "localhost"), _f("port", "Port", port), _f("user", "Username", "root"),
                           _f("password", "Password", "", secret=True), _f("database", "Database", "mydb")),
                   badge=None if proven else "Preview", support_tier="supported" if proven else "preview")


_TSQL_RULES = """
T-SQL (MICROSOFT SQL SERVER) DIALECT RULES (violations cause query errors):
- Row limit: SELECT TOP n ...; there is no LIMIT. With OFFSET: ORDER BY x OFFSET m ROWS FETCH NEXT n ROWS ONLY.
- Date bucketing: DATEFROMPARTS(YEAR(d), MONTH(d), 1) for a month, CAST(ts AS DATE) for a day; DATETRUNC exists only from SQL Server 2022.
- Date differences: DATEDIFF(day, d1, d2) (unit unquoted, FIRST arg, and the result is d2 minus d1).
- Division: integer/integer truncates: multiply one side by 1.0 and guard zero with NULLIF(b, 0).
- Type casting: CAST(x AS BIGINT | DECIMAL(38,6) | FLOAT | NVARCHAR(4000) | DATE | DATETIME2). TRY_CAST returns NULL on failure. No ::TYPE.
- String aggregation: STRING_AGG(col, ','). Concatenate with + or CONCAT().
- No QUALIFY and no ILIKE. An ORDER BY in a subquery needs TOP. Filter a window function in an outer query.
- Identifiers: [bracket-quote]; tables are schema.table. You CANNOT reference SELECT aliases in WHERE/HAVING/GROUP BY.
""".strip()

_ORACLE_RULES = """
ORACLE DIALECT RULES (violations cause query errors):
- Row limit: FETCH FIRST n ROWS ONLY after ORDER BY; there is no LIMIT.
- Date bucketing: TRUNC(d, 'MM') for a month, TRUNC(d) for a day, TRUNC(d, 'YYYY') for a year.
- Date differences: d1 - d2 is a number of days; MONTHS_BETWEEN(a, b) for months. A literal needs DATE '2026-01-31'.
- Division: guard zero with NULLIF(b, 0). An empty string IS NULL.
- Type casting: CAST(x AS NUMBER(38,6) | VARCHAR2(4000) | DATE | TIMESTAMP). No ::TYPE.
- String aggregation: LISTAGG(col, ',') WITHIN GROUP (ORDER BY col). Concatenate with ||.
- A SELECT with no table reads FROM DUAL. No QUALIFY and no ILIKE; a table alias takes no AS.
- Identifiers fold to UPPERCASE unless double-quoted. You CANNOT reference SELECT aliases in WHERE/HAVING/GROUP BY.
""".strip()

_CLICKHOUSE_RULES = """
CLICKHOUSE DIALECT RULES (violations cause query errors):
- Date bucketing: toStartOfMonth(d), toStartOfWeek(d), toDate(ts), toStartOfYear(d); function names are case-sensitive.
- Date differences: dateDiff('day', d1, d2) (unit quoted, FIRST arg).
- Division: a / b is always a Float; guard zero with nullIf(b, 0). intDiv(a, b) for integers.
- Type casting: toInt64(x), toFloat64(x), toString(x), toDate(x), toDateTime(x); CAST(x AS Int64) also works. Types are case-sensitive.
- String aggregation: arrayStringConcat(groupArray(col), ','). Approximate counts: uniq(col).
- Filter by a window function: QUALIFY is supported. You CAN reference SELECT aliases in WHERE/GROUP BY/HAVING. ILIKE is supported.
- Identifiers are case-sensitive; tables are database.table. A column is non-nullable unless declared Nullable.
""".strip()

_DATABRICKS_RULES = """
DATABRICKS SQL (SPARK) DIALECT RULES (violations cause query errors):
- Date bucketing: DATE_TRUNC('MONTH', ts) (grain quoted, FIRST arg); TO_DATE(ts) for a day.
- Date differences: DATEDIFF(d2, d1) for days (end first); TIMESTAMPDIFF(SECOND, a, b).
- Division: a / b is a Double; TRY_DIVIDE(a, b) returns NULL on zero.
- Type casting: CAST(x AS BIGINT | DOUBLE | DECIMAL(38,6) | STRING | DATE | TIMESTAMP); x::BIGINT also works; TRY_CAST returns NULL on failure.
- String aggregation: ARRAY_JOIN(COLLECT_LIST(col), ','). Approximate counts: APPROX_COUNT_DISTINCT(col).
- Filter by a window function: QUALIFY is supported. ILIKE is supported. You CAN reference SELECT aliases in GROUP BY.
- Identifiers: backtick-quote; tables are catalog.schema.table.
""".strip()

_ATHENA_RULES = _TRINO_RULES.replace("TRINO DIALECT RULES", "AMAZON ATHENA (TRINO ENGINE) DIALECT RULES") + """
- Every statement scans and bills its tables' bytes: filter on the partition columns and name only the columns you need.
""".rstrip()

_MSSQL = EngineDeclaration(
    type="mssql", label="Microsoft SQL Server", category="warehouse",
    blurb="Connect to a SQL Server database. It cannot refuse writes itself: give it a read-only login",
    rerun_cost="compute", dsn_preview="mssql://host:1433/db",
    fields=(_f("host", "Host", "localhost"), _f("port", "Port", "1433"), _f("user", "Username", "sa"),
            _f("password", "Password", "", secret=True), _f("database", "Database", "mydb"), _f("schema_name", "Schema", "dbo")),
    drivers=("pymssql",), connector="aughor.connectors.warehouse.mssql:MSSQLConnection",
    dialect="tsql", native_sql=True, param_style="pyformat", engine_read_only=False, writer_rules=_TSQL_RULES,
    refuses_functions=frozenset({"DATE_TRUNC", "DATE_DIFF", "SAFE_DIVIDE", "DIV0", "IFF"}), refuses_features=frozenset({"qualify", "ilike"}),
    brand_color="#CC2927", metadata_facts=_META_NOT_READ_YET, metadata_detail="INFORMATION_SCHEMA.COLUMNS; keys and comments are not read yet",
)

ENGINES = ENGINES + (
    _postgres_wire("cockroachdb", "CockroachDB", "Distributed SQL on Postgres's protocol",
                   "postgresql://user:pass@host:26257/db?sslmode=require", "#6933FF", proven=True),
    _postgres_wire("timescaledb", "TimescaleDB", "Time series on Postgres", "postgresql://user:pass@host:5432/db", "#FDB515", proven=True),
    _postgres_wire("redshift", "Amazon Redshift", "AWS data warehouse",
                   "postgresql://user:pass@cluster.region.redshift.amazonaws.com:5439/dev", "#8C4FFF"),
    _postgres_wire("yugabytedb", "YugabyteDB", "Distributed Postgres", "postgresql://user:pass@host:5433/yugabyte", "#FF6E42"),
    _postgres_wire("greenplum", "Greenplum", "Massively parallel Postgres", "postgresql://user:pass@host:5432/db", "#00A65E"),
    _postgres_wire("aurora_postgres", "Aurora PostgreSQL", "AWS managed Postgres",
                   "postgresql://user:pass@cluster.region.rds.amazonaws.com:5432/db", "#4169E1"),
    _postgres_wire("alloydb", "Google AlloyDB", "Google Cloud managed Postgres", "postgresql://user:pass@host:5432/db", "#4285F4"),
    _postgres_wire("neon", "Neon", "Serverless Postgres; use its direct endpoint, not the pooled one",
                   "postgresql://user:pass@ep-name.region.aws.neon.tech/db?sslmode=require", "#00E599"),
    _postgres_wire("supabase", "Supabase", "Hosted Postgres; use its direct connection string",
                   "postgresql://postgres:pass@db.project.supabase.co:5432/postgres", "#3ECF8E"),
    _mysql_wire("mariadb", "MariaDB", "Connect to a MariaDB database", "3306", "#C0765A", proven=True, read_only=True),
    _mysql_wire("tidb", "TiDB", "Distributed SQL on MySQL's protocol. It cannot refuse writes itself: give it a read-only login",
                "4000", "#E30C33", proven=True, read_only=False),
    _mysql_wire("aurora_mysql", "Aurora MySQL", "AWS managed MySQL", "3306", "#4479A1"),
    _mysql_wire("singlestore", "SingleStore", "Real-time distributed SQL", "3306", "#AA00FF"),
    _mysql_wire("starrocks", "StarRocks", "Analytical database on MySQL's protocol", "9030", "#1F4FFF"),
    _mysql_wire("doris", "Apache Doris", "Analytical database on MySQL's protocol", "9030", "#5B5FE3"),
    replace(_TRINO, type="starburst", label="Starburst", blurb="Trino, managed", dsn_preview="starburst://host:443", brand_color="#00A7E1"),
    _MSSQL,
    replace(_MSSQL, type="synapse", label="Azure Synapse", blurb="Azure's analytics warehouse, through SQL Server's driver",
            dsn_preview="synapse://server.sql.azuresynapse.net:1433/db", brand_color="#0078D4", badge="Preview", support_tier="preview",
            fields=(_f("host", "Host", "server.sql.azuresynapse.net"), _f("port", "Port", "1433"), _f("user", "Username", "sqladmin"),
                    _f("password", "Password", "", secret=True), _f("database", "Database", "db"), _f("schema_name", "Schema", "dbo"))),
    EngineDeclaration(
        type="oracle", label="Oracle", category="warehouse", blurb="Connect to an Oracle database",
        rerun_cost="compute", dsn_preview="oracle://host:1521/service",
        fields=(_f("host", "Host", "localhost"), _f("port", "Port", "1521"), _f("user", "Username", "analyst"),
                _f("password", "Password", "", secret=True), _f("service_name", "Service name", "ORCLPDB1"),
                _f("schema_name", "Schema (the login's own when blank)", "", optional=True)),
        drivers=("oracledb",), connector="aughor.connectors.warehouse.oracle:OracleConnection",
        dialect="oracle", native_sql=True, param_style="named", engine_read_only=True, writer_rules=_ORACLE_RULES,
        refuses_functions=frozenset({"DATE_TRUNC", "DATE_DIFF", "DATEDIFF", "SAFE_DIVIDE", "DIV0", "IFF"}), refuses_features=frozenset({"qualify", "ilike"}),
        brand_color="#F80000", metadata_facts=_META_NOT_READ_YET, metadata_detail="ALL_TAB_COLUMNS; keys and comments are not read yet",
    ),
    EngineDeclaration(
        type="clickhouse", label="ClickHouse", category="warehouse", blurb="Column-oriented analytics database",
        rerun_cost="compute", dsn_preview="clickhouse://host:8123/db",
        fields=(_f("host", "Host", "localhost"), _f("port", "Port", "8123"), _f("user", "Username", "default"),
                _f("password", "Password", "", secret=True, optional=True), _f("database", "Database", "default"),
                _f("secure", "Use HTTPS (true or false)", "false", optional=True)),
        drivers=("clickhouse_connect",), connector="aughor.connectors.warehouse.clickhouse:ClickHouseConnection",
        dialect="clickhouse", native_sql=True, param_style="pyformat", engine_read_only=True, writer_rules=_CLICKHOUSE_RULES,
        refuses_functions=frozenset({"DATE_TRUNC", "SAFE_DIVIDE", "DIV0", "IFF", "STRING_AGG"}),
        brand_color="#FFCC01", metadata_facts=_META_NOT_READ_YET, metadata_detail="system.columns; keys and comments are not read yet",
    ),
    EngineDeclaration(
        type="databricks", label="Databricks", category="warehouse", blurb="Lakehouse SQL warehouses and clusters", badge="Preview",
        rerun_cost="compute", dsn_preview="databricks://workspace.cloud.databricks.com",
        fields=(_f("host", "Server hostname", "dbc-1234.cloud.databricks.com"), _f("http_path", "HTTP path", "/sql/1.0/warehouses/abc"),
                _f("access_token", "Access token", "", secret=True), _f("catalog", "Catalog", "main", optional=True),
                _f("schema_name", "Schema", "default")),
        drivers=("databricks.sql",), connector="aughor.connectors.warehouse.databricks:DatabricksConnection",
        dialect="databricks", native_sql=True, param_style=None, engine_read_only=False, writer_rules=_DATABRICKS_RULES,
        refuses_functions=frozenset({"SAFE_DIVIDE", "DIV0", "IFF"}), support_tier="preview",
        brand_color="#FF3621", metadata_facts=_META_NOT_READ_YET, metadata_detail="INFORMATION_SCHEMA.COLUMNS; keys and comments are not read yet",
    ),
    EngineDeclaration(
        type="athena", label="Amazon Athena", category="warehouse", blurb="Query S3 with SQL; every statement bills its scan", badge="Preview",
        rerun_cost="bytes_scanned", dsn_preview="athena://region",
        fields=(_f("region", "Region", "us-east-1"), _f("s3_staging_dir", "Results bucket", "s3://my-athena-results/"),
                _f("access_key", "Access key (blank for the AWS default chain)", "", optional=True),
                _f("secret_key", "Secret key", "", secret=True, optional=True), _f("work_group", "Workgroup", "primary", optional=True),
                _f("schema_name", "Database", "default")),
        drivers=("pyathena",), connector="aughor.connectors.warehouse.athena:AthenaConnection",
        dialect="athena", native_sql=True, param_style=None, engine_read_only=False, writer_rules=_ATHENA_RULES,
        refuses_functions=_TRINO.refuses_functions, refuses_features=_TRINO.refuses_features, support_tier="preview",
        brand_color="#8C4FFF", metadata_facts=_facts("supported", "unsupported", "unsupported", "unknown"),
        metadata_detail="INFORMATION_SCHEMA.COLUMNS; Athena declares no primary or foreign keys",
    ),
)

BY_TYPE: dict[str, EngineDeclaration] = {e.type: e for e in ENGINES}


def declaration(conn_type: str) -> EngineDeclaration:
    """The one declaration for a type; a KeyError names the type, so a connector class that
    references a declaration nobody wrote fails at import, not at first use."""
    try:
        return BY_TYPE[conn_type]
    except KeyError:
        raise KeyError(f"no engine declaration for {conn_type!r} — add one to "
                       f"aughor/connectors/declarations.py") from None


def by_dialect(engines: tuple[EngineDeclaration, ...] = ENGINES) -> dict[str, EngineDeclaration]:
    """One declaration per dialect — the engine that carries the dialect's writer rules and
    refusals, when several share a dialect (every DuckDB-backed connector shares `duckdb`)."""
    out: dict[str, EngineDeclaration] = {}
    for e in engines:
        if not e.dialect:
            continue
        cur = out.get(e.dialect)
        if cur is None or (e.writer_rules and not cur.writer_rules):
            out[e.dialect] = e
    return out


# ── derivations: every table the rest of the package used to keep by hand ────────────────

def derive_writer_rules(engines: tuple[EngineDeclaration, ...] = ENGINES) -> dict[str, str]:
    return {d: e.writer_rules for d, e in by_dialect(engines).items() if e.writer_rules}


def derive_refusals(engines: tuple[EngineDeclaration, ...] = ENGINES) -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    """dialect → (functions that error, feature keys that error), for the capability contract."""
    return {d: (e.refuses_functions, e.refuses_features) for d, e in by_dialect(engines).items()
            if e.refuses_functions or e.refuses_features}


def derive_engine_names(engines: tuple[EngineDeclaration, ...] = ENGINES) -> dict[str, str]:
    """dialect → the name a person writing SQL for it would say (the prompt's spelling)."""
    names = {d: (e.sql_name or e.label) for d, e in by_dialect(engines).items()}
    names.setdefault("postgresql", names.get("postgres", "PostgreSQL"))
    return names


def derive_error_names(engines: tuple[EngineDeclaration, ...] = ENGINES) -> dict[str, frozenset[str]]:
    """kind → the drivers' exception class names that mean it on their own, for `db/errors.py`."""
    return {
        "connection": frozenset(n for e in engines for n in e.connection_errors),
        "timeout": frozenset(n for e in engines for n in e.timeout_errors),
        "cancelled": frozenset(n for e in engines for n in e.cancelled_errors),
    }


def derive_registry_tables(engines: tuple[EngineDeclaration, ...] = ENGINES) -> dict[str, dict]:
    """The registry's six tables, as `registry.py` exports them."""
    return {
        "DSN_PREVIEWS": {e.type: e.dsn_preview for e in engines},
        "FORM_FIELDS": {e.type: [f.as_dict() for f in e.fields] for e in engines},
        "DRIVERS": {e.type: tuple(e.drivers) for e in engines},
        "CATEGORIES": {e.type: e.category for e in engines},
        "ENV_VARS": {e.type: [dict(v) for v in e.env_vars] for e in engines if e.env_vars},
        "REGISTRATIONS": {e.type: e.connector for e in engines if e.connector},
    }
