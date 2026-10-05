"""Aggregate priors across installs — base rates and normal ranges as aggregates only, never a
customer's claims (the 2027 study §Q and §W, phase 7, P7-5).

What an install may contribute to the ecosystem's priors is a decision the user makes, so sharing
is OFF by default behind `aggregates.share` (`AUGHOR_AGGREGATES_SHARE`): with the flag off nothing
leaves, the export door refuses and says why, and the install behaves byte for byte as before. What
the aggregate holds when a person turns it on:

- **pack records** — how often each pack's claims held on this install (counts by state);
- **base rates** — each play's learned success rate with its count (`playbook/outcomes`);
- **normal ranges** — for metrics stated as a share (ratio, percent), the band the metric's own
  history predicted and how often it held, from scored predictions; for every other unit only the
  band's RELATIVE width, never a level;
- **method backtests** — the registered methods' declared backtests.

What it never holds, held by :func:`assert_no_identifiers` and a test: a connection id, a claim's
text, an object's key, a person's name, an absolute value of a metric that is not a share. The
install is named by an anonymous stable id, so a receiver can count installs without knowing them.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
from typing import Any

FLAG = "aggregates.share"
#: Units whose level is a share, and so an aggregate, not a customer's number. `%` is NOT one: in the
#: Record it is the convention for a RELATIVE band (a change against `before`, `scenario.against_band`),
#: so a `%` prediction's band is a change, not a level, and falls under the relative-width rule.
SHARE_UNITS = frozenset({"ratio", "percent", "share", "rate"})
#: Keys that may never appear in an aggregate document.
FORBIDDEN_KEYS = frozenset({"connection_id", "conn_id", "connections", "text", "statement", "key", "about", "owner",
                            "author", "decided_by", "created_by", "org_id", "sql", "url"})


def _install_id() -> str:
    from aughor.org.context import current_org_id
    return hashlib.sha256(f"aughor-install:{current_org_id()}".encode("utf-8")).hexdigest()[:12]


def _pack_records() -> list[dict]:
    out = []
    try:
        from aughor.packs.record import measured_record
        from aughor.packs.roots import all_pack_ids
        for pid in all_pack_ids():
            rec = measured_record(pid)
            claims = rec.get("claims") or {}
            if not claims.get("measured"):
                continue
            out.append({"pack": pid, "measured": claims["measured"], "supported": claims.get("supported", 0),
                        "refuted": claims.get("refuted", 0), "held_share": claims.get("held_share")})
    except Exception as exc:  # noqa: BLE001 — a record that cannot be read is left out, said
        from aughor.kernel.errors import tolerate
        tolerate(exc, "pack records could not be read for the aggregate", counter="aggregates.packs")
    return out


def _base_rates() -> list[dict]:
    out = []
    try:
        from aughor.playbook.store import list_entries
        for e in list_entries():
            n = int(getattr(e, "outcome_n", 0) or 0)
            if n > 0:
                out.append({"play": e.id, "trigger_metric": e.trigger_metric, "rate": round(float(e.historical_success_rate), 3),
                            "n": n, "source": getattr(e, "rate_source", "")})
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "base rates could not be read for the aggregate", counter="aggregates.plays")
    return out


def _normal_ranges() -> list[dict]:
    """From scored predictions under the history method: per metric, how often the band held and
    — for a share metric — the band itself; for every other unit the band's relative width only."""
    groups: dict[str, dict] = {}
    try:
        from aughor.record import claims as C
        for c in C.list_claims(kind="prediction", state="scored", limit=5000):
            if str(c.extra.get("method") or "") != "history":
                continue
            low, high, mid = c.extra.get("low"), c.extra.get("high"), c.extra.get("mid")
            if low is None or high is None:
                continue
            unit = (c.statement.unit or "").strip().lower()
            g = groups.setdefault(c.statement.metric, {"metric": c.statement.metric, "unit": unit, "n": 0, "held": 0,
                                                       "band_low": [], "band_high": [], "relative_width": []})
            g["n"] += 1
            g["held"] += c.extra.get("scored_against") == "inside"
            if unit in SHARE_UNITS:
                g["band_low"].append(float(low)); g["band_high"].append(float(high))
            elif mid not in (None, 0):
                g["relative_width"].append(abs(float(high) - float(low)) / abs(float(mid)))
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "normal ranges could not be read for the aggregate", counter="aggregates.ranges")
    out = []
    for g in groups.values():
        row = {"metric": g["metric"], "unit": g["unit"], "n": g["n"], "coverage_observed": round(g["held"] / g["n"], 3) if g["n"] else None}
        if g["band_low"]:
            row["band"] = {"low": round(min(g["band_low"]), 6), "high": round(max(g["band_high"]), 6), "note": "a share; the band itself"}
        elif g["relative_width"]:
            row["relative_width"] = round(sum(g["relative_width"]) / len(g["relative_width"]), 4)
            row["note"] = "not a share: the band's relative width only, never a level"
        out.append(row)
    return sorted(out, key=lambda r: r["metric"])


def _method_backtests() -> list[dict]:
    try:
        from aughor.record.methods import list_methods
        return [{"method": m.name, "kind": m.kind, "backtest": m.backtest.model_dump()} for m in list_methods()]
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "method backtests could not be read for the aggregate", counter="aggregates.methods")
        return []


def compute() -> dict[str, Any]:
    """This install's aggregate — computed locally, readable by the install whether or not it shares."""
    doc = {"install": _install_id(), "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(), "version": "2027.1",
           "pack_records": _pack_records(), "base_rates": _base_rates(), "normal_ranges": _normal_ranges(),
           "method_backtests": _method_backtests(),
           "never_includes": ["a connection id", "a claim's text", "an object's key", "a person's name",
                              "an absolute value of a metric that is not a share"]}
    assert_no_identifiers(doc)
    return doc


def assert_no_identifiers(doc: Any, path: str = "") -> None:
    """Refuse a document that carries a forbidden key anywhere — the rule, enforced on every compute."""
    if isinstance(doc, dict):
        for k, v in doc.items():
            if str(k) in FORBIDDEN_KEYS:
                raise ValueError(f"the aggregate carries {k!r} at {path or '/'}; an aggregate never names a customer's data")
            assert_no_identifiers(v, f"{path}/{k}")
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            assert_no_identifiers(v, f"{path}[{i}]")


def sharing_enabled() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def export() -> dict[str, Any]:
    """The document that may leave the install — only when a person turned sharing on."""
    if not sharing_enabled():
        raise PermissionError(f"sharing aggregates is off ({FLAG}, AUGHOR_AGGREGATES_SHARE): the user's call — nothing leaves "
                              "this install until a person turns it on; the aggregate can still be read here")
    return {**compute(), "shareable": True}
