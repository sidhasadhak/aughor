"""HubSpot CRM connector — contacts, companies, deals, tickets → DuckDB.

Objects synced:
  contacts    — email, firstname, lastname, createdate, lastmodifieddate, lifecyclestage
  companies   — name, domain, industry, city, country, numberofemployees
  deals       — dealname, amount, dealstage, closedate, pipeline
  tickets     — subject, hs_ticket_priority, hs_pipeline_stage, createdate

DSN:   hubspot://
Meta:  {"access_token": "pat-na1-…", "objects": "contacts,companies,deals,tickets"}

Auth:  Private App access token (OAuth) — generate at
       HubSpot → Settings → Integrations → Private Apps

Optional dep:  none — uses requests
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

import requests

from aughor.connectors.api.base_sync import RestApiSync

_BASE = "https://api.hubapi.com"
_DEFAULT_OBJECTS = ["contacts", "companies", "deals", "tickets"]
_PAGE_SIZE = 100

# Properties to pull per object — extendable by user via meta["properties_{obj}"]
_DEFAULT_PROPS: dict[str, list[str]] = {
    "contacts": [
        "email", "firstname", "lastname", "phone", "company",
        "createdate", "lastmodifieddate", "lifecyclestage",
        "hs_lead_status", "hubspot_owner_id",
    ],
    "companies": [
        "name", "domain", "industry", "city", "country", "state",
        "numberofemployees", "annualrevenue", "createdate",
        "hs_lastmodifieddate", "hubspot_owner_id",
    ],
    "deals": [
        "dealname", "amount", "dealstage", "pipeline", "closedate",
        "createdate", "hs_lastmodifieddate", "hubspot_owner_id",
    ],
    "tickets": [
        "subject", "hs_ticket_priority", "hs_pipeline_stage",
        "createdate", "hs_lastmodifieddate", "hubspot_owner_id",
    ],
}


class HubSpotConnector(RestApiSync):
    """HubSpot CRM API v3 → DuckDB mirror."""

    def __init__(self, dsn="hubspot://", schema_name=None, connection_id="", meta=None):
        super().__init__(dsn=dsn, schema_name=schema_name, connection_id=connection_id, meta=meta)
        meta = meta or {}
        self._token = meta.get("access_token", "")
        if not self._token:
            raise ValueError("HubSpot connector requires meta['access_token']")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        })
        obj_str = meta.get("objects", "")
        self._obj_list = [o.strip() for o in obj_str.split(",") if o.strip()] or _DEFAULT_OBJECTS

    def _objects(self) -> list[str]:
        return self._obj_list

    def _get_props(self, obj: str) -> list[str]:
        key = f"properties_{obj}"
        custom = self._meta.get(key, "")
        if custom:
            return [p.strip() for p in custom.split(",") if p.strip()]
        return _DEFAULT_PROPS.get(obj, [])

    def _fetch_page(
        self,
        obj: str,
        after: str | None,
        since: datetime | None,
    ) -> tuple[list[dict], str | None]:
        props = self._get_props(obj)

        if since:
            # Use search endpoint for incremental sync
            filter_prop = "lastmodifieddate" if obj in ("contacts", "companies") else "hs_lastmodifieddate"
            payload = {
                "filterGroups": [{
                    "filters": [{
                        "propertyName": filter_prop,
                        "operator": "GTE",
                        "value": str(int(since.timestamp() * 1000)),  # milliseconds
                    }]
                }],
                "properties": props,
                "limit": _PAGE_SIZE,
            }
            if after:
                payload["after"] = after
            resp = self._session.post(
                f"{_BASE}/crm/v3/objects/{obj}/search",
                json=payload,
                timeout=30,
            )
        else:
            params: dict = {"limit": _PAGE_SIZE, "properties": ",".join(props)}
            if after:
                params["after"] = after
            resp = self._session.get(
                f"{_BASE}/crm/v3/objects/{obj}",
                params=params,
                timeout=30,
            )

        resp.raise_for_status()
        data = resp.json()

        raw_results = data.get("results", [])
        # Flatten: { id, properties: {...} } → { id, prop1, prop2, … }
        records = []
        for item in raw_results:
            flat = {"hs_object_id": item.get("id", "")}
            flat.update(item.get("properties", {}))
            records.append(flat)

        paging = data.get("paging", {})
        next_cursor = paging.get("next", {}).get("after") if paging else None
        return records, next_cursor

    def test(self) -> tuple[bool, str]:
        try:
            resp = self._session.get(f"{_BASE}/crm/v3/objects/contacts?limit=1", timeout=10)
            resp.raise_for_status()
            return True, "HubSpot connected (CRM v3 API)"
        except Exception as e:
            return False, str(e)
