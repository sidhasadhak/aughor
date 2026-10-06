"""The briefing, as grounding context for a question asked *about* it.

"Ask this briefing" is a follow-up on an artifact the user is looking at — the verdict, the
findings behind it, the synthesis prose. Without that context the model answers as if the
question arrived cold, so "why is that?" or "break that down" has no referent.

The block is built SERVER-SIDE from the cached brief rather than posted up by the client. Three
reasons, all of which matter more than the small amount of plumbing it saves:

* **One artifact.** The answer is grounded in exactly the brief on screen — the same
  `conn:schema` cache entry the Briefing rendered — instead of whatever subset a component
  happened to serialize. The old ask box sent five lines: theme, headline, three findings.
* **No drift.** A client-assembled blob is a second, silently-diverging copy of the brief.
* **No prose on the wire** every turn, and nothing a caller can spoof into the prompt.

Bounded on purpose: a brief can carry dozens of findings, and this rides in front of a QUICK
answer. Caps below keep it to roughly a screenful.
"""
from __future__ import annotations

import re
from typing import Any

# A brief's verdict + a handful of its cited findings is the useful part; the long tail is
# already reachable by asking. These bound the prompt cost of every single ask.
MAX_CITATIONS = 8
MAX_FINDING_CHARS = 260
MAX_NARRATIVE_CHARS = 1200
MAX_MEASURED = 12
MAX_KEY_METRICS = 8
MAX_METRIC_SQL_CHARS = 400

#: The ``surface`` the Briefing's own ask panel sends (`web/components/brief/BriefAskPanel.tsx`).
BRIEFING_SURFACE = "briefing"

#: A range Briefing's own cache key under its scope (`briefing/ranges.RangeSpec.key`), e.g.
#: ``range:last_month:2026-08-01..2026-08-31``. Anything else is refused rather than read: the
#: key is joined into a cache key, and a caller must not be able to walk the store with it.
PERIOD_KEY = re.compile(r"^range:[a-z_]+:\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}$")


def _period_lines(period: dict[str, Any]) -> list[str]:
    """What the Briefing in view covers, said once, so "this month" and "the drop" in a question
    resolve to the window on screen rather than to whatever window the SQL writer guesses."""
    covers = str(period.get("covers") or "").strip()
    if not covers:
        return []
    label = str(period.get("label") or "").strip()
    line = f"PERIOD: the {label.lower() + ' ' if label else ''}Briefing for {covers}"
    compared = str(period.get("compared_with") or "").strip()
    if compared:
        line += f", compared with {compared}"
    if period.get("start") and period.get("end"):
        line += f" (dates from {period['start']} up to but not including {period['end']})"
    as_of = str(period.get("as_of") or "").strip()
    lag = period.get("lag_days")
    if as_of:
        line += f"; read as of {as_of}"
    if isinstance(lag, int) and lag > 0:
        line += f", and the newest {lag} days of data are not settled yet"
    out = [line + "."]
    moving = [str(t) for t in (period.get("still_moving") or []) if str(t).strip()]
    if moving:
        out.append(f"STILL MOVING (figures from these may change): {', '.join(moving[:8])}")
    return out


