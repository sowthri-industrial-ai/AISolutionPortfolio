"""Unit tests for the guardrails layer (Content Safety + schema validation)."""

from __future__ import annotations

import logging

import pytest
from pydantic import BaseModel, Field

from framework.guardrails.content_safety import (
    CategoryAnalysis,
    ContentSafetyClient,
    ContentSafetyResult,
    ContentSafetyVerdict,
    HarmCategory,
    SchemaValidationError,
    Severity,
    validate_schema,
)

# ---------- Severity / HarmCategory enums ----------


def test_severity_values_match_azure_four_level_scale() -> None:
    assert Severity.SAFE.value == 0
    assert Severity.LOW.value == 2
    assert Severity.MEDIUM.value == 4
    assert Severity.HIGH.value == 6


def test_harm_category_canonical_four() -> None:
    assert {c.value for c in HarmCategory} == {"Hate", "SelfHarm", "Sexual", "Violence"}


# ---------- ContentSafetyResult ----------


def test_result_is_blocked_at_default_threshold() -> None:
    r = ContentSafetyResult(
        categories=[
            CategoryAnalysis(category=HarmCategory.HATE, severity=Severity.MEDIUM),
            CategoryAnalysis(category=HarmCategory.VIOLENCE, severity=Severity.SAFE),
        ]
    )
    assert r.is_blocked() is True
    assert r.verdict() is ContentSafetyVerdict.BLOCK
    assert r.blocking_categories() == [HarmCategory.HATE]


def test_result_is_allowed_when_all_below_threshold() -> None:
    r = ContentSafetyResult(
        categories=[CategoryAnalysis(category=cat, severity=Severity.SAFE) for cat in HarmCategory]
    )
    assert r.is_blocked() is False
    assert r.verdict() is ContentSafetyVerdict.ALLOW
    assert r.blocking_categories() == []


def test_result_threshold_can_be_tightened() -> None:
    """Caller can tighten the threshold to LOW for stricter contexts."""
    r = ContentSafetyResult(
        categories=[
            CategoryAnalysis(category=HarmCategory.HATE, severity=Severity.LOW),
        ]
    )
    assert r.is_blocked(threshold=Severity.LOW) is True
    assert r.is_blocked(threshold=Severity.MEDIUM) is False


def test_result_high_severity_is_blocked() -> None:
    r = ContentSafetyResult(
        categories=[
            CategoryAnalysis(category=HarmCategory.SEXUAL, severity=Severity.HIGH),
        ]
    )
    assert r.is_blocked() is True
    assert r.blocking_categories() == [HarmCategory.SEXUAL]


# ---------- validate_schema ----------


class _Plan(BaseModel):
    goal: str = Field(min_length=1)
    steps: list[str]


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


def test_schema_validation_error_preserves_cause() -> None:
    try:
        validate_schema({"goal": "g"}, _Plan)  # missing steps
    except SchemaValidationError as exc:
        assert exc.cause is not None
        assert exc.model is _Plan
    else:
        pytest.fail("expected SchemaValidationError")


# ---------- ContentSafetyClient (stub) ----------


async def test_content_safety_client_stub_returns_allow_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = ContentSafetyClient(endpoint="https://cs.example/")
    with caplog.at_level(logging.WARNING, logger="agent.guardrails.content_safety.stub"):
        result = await client.check_text("anything at all")
    assert result.verdict() is ContentSafetyVerdict.ALLOW
    assert all(c.severity is Severity.SAFE for c in result.categories)
    assert "STUB Content Safety" in caplog.text
    # all four categories represented even though SAFE
    assert {c.category for c in result.categories} == set(HarmCategory)


def test_content_safety_client_endpoint_property() -> None:
    client = ContentSafetyClient(endpoint="https://cs.example/")
    assert client.endpoint == "https://cs.example/"


def test_content_safety_from_endpoint_factory() -> None:
    client = ContentSafetyClient.from_endpoint(endpoint="https://cs.example/")
    assert isinstance(client, ContentSafetyClient)
    assert client.endpoint == "https://cs.example/"


def test_content_safety_client_endpoint_can_be_omitted() -> None:
    """Useful for tests that don't need a configured endpoint."""
    client = ContentSafetyClient()
    assert client.endpoint is None
