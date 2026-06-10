"""Connection convenience adapters db.rows() / db.scalar() — see DatabaseConnection (C3).
Replace the ad-hoc execute→check-error→pull-rows wrappers; best-effort ([]/None on error)."""
from aughor.db.connection import DatabaseConnection


class _Res:
    def __init__(self, rows, error=None):
        self.rows = rows
        self.error = error


class _Conn:
    """A minimal connection: implements execute() and inherits the C3 adapters."""
    def __init__(self, rows, error=None):
        self._r = _Res(rows, error)
    def execute(self, label, sql):
        return self._r
    rows = DatabaseConnection.rows
    scalar = DatabaseConnection.scalar


def test_rows_returns_rows():
    assert _Conn([(1, 2), (3, 4)]).rows("x") == [(1, 2), (3, 4)]


def test_rows_empty_on_error():
    assert _Conn([], error="boom").rows("x") == []


def test_rows_empty_on_none():
    assert _Conn(None).rows("x") == []


def test_scalar_float_default():
    assert _Conn([(42,)]).scalar("x") == 42.0


def test_scalar_cast_int():
    assert _Conn([(42,)]).scalar("x", cast=int) == 42


def test_scalar_dict_row():
    assert _Conn([{"c": 17}]).scalar("x") == 17.0


def test_scalar_none_on_empty():
    assert _Conn([]).scalar("x") is None


def test_scalar_none_on_null_cell():
    assert _Conn([(None,)]).scalar("x") is None


def test_scalar_none_on_uncastable():
    assert _Conn([("abc",)]).scalar("x", cast=float) is None
