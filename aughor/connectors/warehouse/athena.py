"""Amazon Athena. `pyathena`; declared in `connectors/declarations.py`.

Written from Athena's documentation and not yet run against an AWS account, so it is Preview. Every statement scans and bills
its tables' bytes (`rerun_cost` says so), and Athena has no read-only session: the door's checks are the boundary.
"""
from __future__ import annotations

from aughor.connectors.declarations import declaration
from aughor.connectors.warehouse.dbapi import DbApiWarehouse, literal

_DECL = declaration("athena")


class AthenaConnection(DbApiWarehouse):
    connector_category = _DECL.category
    dialect = _DECL.dialect
    writes_native_sql = _DECL.native_sql
    engine_read_only = _DECL.engine_read_only
    _NAME = "Athena"

    def __init__(self, dsn: str = "", schema_name: str | None = None, connection_id: str = "", meta: dict | None = None) -> None:
        self.dep_check("pyathena", "PyAthena>=3.0.0")
        from pyathena import connect

        meta = meta or {}
        self._connection_id = connection_id
        self._schema_name = schema_name or meta.get("schema_name") or "default"
        # Credentials left blank fall to the AWS default chain (a profile, an instance role).
        self._conn = connect(
            s3_staging_dir=meta.get("s3_staging_dir", ""), region_name=meta.get("region", ""),
            aws_access_key_id=meta.get("access_key") or None, aws_secret_access_key=meta.get("secret_key") or None,
            work_group=meta.get("work_group") or None, schema_name=self._schema_name,
        )

    def _columns_sql(self) -> str:
        return ("SELECT table_name, column_name, data_type FROM INFORMATION_SCHEMA.COLUMNS "
                f"WHERE table_schema = {literal(self._schema_name)} ORDER BY table_name, ordinal_position")
