"""SQL utilities package.

Individual modules are imported on demand so that lint/inspect can be used
without pulling in the heavy LLM dependency chain (instructor, openai, etc.).
"""
from __future__ import annotations

# Re-export writer symbols lazily so existing 'from aughor.sql import SqlWriter'
# imports keep working, but the heavy import only happens on first access.
import importlib

class _LazyWriter:
    __slots__ = ()
    def __getattr__(self, name: str):
        mod = importlib.import_module('aughor.sql.writer')
        return getattr(mod, name)

# Module-level singleton so 'from aughor.sql import SqlWriter' works
_writer = _LazyWriter()
SqlWriter = _writer.SqlWriter
FixResult = _writer.FixResult

__all__ = ['SqlWriter', 'FixResult']
