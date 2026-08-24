"""Which connections a pack applies to — the field that was declared and never read.

`pack.yaml` has carried `scope: {connections: [...]}` since P0. `PackManifest` declares
it, `validate` warns when it is missing, and **nothing anywhere read it**. Every pack was
offered to every connection no matter what it said, so the field documented an intent the
product did not have.

That was invisible while every pack was authored here and general. It stopped being
invisible when engine packs arrived: a Bigtable pack and a BigQuery pack both say `['*']`,
so both are equally reachable from a DuckDB question, and the roster a model reads cannot
tell it which of them has anything to do with the warehouse in front of it. Prose that
cannot apply is not neutral — it is a plausible-sounding recipe for a system the reader
is not connected to.

The vocabulary, matched case-insensitively:

* ``*``                  — every connection. The default, and what every pack on disk says today.
* ``engine:<conn_type>`` — every connection of that connector type, e.g. ``engine:bigquery``.
* ``<connection_id>``    — that one connection.

Three decisions shape this file:

**One matcher, not one per surface.** The pack ROOT path was written out three times before
`roots.py` collected it, and they agreed only by luck. A scope rule read one way by the tool
loop and another way by the steering path would be the same bug with a worse blast radius —
the disagreement would be about what a model is allowed to read.

**An empty list matches nothing, and saying so is the point.** A missing `scope` gets the
model default (`['*']`); only an explicit `connections: []` is empty, which can only mean
"no connection". Reading it as "all" — the tempting lenient default — would turn the one
unambiguous way to say *nothing* into its opposite, silently, on a gate that governs prompt
content. `validate` warns and `promote` refuses, so it is loud rather than quiet.

**An unresolvable connection is not a match for an engine-scoped pack.** When the connector
type cannot be determined, `*` still applies (it claims nothing about the engine) and an
`engine:` entry does not. The alternative — assume it matches — fails open on exactly the
question this module exists to answer.
"""
from __future__ import annotations

from typing import Iterable, Optional

#: Everything matches this one.
ANY = "*"

#: Prefix marking an entry as a connector TYPE rather than a connection id.
ENGINE_PREFIX = "engine:"


def entries(manifest_scope: Optional[dict]) -> list[str]:
    """The scope entries as a normalised list of lowercase strings.

    A missing key, a null value, or a non-mapping `scope` all mean "not stated", which is
    `['*']` — the same answer `PackManifest` gives when the key is absent, so a pack that
    omits `scope` and one that omits `connections` are not two different packs.
    """
    if not isinstance(manifest_scope, dict) or "connections" not in manifest_scope:
        return [ANY]
    raw = manifest_scope.get("connections")
    if raw is None:
        return [ANY]
    if isinstance(raw, str):                       # `connections: bigquery` — a scalar, not a list
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return [ANY]
    return [str(e).strip().lower() for e in raw if str(e).strip()]


def is_engine_entry(entry: str) -> bool:
    return entry.startswith(ENGINE_PREFIX)


def engine_of(entry: str) -> str:
    """The connector type named by an `engine:` entry ('' for any other entry)."""
    return entry[len(ENGINE_PREFIX):].strip() if is_engine_entry(entry) else ""


def known_engines() -> set[str]:
    """Connector types an `engine:` entry may legally name.

    Spans the registry AND the three types the product opens without going through it
    (`duckdb`, `postgres`, `aughor_ops`) — a scope that named `engine:postgres` and was
    rejected as unknown would be the connector list's gap showing up as a pack author's
    error.
    """
    out = {"duckdb", "postgres", "aughor_ops"}
    try:
        from aughor.connectors.registry import REGISTRY, DSN_PREVIEWS
        out |= set(REGISTRY.supported_types())
        out |= set(DSN_PREVIEWS)
    except Exception as exc:
        # A connector registry that will not import must not make every scope unreadable,
        # but it does make this answer narrower than it should be — and a narrower answer
        # here reads as "that engine does not exist", which is the wrong refusal.
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the connector registry is unreadable; only the built-in engine "
                      "names are known", counter="packs.scope_known_engines")
    return out