def _figure(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else f"{value:,}"
    return str(value)


def _measured_lines(period: dict[str, Any]) -> list[str]:
    """The headline metrics the Briefing measured for its window, as it showed them — and the
    ones it could not measure, with why, so a question about one is not answered as if it
    had a figure."""
    out: list[str] = []
    measured = [m for m in (period.get("measured") or []) if isinstance(m, dict)]
    if measured:
        out.append("MEASURED FOR THIS PERIOD (as the Briefing shows them):")
        for m in measured[:MAX_MEASURED]:
            text = f"  - {m.get('name') or m.get('metric')}: {_figure(m.get('current'))}"
            if m.get("previous") is not None:
                text += f" (previous period {_figure(m.get('previous'))}"
                rel = m.get("rel")
                text += f", {rel * 100:+.1f}%)" if isinstance(rel, (int, float)) else ")"
            if m.get("status"):
                text += f" [{m['status']}]"
            out.append(text)
    unmeasured = [u for u in (period.get("unmeasured") or []) if isinstance(u, dict)]
    if unmeasured:
        out.append("NOT MEASURED FOR THIS PERIOD (no figure on screen, and why):")
        for u in unmeasured[:MAX_MEASURED]:
            out.append(f"  - {u.get('name')}: {u.get('reason')}")
    return out


def _key_metric_lines(key_metrics: list[dict[str, Any]] | None) -> list[str]:
    """The Briefing's Key Metrics tiles, by definition. The tiles are computed in the browser
    from the business profile's own SQL, so the figures are not on the server — but how each is
    computed is, and a question about a tile should measure it the way the tile does."""
    rows = [k for k in (key_metrics or []) if isinstance(k, dict) and k.get("name")]
    if not rows:
        return []
    out = ["KEY METRICS ON THE PAGE (each tile's own definition — measure a tile this way):"]
    for k in rows[:MAX_KEY_METRICS]:
        sql = " ".join(str(k.get("value_sql") or "").split())
        if len(sql) > MAX_METRIC_SQL_CHARS:
            sql = sql[:MAX_METRIC_SQL_CHARS] + "…"
        out.append(f"  - {k['name']}" + (f": {sql}" if sql else ""))
    return out


def build_brief_block(brief: dict[str, Any] | None, *,
                      key_metrics: list[dict[str, Any]] | None = None) -> str:
    """A prompt block describing the brief in view, or "" when there is nothing to say.

    Empty is the honest default: no brief cached for this scope means the user is not looking
    at one, and inventing context would be worse than having none. A RANGE Briefing whose
    period was built but quiet still says its period and what it measured — the reader is
    looking at that window."""
    if not isinstance(brief, dict):
        return ""
    theme = (brief.get("headline_theme") or "").strip()
    narrative = (brief.get("narrative") or "").strip()
    citations = brief.get("citations") or []
    period = brief.get("period") if isinstance(brief.get("period"), dict) else {}
    period_lines = _period_lines(period) if period else []
    measured_lines = _measured_lines(period) if period else []
    if not (theme or narrative or citations or period_lines):
        return ""

    lines: list[str] = [
        "THE BRIEFING THE USER IS LOOKING AT — the question is most likely ABOUT this.",
        "Use it to resolve references ('that', 'the drop', 'those brands') and to stay on the",
        "same entities and time window. It is CONTEXT, not a source of numbers: every figure",
        "in your answer must still come from the query you run.",
        "",
    ]
    lines += period_lines
    if period_lines and not (theme or narrative):
        lines.append("No narrative was written for this period; only its figures below are on screen.")
    if theme:
        lines.append(f"VERDICT: {theme}")
    if narrative:
        text = narrative[:MAX_NARRATIVE_CHARS]
        if len(narrative) > MAX_NARRATIVE_CHARS:
            text += "…"
        lines.append(f"SYNTHESIS: {text}")
    if citations:
        lines.append("FINDINGS IT CITES:")
        for c in citations[:MAX_CITATIONS]:
            if not isinstance(c, dict):
                continue
            finding = (c.get("finding") or "").strip()
            if not finding:
                continue
            if len(finding) > MAX_FINDING_CHARS:
                finding = finding[:MAX_FINDING_CHARS] + "…"
            domain = (c.get("domain") or "").strip()
            lines.append(f"  - {f'[{domain}] ' if domain else ''}{finding}")
    lines += measured_lines
    lines += _key_metric_lines(key_metrics)
    lines.append("")
    return "\n".join(lines)


def _key_metrics(connection_id: str, schema: str | None) -> list[dict[str, Any]]:
    """The Key Metrics tiles' definitions: the business profile's north-star metrics with SQL,
    the same list `IndustryKpiStrip` measures. Read-only; [] when there is no profile."""
    try:
        from aughor.business_profile import store as _pstore
        profile = _pstore.load(connection_id, schema)
    except Exception:  # noqa: BLE001 — the tiles are context; their absence is not an error
        return []
    metrics = getattr(profile, "north_star_metrics", None) if profile is not None else None
    if metrics is None and isinstance(profile, dict):
        metrics = profile.get("north_star_metrics")
    out = []
    for m in metrics or []:
        name = getattr(m, "name", None) if not isinstance(m, dict) else m.get("name")
        sql = getattr(m, "value_sql", None) if not isinstance(m, dict) else m.get("value_sql")
        if name and str(sql or "").strip():
            out.append({"name": str(name), "value_sql": str(sql)})
    return out


def brief_block_for_scope(connection_id: str, schema: str | None, canvas_id: str | None = None,
                          *, period_key: str = "", from_briefing: bool = False) -> str:
    """The brief block for a (connection, schema) or canvas — "" when none is cached.

    Mirrors the scope key the briefing route stamps, so the ask is grounded in the SAME entry
    the user is reading and can never pick up a different schema's brief. ``period_key`` is
    the range Briefing the user has open: a range Briefing is cached under
    ``<scope>#<period key>``, and without it the ask read the standing entry — a different
    Briefing from the one on screen, or none at all (`workspace:uber_ncr` had only range
    entries, 2026-10-07). ``from_briefing`` is set when the question was asked FROM the Briefing:
    only then are the Key Metrics tiles on the page, so only then are they described — every
    other quick answer in the scope gets the block exactly as before."""
    from aughor.knowledge.briefing import peek_briefing, peek_entry

    scope_key = f"canvas:{canvas_id}" if canvas_id else (
        f"{connection_id}:{schema}" if schema else connection_id
    )
    key_metrics = _key_metrics(connection_id, schema) if (from_briefing and not canvas_id) else []
    period_key = (period_key or "").strip()
    if period_key and PERIOD_KEY.match(period_key):
        entry = peek_entry(f"{scope_key}#{period_key}")
        if entry is None:
            # Said, never implied: the user has a period open that has no Briefing built.
            return ("THE BRIEFING THE USER IS LOOKING AT has not been built for the period they "
                    f"have open ({period_key}); there is no verdict or finding on screen to refer to.\n")
        return build_brief_block(entry, key_metrics=key_metrics)
    return build_brief_block(peek_briefing(scope_key), key_metrics=key_metrics)
