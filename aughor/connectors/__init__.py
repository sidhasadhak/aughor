"""Multi-source connector platform for Aughor.

Connector taxonomy:
  warehouse  — cloud SQL warehouses (BigQuery, Snowflake, MySQL, …)
  file       — CSV, Parquet, Excel, S3 objects (materialized into DuckDB)
  api        — REST sync connectors (Salesforce, HubSpot, Stripe — future)
  knowledge  — Confluence, Notion (feeds document pipeline — future)

All connectors extend DatabaseConnection and are registered in
aughor.connectors.registry so open_connection() routes to the right class.
"""
from aughor.connectors.registry import (
    ConnectorRegistry,
    build_connector,
    REGISTRY,
)

__all__ = ["ConnectorRegistry", "build_connector", "REGISTRY"]
