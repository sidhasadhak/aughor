"""Stripe connector — syncs revenue, customer, and subscription data into DuckDB.

Objects synced:
  charges          — payment attempts (amount, currency, status, customer, created)
  customers        — customer records (email, name, created, metadata)
  subscriptions    — recurring billing (status, plan, amount, interval, customer)
  invoices         — billing invoices (amount_due, paid, status, customer, lines)
  payment_intents  — payment intent lifecycle (amount, status, customer, metadata)

DSN format:  stripe://  (sentinel)
Meta fields: {"secret_key": "sk_live_…", "objects": "charges,customers,subscriptions"}

Optional dep:  none — uses requests (always available)
Install:        pip install stripe>=7.0.0  for full SDK (not required)
"""
from __future__ import annotations

from datetime import datetime

import requests

from aughor.connectors.api.base_sync import RestApiSync

_STRIPE_BASE = "https://api.stripe.com/v1"
_DEFAULT_OBJECTS = ["charges", "customers", "subscriptions", "invoices", "payment_intents"]
_PAGE_SIZE = 100


class StripeConnector(RestApiSync):
    """Stripe REST API → DuckDB mirror."""

    def __init__(self, dsn="stripe://", schema_name=None, connection_id="", meta=None):
        super().__init__(dsn=dsn, schema_name=schema_name, connection_id=connection_id, meta=meta)
        meta = meta or {}
        self._secret_key = meta.get("secret_key", "")
        if not self._secret_key:
            raise ValueError("Stripe connector requires meta['secret_key'] = 'sk_live_…'")
        self._session = requests.Session()
        self._session.auth = (self._secret_key, "")  # Stripe uses HTTP basic auth
        self._session.headers.update({"Stripe-Version": "2023-10-16"})
        obj_list = meta.get("objects", "")
        self._obj_list = [o.strip() for o in obj_list.split(",") if o.strip()] or _DEFAULT_OBJECTS

    # ── RestApiSync contract ───────────────────────────────────────────────────

    def _objects(self) -> list[str]:
        return self._obj_list

    def _fetch_page(
        self,
        obj: str,
        after: str | None,
        since: datetime | None,
    ) -> tuple[list[dict], str | None]:
        params: dict = {"limit": _PAGE_SIZE}
        if after:
            params["starting_after"] = after
        if since:
            params["created[gte]"] = int(since.timestamp())

        resp = self._session.get(f"{_STRIPE_BASE}/{obj}", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        records = data.get("data", [])
        # Stripe pagination: has_more + last object id
        next_cursor = records[-1]["id"] if data.get("has_more") and records else None
        return records, next_cursor

    def _flatten(self, record: dict, prefix: str = "") -> dict:
        """Strip nested dicts to scalars; expand metadata dict."""
        import json as _json
        flat: dict = {}
        for k, v in record.items():
            key = f"{prefix}{k}".replace(".", "_")
            if k == "metadata" and isinstance(v, dict):
                # Keep metadata as JSON string
                flat[key] = _json.dumps(v)
            elif isinstance(v, dict):
                flat.update(self._flatten(v, prefix=f"{key}_"))
            elif isinstance(v, list):
                flat[key] = _json.dumps(v)
            else:
                flat[key] = str(v) if v is not None else None
        return flat

    # ── DatabaseConnection overrides ──────────────────────────────────────────

    def test(self) -> tuple[bool, str]:
        try:
            resp = self._session.get(f"{_STRIPE_BASE}/balance", timeout=10)
            resp.raise_for_status()
            bal = resp.json()
            avail = bal.get("available", [{}])
            currency = avail[0].get("currency", "?").upper() if avail else "?"
            amount = avail[0].get("amount", 0) / 100 if avail else 0
            return True, f"Stripe connected — balance: {amount:.2f} {currency}"
        except Exception as e:
            return False, str(e)
