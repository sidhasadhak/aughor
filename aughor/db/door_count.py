"""Which of the SQL door's methods a caller came in through — counted, so the gate map can say when each
was last used (the 2027 study §V, screen 12; decided per entry point, ROADMAP §6 item 42).

The door has ten ways in: nine methods on a connection and ``execute_guarded``. One use is counted at
the method the caller called. A door method reached through another — ``rows`` through ``execute``,
``execute_guarded`` through ``execute_bounded``, an engine's ``execute`` through the base's — is the
same use and is not counted again.

Nobody lists which connections are counted: ``DatabaseConnection`` wraps the door methods of every
class that subclasses it, so a connector written tomorrow is counted the day it exists.
"""
from __future__ import annotations

import functools
import inspect
from contextvars import ContextVar
from typing import Any, Callable

#: The door's methods on a connection. `docs/SQL_DOORS.json` is keyed by these and by `GUARDED`.
DOOR_METHODS: tuple[str, ...] = ("execute", "execute_bounded", "execute_typed", "execute_with_params",
                                 "execute_with_params_typed", "read_typed_rows", "rows", "scalar", "bulk_read")
#: The tenth way in — a function over a connection, in `aughor/sql/executor.py`.
GUARDED = "execute_guarded"
DOORS: tuple[str, ...] = (*DOOR_METHODS, GUARDED)

_in_door: ContextVar[bool] = ContextVar("aughor_in_door", default=False)


def _count(door: str) -> None:
    """One more use of ``door``. Never blocks the statement."""
    try:
        from aughor.security.audit import DoorCounter
        DoorCounter.count(door)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the door-use count is best-effort; the statement runs", counter="audit.door_count")


def counted_door(door: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """``fn`` counted as one use of ``door`` when a caller outside the door calls it."""
    @functools.wraps(fn)
    def through_the_door(*args: Any, **kwargs: Any) -> Any:
        if _in_door.get():
            return fn(*args, **kwargs)
        token = _in_door.set(True)
        try:
            _count(door)
            return fn(*args, **kwargs)
        finally:
            _in_door.reset(token)

    through_the_door.__counted_door__ = door  # type: ignore[attr-defined]
    return through_the_door


def count_the_doors(cls: type) -> None:
    """Wrap each door method ``cls`` itself defines. An abstract one is left alone — the class that
    fills it in is wrapped when it is defined."""
    for name in DOOR_METHODS:
        fn = cls.__dict__.get(name)
        if not inspect.isfunction(fn) or getattr(fn, "__counted_door__", None) \
                or getattr(fn, "__isabstractmethod__", False):
            continue
        setattr(cls, name, counted_door(name, fn))
