"""Execution-lifecycle hook registries — invert the agent's reach into query
execution and connection setup.

Two seams the platform's connection layer exposes, which the AGENT fills:

  • **post-execute** — after a (gated, audited, metered) query runs, the agent may
    react: e.g. emit an AI-column Trust-Receipt when the SQL used a governed
    ``prompt()`` / ``embedding()`` UDF. ``fn(sql, result, connection_id)``.
  • **on-connect** — when a physical DuckDB connection is opened, the agent may
    install capabilities: e.g. register the AI ``prompt()`` / ``embedding()`` UDFs
    (when ``AUGHOR_AI_SQL`` is on, and not for MotherDuck which has them natively).
    ``fn(raw_conn, *, is_motherduck=...)``.

Both run under ``tolerate`` — best-effort, never break execution or a connect. With
nothing registered they are no-ops (the platform executes and connects with zero
agent involvement), which is the plug-and-play property the boundary guarantees.
"""
from __future__ import annotations

from typing import Callable

from aughor.kernel.errors import tolerate

_POST_EXECUTE: list[tuple[str, Callable]] = []  # fn(sql, result, connection_id)
_ON_CONNECT: list[tuple[str, Callable]] = []    # fn(raw_conn, **ctx)


def register_post_execute_hook(name: str, fn: Callable) -> None:
    _POST_EXECUTE.append((name, fn))


def register_on_connect_hook(name: str, fn: Callable) -> None:
    _ON_CONNECT.append((name, fn))


def clear() -> None:
    _POST_EXECUTE.clear()
    _ON_CONNECT.clear()


def run_post_execute_hooks(sql: str, result, connection_id) -> None:
    for name, fn in list(_POST_EXECUTE):
        try:
            fn(sql, result, connection_id)
        except Exception as e:
            tolerate(e, f"post-execute hook {name!r}", counter=f"exec.post.{name}")


def run_on_connect_hooks(raw_conn, **ctx) -> None:
    for name, fn in list(_ON_CONNECT):
        try:
            fn(raw_conn, **ctx)
        except Exception as e:
            tolerate(e, f"on-connect hook {name!r}", counter=f"exec.connect.{name}")
