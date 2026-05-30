"""
Unit test: verify the explorer _save_state recursion bug is fixed.

Before the fix (R1a), _save_state() called itself when canvas_id was None:
    def _save_state(self):
        if self.canvas_id:
            _store.save_canvas(...)
        else:
            self._save_state()   ← infinite recursion → stack overflow

After the fix:
        else:
            _store.save(self.connection_id, self._state)
"""
from __future__ import annotations

import inspect


def test_save_state_does_not_call_itself() -> None:
    """_save_state must not contain a recursive self._save_state() call."""
    from aughor.explorer.agent import SchemaExplorer
    source = inspect.getsource(SchemaExplorer._save_state)
    assert "self._save_state()" not in source, (
        "SchemaExplorer._save_state() still contains a recursive call — "
        "R1a recursion fix was reverted or not applied."
    )


def test_save_state_calls_store_save_for_connection() -> None:
    """Without canvas_id, _save_state must delegate to _store.save()."""
    from aughor.explorer.agent import SchemaExplorer
    source = inspect.getsource(SchemaExplorer._save_state)
    assert "_store.save(" in source, (
        "Expected _store.save(connection_id, ...) in the else branch of _save_state."
    )
