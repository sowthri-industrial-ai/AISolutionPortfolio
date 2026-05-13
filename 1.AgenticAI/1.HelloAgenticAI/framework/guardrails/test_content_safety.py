"""Unit tests for the Content Safety client (input + output gates).

Schema-gate tests (``validate_schema`` / ``SchemaValidationError``) live
in :mod:`framework.guardrails.test_schema` — separate module, separate
concern.

The real SDK is never contacted: ``unittest.mock.patch`` substitutes
``azure.ai.contentsafety.aio.ContentSafetyClient`` and
``azure.identity.aio.DefaultAzureCredential`` so every test runs offline.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from framework.guardrails.content_safety import (
    CategoryAnalysis,
    ContentSafetyClient,
    ContentSafetyError,
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


def test_result_max_severity_picks_largest() -> None:
    r = ContentSafetyResult(
        categories=[
            CategoryAnalysis(category=HarmCategory.HATE, severity=Severity.SAFE),
            CategoryAnalysis(category=HarmCategory.VIOLENCE, severity=Severity.HIGH),
            CategoryAnalysis(category=HarmCategory.SEXUAL, severity=Severity.LOW),
        ]
    )
    assert r.max_severity() is Severity.HIGH


def test_result_max_severity_returns_safe_when_empty() -> None:
    """Defensive: an empty categories list shouldn't crash; SAFE is the
    floor of the enum."""
    r = ContentSafetyResult(categories=[])
    assert r.max_severity() is Severity.SAFE


# ---------- ContentSafetyError ----------


def test_content_safety_error_carries_gate_categories_severity() -> None:
    exc = ContentSafetyError(
        gate="input",
        blocking_categories=[HarmCategory.HATE, HarmCategory.VIOLENCE],
        severity=Severity.HIGH,
    )
    assert exc.gate == "input"
    assert exc.blocking_categories == [HarmCategory.HATE, HarmCategory.VIOLENCE]
    assert exc.severity is Severity.HIGH
    assert "input gate blocked" in str(exc)
    assert "Hate" in str(exc)
    assert "HIGH" in str(exc)


def test_content_safety_error_rejects_invalid_gate() -> None:
    """Defensive: only ``'input'`` or ``'output'`` are meaningful — a typo
    should fail loudly, not silently log the wrong gate label."""
    with pytest.raises(ValueError, match="must be 'input' or 'output'"):
        ContentSafetyError(
            gate="middle",
            blocking_categories=[HarmCategory.HATE],
            severity=Severity.HIGH,
        )


def test_content_safety_error_accepts_output_gate() -> None:
    exc = ContentSafetyError(
        gate="output",
        blocking_categories=[HarmCategory.SEXUAL],
        severity=Severity.MEDIUM,
    )
    assert exc.gate == "output"


# ---------- ContentSafetyClient — construction + introspection ----------


def _make_mock_credential() -> MagicMock:
    """Mock DefaultAzureCredential — its ``close()`` must be an
    ``AsyncMock`` because ContentSafetyClient.close awaits it. Without
    this, ``async with`` exits raise ``TypeError: object MagicMock can't
    be used in 'await' expression``."""
    cred = MagicMock()
    cred.close = AsyncMock()
    return cred


def test_client_construction_is_cheap_no_endpoint() -> None:
    """Construction must not touch the SDK / network / auth — Phase 4
    lazy-init contract."""
    client = ContentSafetyClient()
    assert client.endpoint is None
    assert client.is_armed is False  # no endpoint
    # Internal state: SDK client not built
    assert client._client is None
    assert client._credential is None


def test_client_construction_is_cheap_with_endpoint() -> None:
    client = ContentSafetyClient(endpoint="https://cs.example.cognitiveservices.azure.com/")
    assert client.endpoint == "https://cs.example.cognitiveservices.azure.com/"
    assert client.is_armed is True  # endpoint set, not (yet) failed
    # Lazy-init: SDK client not built until first check_text
    assert client._client is None


def test_client_from_endpoint_factory() -> None:
    client = ContentSafetyClient.from_endpoint(endpoint="https://cs.example/")
    assert isinstance(client, ContentSafetyClient)
    assert client.endpoint == "https://cs.example/"


# ---------- ContentSafetyClient — degraded mode (no endpoint) ----------


async def test_check_text_no_endpoint_returns_allow_and_logs_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No-endpoint construction is the pre-first-deploy / test-fixture
    case. First call returns ALLOW and logs one warning. Subsequent
    calls return ALLOW silently — the lock-guarded init only fires once."""
    client = ContentSafetyClient()  # no endpoint
    with caplog.at_level(logging.WARNING, logger="framework.guardrails.content_safety"):
        r1 = await client.check_text("anything")
        r2 = await client.check_text("anything else")
    assert r1.verdict() is ContentSafetyVerdict.ALLOW
    assert r2.verdict() is ContentSafetyVerdict.ALLOW
    assert all(c.severity is Severity.SAFE for c in r1.categories)
    # All four categories represented in the ALLOW fallback
    assert {c.category for c in r1.categories} == set(HarmCategory)
    # Single "no endpoint" warning across both calls — not one per call
    warnings = [r for r in caplog.records if "no endpoint configured" in r.message]
    assert len(warnings) == 1
    # The instance is now permanently in failed mode; is_armed reflects it
    assert client.is_armed is False


