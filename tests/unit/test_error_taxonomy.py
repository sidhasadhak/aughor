"""R3 — the typed SQL-error taxonomy (the Verifier's signal that routes repair).
Covers DuckDB (prefixed), Postgres, and SQLite error shapes."""
from aughor.sql.writer import FixResult
from aughor.tools.error_classifier import (
    SqlErrorClass,
    classify_error_type,
    error_class_guidance,
)


def test_ok_when_no_error():
    assert classify_error_type(None) == SqlErrorClass.OK
    assert classify_error_type("") == SqlErrorClass.OK


def test_parser():
    assert classify_error_type('Parser Error: syntax error at or near "FROM"') == SqlErrorClass.PARSER
    assert classify_error_type('syntax error at or near ")"') == SqlErrorClass.PARSER
    assert classify_error_type('near "SELEC": syntax error') == SqlErrorClass.PARSER


def test_binder():
    assert classify_error_type('Binder Error: Referenced column "revenue" not found') == SqlErrorClass.BINDER
    assert classify_error_type('column "foo" does not exist') == SqlErrorClass.BINDER
    assert classify_error_type("no such column: bar") == SqlErrorClass.BINDER
    assert classify_error_type('column "x" must appear in the GROUP BY clause') == SqlErrorClass.BINDER
    assert classify_error_type("Catalog Error: Table with name orders does not exist") == SqlErrorClass.BINDER
    assert classify_error_type("ambiguous column name: id") == SqlErrorClass.BINDER


def test_semantic():
    assert classify_error_type("Conversion Error: Could not convert string 'x' to INT64") == SqlErrorClass.SEMANTIC
    assert classify_error_type("invalid input syntax for type numeric") == SqlErrorClass.SEMANTIC
    # a function *signature* mismatch is semantic even though it says "does not exist"
    assert classify_error_type("function round(double precision) does not exist") == SqlErrorClass.SEMANTIC


def test_runtime():
    assert classify_error_type("division by zero") == SqlErrorClass.RUNTIME
    assert classify_error_type("Out of Range Error: overflow") == SqlErrorClass.RUNTIME


def test_operator_mismatch_is_semantic_not_binder():
    # 'does not exist' alone would be binder; the operator type-mismatch must win
    # (order of checks puts semantic first), or the fixer would re-link columns in vain.
    assert classify_error_type("operator does not exist: integer + text") == SqlErrorClass.SEMANTIC


def test_guidance_is_type_specific():
    assert "syntax" in error_class_guidance(SqlErrorClass.PARSER)
    assert "do not invent names" in error_class_guidance(SqlErrorClass.BINDER)
    assert "Cast" in error_class_guidance(SqlErrorClass.SEMANTIC)
    assert "NULLIF" in error_class_guidance(SqlErrorClass.RUNTIME)
    assert error_class_guidance(SqlErrorClass.OK) == ""


def test_fixresult_carries_error_class():
    assert FixResult(ok=True, sql="SELECT 1").error_class == ""
    assert FixResult(ok=False, sql="x", error_class="binder").error_class == "binder"
