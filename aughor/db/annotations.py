"""Schema annotations — user-authored descriptions for tables and columns.

These descriptions flow directly into the LLM schema context at render time,
closing the semantic gap between raw column names and what they mean in this
specific domain.

Storage: one JSON file per connection at  data/annotations_{conn_id}.json

Format:
{
  "tables": {
    "order_items": {
      "description": "Line-item revenue and shipping cost for each delivered order.",
      "columns": {
        "freight_value": "Shipping cost charged to the seller (BRL). Aggregation target — always SUM.",
        "price":         "Unit sale price charged to the customer (BRL). Aggregation target — always SUM."
      }
    }
  }
}
"""
from __future__ import annotations

import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent.parent / "data"


# ── Data class ────────────────────────────────────────────────────────────────

class SchemaAnnotations:
    """Container for user-authored table and column descriptions."""

    def __init__(self, data: dict | None = None) -> None:
        self._data: dict = data or {"tables": {}}

    # ── Reads ─────────────────────────────────────────────────────────────────

    def table_description(self, table: str) -> str:
        return self._data.get("tables", {}).get(table, {}).get("description", "")

    def column_description(self, table: str, column: str) -> str:
        return (
            self._data.get("tables", {})
            .get(table, {})
            .get("columns", {})
            .get(column, "")
        )

    def all_tables(self) -> dict[str, dict]:
        """Return the full annotations dict keyed by table name."""
        return dict(self._data.get("tables", {}))

    def is_empty(self) -> bool:
        return not self._data.get("tables")

    # ── Writes ────────────────────────────────────────────────────────────────

    def set_table_description(self, table: str, description: str) -> None:
        self._data.setdefault("tables", {}).setdefault(table, {})["description"] = description.strip()

    def set_column_description(self, table: str, column: str, description: str) -> None:
        tbl = self._data.setdefault("tables", {}).setdefault(table, {})
        tbl.setdefault("columns", {})[column] = description.strip()

    def delete_table_description(self, table: str) -> None:
        entry = self._data.get("tables", {}).get(table, {})
        entry.pop("description", None)
        # remove the table key entirely if it has no columns either
        if not entry.get("columns") and not entry.get("description"):
            self._data.get("tables", {}).pop(table, None)

    def delete_column_description(self, table: str, column: str) -> None:
        (
            self._data.get("tables", {})
            .get(table, {})
            .get("columns", {})
            .pop(column, None)
        )

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return self._data

    @classmethod
    def from_dict(cls, d: dict) -> "SchemaAnnotations":
        return cls(d)


# ── Persistence ───────────────────────────────────────────────────────────────

def _path(connection_id: str) -> Path:
    return _DATA_DIR / f"annotations_{connection_id}.json"


def load_annotations(connection_id: str) -> SchemaAnnotations:
    p = _path(connection_id)
    if not p.exists():
        return SchemaAnnotations()
    try:
        return SchemaAnnotations.from_dict(json.loads(p.read_text()))
    except Exception:
        return SchemaAnnotations()


def save_annotations(connection_id: str, annotations: SchemaAnnotations) -> None:
    _DATA_DIR.mkdir(exist_ok=True)
    _path(connection_id).write_text(json.dumps(annotations.to_dict(), indent=2))


# ── Schema injection ──────────────────────────────────────────────────────────

def inject_into_schema_parts(
    parts: list[str],
    table: str,
    col_name: str | None,
    annotations: SchemaAnnotations,
) -> None:
    """Mutate the last element of *parts* to append an annotation comment.

    Called inline while building the schema context parts list:
      • col_name=None  → annotating a TABLE: header line
      • col_name=str   → annotating a column line
    """
    if col_name is None:
        desc = annotations.table_description(table)
    else:
        desc = annotations.column_description(table, col_name)

    if not desc:
        return

    if parts:
        # Append inline — keeps the schema compact and readable
        parts[-1] = f"{parts[-1]}  ⬝ {desc}"