# ---------- ContentSafetyClient — init failure ----------


async def test_init_failure_marks_client_failed_returns_allow(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SDK constructor raises (e.g. invalid endpoint, network unreachable).
    Instance is permanently marked failed; all subsequent calls return
    ALLOW without re-attempting the SDK."""
    client = ContentSafetyClient(endpoint="https://cs.example/")

    with (
        patch("azure.ai.contentsafety.aio.ContentSafetyClient") as mock_sdk,
        patch(
            "azure.identity.aio.DefaultAzureCredential",
            return_value=_make_mock_credential(),
        ),
        caplog.at_level(logging.WARNING, logger="framework.guardrails.content_safety"),
    ):
        mock_sdk.side_effect = RuntimeError("simulated SDK init failure")
        r1 = await client.check_text("first")
        r2 = await client.check_text("second")
        r3 = await client.check_text("third")

    assert r1.verdict() is ContentSafetyVerdict.ALLOW
    assert r2.verdict() is ContentSafetyVerdict.ALLOW
    assert r3.verdict() is ContentSafetyVerdict.ALLOW
    # SDK constructor invoked exactly once even though check_text was
    # called three times — the failed flag short-circuits subsequent
    # ensure_client calls
    assert mock_sdk.call_count == 1
    # One warning, not three
    warnings = [r for r in caplog.records if "init failed" in r.message]
    assert len(warnings) == 1
    assert "RuntimeError" in warnings[0].message
    assert client.is_armed is False


# ---------- ContentSafetyClient — happy path with SDK ----------


def _make_sdk_response(
    category_severities: dict[HarmCategory, Severity],
) -> Any:
    """Build a mock ``AnalyzeTextResult`` with the given per-category
    severities. The real SDK uses an object with attributes ``category``
    and ``severity``; ``SimpleNamespace`` matches that shape exactly."""
    return SimpleNamespace(
        categories_analysis=[
            SimpleNamespace(category=cat.value, severity=sev.value)
            for cat, sev in category_severities.items()
        ]
    )


async def test_check_text_calls_sdk_with_four_categories_and_four_severity_levels() -> None:
    """Verify the AnalyzeTextOptions we pass to the SDK lists exactly the
    four canonical categories and requests FourSeverityLevels output —
    the rest of the framework assumes this shape.

    Asserts against ``options.as_dict()`` rather than attribute access:
    the Azure SDK's attribute getter returns Python ``str(repr(...))`` of
    the enums (verified locally on azure-ai-contentsafety 1.0.0), whereas
    ``as_dict`` returns the enum members whose ``.value`` is the
    wire-format string the API actually receives.
    """
    client = ContentSafetyClient(endpoint="https://cs.example/")
    response = _make_sdk_response({cat: Severity.SAFE for cat in HarmCategory})
    mock_sdk_instance = MagicMock()
    mock_sdk_instance.analyze_text = AsyncMock(return_value=response)
    mock_sdk_instance.close = AsyncMock()

    with (
        patch(
            "azure.ai.contentsafety.aio.ContentSafetyClient",
            return_value=mock_sdk_instance,
        ),
        patch(
            "azure.identity.aio.DefaultAzureCredential",
            return_value=_make_mock_credential(),
        ),
    ):
        await client.check_text("hello")

    mock_sdk_instance.analyze_text.assert_awaited_once()
    options = mock_sdk_instance.analyze_text.await_args.args[0]
    serialized = options.as_dict()
    assert serialized["text"] == "hello"
    # Categories in as_dict() are the TextCategory enum members; .value is
    # the wire-format string Azure expects ("Hate", "SelfHarm", etc.) and
    # matches our HarmCategory enum values exactly.
    wire_categories = {c.value for c in serialized["categories"]}
    assert wire_categories == {c.value for c in HarmCategory}
    # output_type in as_dict() is the FOUR_SEVERITY_LEVELS enum member.
    assert serialized["outputType"].value == "FourSeverityLevels"


async def test_check_text_returns_block_when_sdk_returns_high_severity() -> None:
    client = ContentSafetyClient(endpoint="https://cs.example/")
    response = _make_sdk_response(
        {
            HarmCategory.HATE: Severity.HIGH,
            HarmCategory.SELF_HARM: Severity.SAFE,
            HarmCategory.SEXUAL: Severity.SAFE,
            HarmCategory.VIOLENCE: Severity.SAFE,
        }
    )
    mock_sdk_instance = MagicMock()
    mock_sdk_instance.analyze_text = AsyncMock(return_value=response)
    mock_sdk_instance.close = AsyncMock()

    with (
        patch(
            "azure.ai.contentsafety.aio.ContentSafetyClient",
            return_value=mock_sdk_instance,
        ),
        patch(
            "azure.identity.aio.DefaultAzureCredential",
            return_value=_make_mock_credential(),
        ),
    ):
        result = await client.check_text("flagged text")

    assert result.verdict() is ContentSafetyVerdict.BLOCK
    assert result.blocking_categories() == [HarmCategory.HATE]
    assert result.max_severity() is Severity.HIGH


async def test_check_text_returns_allow_when_sdk_returns_all_safe() -> None:
    client = ContentSafetyClient(endpoint="https://cs.example/")
    response = _make_sdk_response({cat: Severity.SAFE for cat in HarmCategory})
    mock_sdk_instance = MagicMock()
    mock_sdk_instance.analyze_text = AsyncMock(return_value=response)
    mock_sdk_instance.close = AsyncMock()

    with (
        patch(
            "azure.ai.contentsafety.aio.ContentSafetyClient",
            return_value=mock_sdk_instance,
        ),
        patch(
            "azure.identity.aio.DefaultAzureCredential",
            return_value=_make_mock_credential(),
        ),
    ):
        result = await client.check_text("benign text")

    assert result.verdict() is ContentSafetyVerdict.ALLOW
    assert result.blocking_categories() == []


async def test_check_text_lazy_init_only_fires_once() -> None:
    """Two ``check_text`` calls on the same instance should build the SDK
    client exactly once — the double-checked-locking in ``_ensure_client``
    avoids re-init on every call."""
    client = ContentSafetyClient(endpoint="https://cs.example/")
    response = _make_sdk_response({cat: Severity.SAFE for cat in HarmCategory})
    mock_sdk_instance = MagicMock()
    mock_sdk_instance.analyze_text = AsyncMock(return_value=response)
    mock_sdk_instance.close = AsyncMock()

    with (
        patch(
            "azure.ai.contentsafety.aio.ContentSafetyClient",
            return_value=mock_sdk_instance,
        ) as sdk_class,
        patch("azure.identity.aio.DefaultAzureCredential") as cred_class,
    ):
        await client.check_text("first")
        await client.check_text("second")
        await client.check_text("third")

    assert sdk_class.call_count == 1
    assert cred_class.call_count == 1
    assert mock_sdk_instance.analyze_text.await_count == 3


# ---------- ContentSafetyClient — per-call failure ----------


async def test_check_text_per_call_failure_returns_allow(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If ``analyze_text`` raises (transient SDK error, throttle), this
    call returns ALLOW but the instance stays armed for next call."""
    client = ContentSafetyClient(endpoint="https://cs.example/")
    mock_sdk_instance = MagicMock()
    mock_sdk_instance.analyze_text = AsyncMock(side_effect=RuntimeError("simulated 429 throttle"))
    mock_sdk_instance.close = AsyncMock()

    with (
        patch(
            "azure.ai.contentsafety.aio.ContentSafetyClient",
            return_value=mock_sdk_instance,
        ),
        patch(
            "azure.identity.aio.DefaultAzureCredential",
            return_value=_make_mock_credential(),
        ),
        caplog.at_level(logging.WARNING, logger="framework.guardrails.content_safety"),
    ):
        result = await client.check_text("text")

    assert result.verdict() is ContentSafetyVerdict.ALLOW
    # Instance stays armed — next call may try the SDK again
    assert client.is_armed is True
    warnings = [r for r in caplog.records if "check_text failed" in r.message]
    assert len(warnings) == 1
    assert "RuntimeError" in warnings[0].message


async def test_check_text_per_call_failure_does_not_mark_failed() -> None:
    """First call raises; second call succeeds — proves per-call errors
    don't permanently disable the instance."""
    client = ContentSafetyClient(endpoint="https://cs.example/")
    response = _make_sdk_response({cat: Severity.SAFE for cat in HarmCategory})
    mock_sdk_instance = MagicMock()
    # First call raises, second call succeeds
    mock_sdk_instance.analyze_text = AsyncMock(side_effect=[RuntimeError("transient"), response])
    mock_sdk_instance.close = AsyncMock()

    with (
        patch(
            "azure.ai.contentsafety.aio.ContentSafetyClient",
            return_value=mock_sdk_instance,
        ),
        patch(
            "azure.identity.aio.DefaultAzureCredential",
            return_value=_make_mock_credential(),
        ),
    ):
        r1 = await client.check_text("first")
        r2 = await client.check_text("second")

    assert r1.verdict() is ContentSafetyVerdict.ALLOW
    assert r2.verdict() is ContentSafetyVerdict.ALLOW
    # Both calls reached the SDK — second wasn't short-circuited
    assert mock_sdk_instance.analyze_text.await_count == 2


# ---------- ContentSafetyClient — lifecycle ----------


async def test_close_is_idempotent() -> None:
    """Calling close() twice on a never-initialised client must not raise."""
    client = ContentSafetyClient()
    await client.close()
    await client.close()  # idempotent


async def test_close_releases_sdk_handle() -> None:
    client = ContentSafetyClient(endpoint="https://cs.example/")
    response = _make_sdk_response({cat: Severity.SAFE for cat in HarmCategory})
    mock_sdk_instance = MagicMock()
    mock_sdk_instance.analyze_text = AsyncMock(return_value=response)
    mock_sdk_instance.close = AsyncMock()
    mock_credential = MagicMock()
    mock_credential.close = AsyncMock()

    with (
        patch(
            "azure.ai.contentsafety.aio.ContentSafetyClient",
            return_value=mock_sdk_instance,
        ),
        patch(
            "azure.identity.aio.DefaultAzureCredential",
            return_value=mock_credential,
        ),
    ):
        await client.check_text("init the client")
        await client.close()

    mock_sdk_instance.close.assert_awaited_once()
    mock_credential.close.assert_awaited_once()


async def test_context_manager_closes_on_exit() -> None:
    """``async with`` should close the SDK handle on exit."""
    response = _make_sdk_response({cat: Severity.SAFE for cat in HarmCategory})
    mock_sdk_instance = MagicMock()
    mock_sdk_instance.analyze_text = AsyncMock(return_value=response)
    mock_sdk_instance.close = AsyncMock()

    with (
        patch(
            "azure.ai.contentsafety.aio.ContentSafetyClient",
            return_value=mock_sdk_instance,
        ),
        patch(
            "azure.identity.aio.DefaultAzureCredential",
            return_value=_make_mock_credential(),
        ),
    ):
        async with ContentSafetyClient(endpoint="https://cs.example/") as client:
            await client.check_text("init")

    mock_sdk_instance.close.assert_awaited_once()