def unknown_engines(scope_entries: Iterable[str]) -> list[str]:
    """Engine names in these entries that no connector type answers to.

    A typo (`engine:bigqeury`) is indistinguishable at match time from a correct entry for
    an engine nobody is connected to: both simply never match. This is what lets the
    activation gate tell them apart.
    """
    known = known_engines()
    return [e for entry in scope_entries
            if (e := engine_of(entry)) and e not in known]


def matches(scope_entries: Iterable[str], *, connection_id: str = "",
            conn_type: str = "") -> bool:
    """Does a pack with these entries apply to this connection?

    `conn_type` empty means "could not be determined" — see the module docstring for why
    that is a non-match for an `engine:` entry rather than a match.
    """
    cid = (connection_id or "").strip().lower()
    ctype = (conn_type or "").strip().lower()
    for entry in scope_entries:
        if entry == ANY:
            return True
        if is_engine_entry(entry):
            if ctype and engine_of(entry) == ctype:
                return True
            continue
        if cid and entry == cid:
            return True
    return False


def conn_type_of(connection_id: str) -> str:
    """The connector type for a connection id, or '' when it cannot be read.

    Best-effort by design: this is called to decide what a roster shows, and a registry
    that cannot be opened must degrade to "unknown engine", never take the roster down.
    """
    if not connection_id:
        return ""
    try:
        from aughor.db.registry import get_conn_type
        return get_conn_type(connection_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "an unreadable connection type means 'unknown', not a failed roster",
                 counter="packs.scope_conn_type")
        return ""


def lazy_conn_type(connection_id: str):
    """A memoised zero-argument reader of this connection's type.

    For a caller looping over every installed pack. The lookup opens the connection
    registry, and today EVERY pack on disk is scoped `['*']` — which needs no lookup at
    all — so resolving eagerly would add a store read to every roster and every plan for
    an answer nothing asked for. Memoised rather than cached globally on purpose: a
    process-lifetime cache of connection ids is the shape that has made this repo's
    registry non-hermetic in tests before.
    """
    box: list[str] = []

    def read() -> str:
        if not box:
            box.append(conn_type_of(connection_id))
        return box[0]

    return read


def applies(pack, connection_id: str = "", conn_type: Optional[str] = None) -> bool:
    """Does this pack apply to this connection? `conn_type` is looked up when not given."""
    ents = entries(pack.manifest.scope)
    if ANY in ents:                                # the common case; skip the lookup entirely
        return True
    ctype = conn_type if conn_type is not None else conn_type_of(connection_id)
    return matches(ents, connection_id=connection_id, conn_type=ctype or "")


def filter_applicable(packs: Iterable, connection_id: str) -> list:
    """The packs that apply to this connection, resolving the connector type at most once.

    The lookup is deferred until a pack actually asks about the engine, because the
    all-`*` case — every pack on disk today — can be answered without touching the
    connection registry at all.
    """
    read = lazy_conn_type(connection_id)
    out = []
    for pack in packs:
        ents = entries(pack.manifest.scope)
        if ANY in ents or matches(ents, connection_id=connection_id, conn_type=read()):
            out.append(pack)
    return out


def label(scope_entries: Iterable[str]) -> str:
    """A one-line reading of a scope, for a surface that must explain a refusal."""
    ents = list(scope_entries)
    if not ents:
        return "no connection"
    if ANY in ents:
        return "any connection"
    engines = [engine_of(e) for e in ents if is_engine_entry(e)]
    ids = [e for e in ents if not is_engine_entry(e)]
    parts = []
    if engines:
        parts.append(f"{', '.join(engines)} connections")
    if ids:
        parts.append(f"connection {', '.join(ids)}")
    return " and ".join(parts)
