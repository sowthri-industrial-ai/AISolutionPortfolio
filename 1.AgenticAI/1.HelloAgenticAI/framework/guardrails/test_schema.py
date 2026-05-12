"""Unit tests for the schema gate (validate_schema + SchemaValidationError).

The schema gate is pure Pydantic — no Azure calls, no I/O — so the tests
are equally pure. The integration with the agent runtime (retry + emit
SCHEMA_VALIDATION_FAILED) is tested in :mod:`framework.agents.test_base`.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field, ValidationError

from framework.guardrails.schema import SchemaValidationError, validate_schema


class _Plan(BaseModel):
    goal: str = Field(min_length=1)
    steps: list[str]


# ---------- validate_schema ----------


def test_validate_schema_accepts_dict_payload() -> None:
    out = validate_schema({"goal": "buy fruit", "steps": ["a", "b"]}, _Plan)
    assert isinstance(out, _Plan)
    assert out.goal == "buy fruit"
    assert out.steps == ["a", "b"]


def test_validate_schema_accepts_json_string() -> None:
    out = validate_schema('{"goal": "g", "steps": ["x"]}', _Plan)
    assert out.goal == "g"
    assert out.steps == ["x"]


def test_validate_schema_raises_on_missing_field() -> None:
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_schema({"steps": ["a"]}, _Plan)
    assert excinfo.value.model is _Plan
    assert "goal" in str(excinfo.value)


def test_validate_schema_raises_on_invalid_field_value() -> None:
    with pytest.raises(SchemaValidationError):
        validate_schema({"goal": "", "steps": ["a"]}, _Plan)


def test_validate_schema_raises_on_malformed_json() -> None:
    with pytest.raises(SchemaValidationError):
        validate_schema("not json", _Plan)


# ---------- SchemaValidationError ----------


def test_schema_validation_error_preserves_cause() -> None:
    """The wrapped ValidationError is reachable via ``.cause`` so the
    retry helper can extract structured Pydantic error detail."""
    try:
        validate_schema({"goal": "g"}, _Plan)  # missing steps
    except SchemaValidationError as exc:
        assert exc.cause is not None
        assert isinstance(exc.cause, ValidationError)
        assert exc.model is _Plan
        assert exc.reason is None
    else:
        pytest.fail("expected SchemaValidationError")


def test_schema_validation_error_reason_only_construction() -> None:
    """Phase-4 path: chat_structured raises this with a reason string when
    the OpenAI SDK returns parsed=None. No underlying ValidationError exists."""
    exc = SchemaValidationError(_Plan, reason="parsed=None after 3 attempt(s)")
    assert exc.model is _Plan
    assert exc.cause is None
    assert exc.reason == "parsed=None after 3 attempt(s)"
    assert "parsed=None" in str(exc)


def test_schema_validation_error_requires_cause_or_reason() -> None:
    """Defence: at least one of ``cause`` or ``reason`` must be supplied,
    else the exception carries no detail and is impossible to debug."""
    with pytest.raises(ValueError, match="requires either"):
        SchemaValidationError(_Plan)
