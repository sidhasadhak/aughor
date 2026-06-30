"""Salesforce CRM connector — Accounts, Contacts, Opportunities, Leads, Cases → DuckDB.

Uses SOQL REST API (no Bulk API dependency). For initial syncs > 100k records,
consider using the Bulk 2.0 API endpoint — this implementation uses the
standard query endpoint with pagination which works for most mid-market orgs.

DSN:   salesforce://  (sentinel)
Meta:  {"username": "…", "password": "…", "security_token": "…",
        "domain": "login",  (or "test" for sandbox)
        "objects": "Account,Contact,Opportunity"}

Optional dep:  none — uses requests (oauth via username+password+token flow)

Auth flow: username + password + security_token → OAuth session token via
  POST https://{domain}.salesforce.com/services/oauth2/token
  grant_type=password, client_id=salesforce, client_secret=salesforce
  (Uses the built-in connected app — no custom app needed for user/pass flow)
"""
from __future__ import annotations

from datetime import datetime

import requests

from aughor.connectors.api.base_sync import RestApiSync

_LOGIN_URL = "https://{domain}.salesforce.com/services/oauth2/token"
_DEFAULT_OBJECTS = ["Account", "Contact", "Opportunity", "Lead", "Case"]
_PAGE_SIZE = 200

# SOQL field lists per object
_DEFAULT_FIELDS: dict[str, list[str]] = {
    "Account":     ["Id", "Name", "Type", "Industry", "AnnualRevenue",
                    "NumberOfEmployees", "BillingCountry", "CreatedDate", "LastModifiedDate"],
    "Contact":     ["Id", "FirstName", "LastName", "Email", "Phone",
                    "AccountId", "Title", "Department", "CreatedDate", "LastModifiedDate"],
    "Opportunity": ["Id", "Name", "StageName", "Amount", "CloseDate",
                    "Probability", "AccountId", "OwnerId", "Type", "CreatedDate", "LastModifiedDate"],
    "Lead":        ["Id", "FirstName", "LastName", "Email", "Company",
                    "Status", "LeadSource", "Industry", "CreatedDate", "LastModifiedDate"],
    "Case":        ["Id", "Subject", "Status", "Priority", "Type",
                    "AccountId", "ContactId", "CreatedDate", "LastModifiedDate"],
}


class SalesforceConnector(RestApiSync):
    """Salesforce REST API → DuckDB mirror via SOQL."""

    def __init__(self, dsn="salesforce://", schema_name=None, connection_id="", meta=None):
        super().__init__(dsn=dsn, schema_name=schema_name, connection_id=connection_id, meta=meta)
        meta = meta or {}
        self._username       = meta.get("username", "")
        self._password       = meta.get("password", "")
        self._security_token = meta.get("security_token", "")
        self._domain         = meta.get("domain", "login")

        for required in ("username", "password", "security_token"):
            if not meta.get(required):
                raise ValueError(f"Salesforce connector requires meta['{required}']")

        self._session        = requests.Session()
        self._instance_url   = ""
        self._access_token   = ""
        obj_str = meta.get("objects", "")
        self._obj_list = [o.strip() for o in obj_str.split(",") if o.strip()] or _DEFAULT_OBJECTS
        self._authenticate()

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _authenticate(self) -> None:
        url = _LOGIN_URL.format(domain=self._domain)
        resp = requests.post(url, data={
            "grant_type":    "password",
            "client_id":     "3MVG9pe2TCblY4PfWPBQ7bW29PtGOy3FDHnSfMVAJBSJsX5EB8YdmqTK7LwJFYJLSrU9C6LB0KkKyE2bCPSf",  # public Workbench client
            "client_secret": "3034636088027943816",
            "username":      self._username,
            "password":      self._password + self._security_token,
        }, timeout=30)
        if not resp.ok:
            raise ConnectionError(f"Salesforce auth failed: {resp.json().get('error_description', resp.text)}")
        data = resp.json()
        self._access_token  = data["access_token"]
        self._instance_url  = data["instance_url"]
        self._session.headers.update({
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type":  "application/json",
        })

    def _soql(self, query: str, next_url: str | None = None) -> tuple[list[dict], str | None]:
        if next_url:
            resp = self._session.get(f"{self._instance_url}{next_url}", timeout=60)
        else:
            resp = self._session.get(
                f"{self._instance_url}/services/data/v59.0/query",
                params={"q": query}, timeout=60,
            )
        if resp.status_code == 401:
            self._authenticate()
            resp = self._session.get(
                f"{self._instance_url}/services/data/v59.0/query",
                params={"q": query}, timeout=60,
            )
        resp.raise_for_status()
        data = resp.json()
        records = [{k: v for k, v in r.items() if k != "attributes"} for r in data.get("records", [])]
        next_url = data.get("nextRecordsUrl")
        return records, next_url

    # ── RestApiSync contract ───────────────────────────────────────────────────

    def _objects(self) -> list[str]:
        return self._obj_list

    def _fetch_page(
        self,
        obj: str,
        after: str | None,
        since: datetime | None,
    ) -> tuple[list[dict], str | None]:
        fields = _DEFAULT_FIELDS.get(obj, ["Id", "Name", "CreatedDate", "LastModifiedDate"])
        field_str = ", ".join(fields)
        query = f"SELECT {field_str} FROM {obj}"
        if since:
            ts = since.strftime("%Y-%m-%dT%H:%M:%SZ")
            query += f" WHERE LastModifiedDate > {ts} ORDER BY LastModifiedDate ASC"
        query += f" LIMIT {_PAGE_SIZE}"
        if after:
            # SOQL uses OFFSET for simple pagination (Salesforce doesn't have cursor-based for REST)
            try:
                offset = int(after)
                query += f" OFFSET {offset}"
            except ValueError:
                # `after` is a nextRecordsUrl — use it directly
                return self._soql(query, next_url=after)
        records, next_url = self._soql(query)
        # next_cursor = nextRecordsUrl or offset-based
        next_cursor = next_url if next_url else None
        return records, next_cursor

    # ── Test ──────────────────────────────────────────────────────────────────

    def test(self) -> tuple[bool, str]:
        try:
            resp = self._session.get(
                f"{self._instance_url}/services/data/v59.0/limits",
                timeout=10,
            )
            resp.raise_for_status()
            daily = resp.json().get("DailyApiRequests", {})
            remaining = daily.get("Remaining", "?")
            max_req = daily.get("Max", "?")
            return True, f"Salesforce connected @ {self._instance_url} — API calls: {remaining}/{max_req} remaining today"
        except Exception as e:
            return False, str(e)
