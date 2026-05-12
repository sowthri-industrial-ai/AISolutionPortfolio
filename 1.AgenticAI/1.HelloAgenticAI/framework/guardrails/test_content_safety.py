"""Unit tests for the Content Safety client (input + output gates).

Schema-gate tests (``validate_schema`` / ``SchemaValidationError``) live
in :mod:`framework.guardrails.test_schema` — separate module, separate
concern.
"""

from __future__ import annotations

import logging

import pytest

from framework.guardrails.content_safety import (
    CategoryAnalysis,
    ContentSafetyClient,
    ContentSafetyResult,
    ContentSafetyVerdict,
    HarmCategory,
    Severity,
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
