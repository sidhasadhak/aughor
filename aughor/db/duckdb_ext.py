"""DuckDB extension directories on a filesystem with no writable home.

DuckDB resolves the *home* directory (where `~/.duckdb` lives) BEFORE it consults
`extension_directory`, so on a serverless host — $HOME unset, or set to a path on a
read-only layer — every INSTALL dies with::

    IO Error: Can't find the home directory at ''
    Specify a home directory using the SET home_directory='/path/to/dir' option.

Measured 2026-09-07 against duckdb 1.5.2 with HOME removed: `extension_directory`
alone STILL fails; `home_directory` is the setting that matters. The 2026-09-06 fix
set only the former, which is why a Vercel deployment kept failing while the unit
test that "proved" the fix passed — it asserted the setting, not the install.

On a host whose home IS writable this is a deliberate no-op: the settings stay at
their defaults so the shared `~/.duckdb` extension cache keeps being reused. A
laptop and CI must not start re-downloading extensions (nor need network to run
the suite) just because serverless needs a different directory.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

#: Where extensions land when the real home is unusable. A subdirectory rather than
#: the bare temp dir, so the cache is identifiable and cheap to clear.
_EXT_SUBDIR = "aughor_duckdb_ext"


def _home_is_writable() -> bool:
    """True when DuckDB's default `~/.duckdb` can actually be created.

    This mirrors DuckDB's OWN resolution, which reads the environment and nothing
    else. Python's `os.path.expanduser` is more generous — with HOME unset it falls
    back to the passwd database and happily returns a real directory — so using it
    here reported "home is fine" on exactly the hosts where DuckDB reports
    ``Can't find the home directory at ''``. Env only, deliberately.
    """
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE") or ""
    return bool(home) and os.path.isdir(home) and os.access(home, os.W_OK)


def fallback_home() -> str | None:
    """The directory to use as DuckDB's home, or None when the real home works."""
    return None if _home_is_writable() else tempfile.gettempdir()


def prepare_extensions(con) -> None:
    """Make `con` able to INSTALL when the host has no writable home.

    Call immediately before any ``INSTALL``. Idempotent and cheap. Best-effort by
    design: if the SET itself fails, the caller's INSTALL raises DuckDB's own error,
    which says more than anything this function could invent.
    """
    home = fallback_home()
    if home is None:
        return
    try:
        con.execute(f"SET home_directory='{home}'")
        con.execute(f"SET extension_directory='{Path(home) / _EXT_SUBDIR}'")
    except Exception:
        logger.debug("duckdb extension directories not settable", exc_info=True)
