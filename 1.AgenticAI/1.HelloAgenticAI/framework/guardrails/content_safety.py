"""Content Safety client — input and output text-analysis gates.

Per ``docs/ARCHITECTURE.md`` §3, the agent runs three guardrail gates;
this module owns the **input gate** (user goal at agent entry) and the
**output gate** (final answer before it reaches the user). The third
gate — Pydantic schema validation on structured LLM/tool I/O — lives
in :mod:`framework.guardrails.schema` (different concern, different
failure mode, different SDK dependency).

Phase 4 ships the real Azure AI Content Safety integration via the
:mod:`azure-ai-contentsafety` SDK. AAD-only auth via the user-assigned
managed identity (production) or the dev principal (local). The
Phase 1 Bicep already grants Cognitive Services User on the deployed
account to both principals.

Architectural rule — **lazy-init + graceful degrade**:

* The client constructs cheaply: no I/O, no SDK import, no auth attempt.
* The SDK client + credential are built on the FIRST :meth:`check_text`
  call.
* If init fails (no endpoint configured, SDK import error, network
  unreachable), the instance is permanently marked failed; every
  subsequent ``check_text`` returns ALLOW. One warning is logged.
* If a per-call analysis fails (throttle, transient network), THIS call
  returns ALLOW and the instance stays armed for the next call.

The agent NEVER crashes because Content Safety is unreachable or
misconfigured. Fail-open is the deliberate default — security on a
best-effort basis, availability guaranteed.

The framework client never **raises** ``ContentSafetyError`` directly —
it returns a :class:`ContentSafetyResult` and the caller (the agent
layer's input/output gates in Phase 4 batch 3) decides whether to
convert a BLOCK verdict into a raised exception. Keeps the client a
pure analysis surface.
"""

from __future__ import annotations

import asyncio
import logging
from enum import IntEnum, StrEnum
from types import TracebackType
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Severity(IntEnum):
    """Azure Content Safety four-level severity scale."""

    SAFE = 0
    LOW = 2
    MEDIUM = 4
    HIGH = 6


class HarmCategory(StrEnum):
    """The four canonical Azure Content Safety harm categories."""

    HATE = "Hate"
    SELF_HARM = "SelfHarm"
    SEXUAL = "Sexual"
    VIOLENCE = "Violence"


class CategoryAnalysis(BaseModel):
    """One category's analysis result from the Content Safety API."""

    category: HarmCategory
    severity: Severity


class ContentSafetyVerdict(StrEnum):
    """Aggregate decision derived from per-category severities."""

    ALLOW = "allow"
    BLOCK = "block"


class ContentSafetyResult(BaseModel):
    """Full result of one :meth:`ContentSafetyClient.check_text` call."""

    categories: list[CategoryAnalysis]

    def is_blocked(self, threshold: Severity = Severity.MEDIUM) -> bool:
        """Whether ANY category meets or exceeds ``threshold``."""
        return any(c.severity >= threshold for c in self.categories)

    def blocking_categories(self, threshold: Severity = Severity.MEDIUM) -> list[HarmCategory]:
        return [c.category for c in self.categories if c.severity >= threshold]

    def max_severity(self) -> Severity:
        """Highest severity across all categories — useful for the
        ``GUARDRAIL_BLOCKED`` event payload."""
        return max((c.severity for c in self.categories), default=Severity.SAFE)

    def verdict(self, threshold: Severity = Severity.MEDIUM) -> ContentSafetyVerdict:
        return (
            ContentSafetyVerdict.BLOCK if self.is_blocked(threshold) else ContentSafetyVerdict.ALLOW
        )


class ContentSafetyError(Exception):
    """Raised by the agent-layer gates (Phase 4 batch 3) when Content
    Safety BLOCKs input or output.

    Carries the gate name (``"input"`` or ``"output"``), the blocking
    categories, and the maximum severity — enough payload for the
    ``GUARDRAIL_BLOCKED`` event AND for Chainlit's UI to render a clear
    "your message was flagged" message.

    The framework client itself never raises this. It returns a
    :class:`ContentSafetyResult` and the caller decides whether to
    convert a BLOCK verdict into a raised exception. This keeps the
    client a pure analysis surface and lets test code assert on the
    result without dealing with exception handling.
    """

    def __init__(
        self,
        *,
        gate: str,
        blocking_categories: list[HarmCategory],
        severity: Severity,
    ) -> None:
        if gate not in {"input", "output"}:
            raise ValueError(f"ContentSafetyError.gate must be 'input' or 'output', got {gate!r}")
        self.gate = gate
        self.blocking_categories = blocking_categories
        self.severity = severity
        cats = ", ".join(c.value for c in blocking_categories) or "<unknown>"
        super().__init__(
            f"Content Safety {gate} gate blocked: severity={severity.name}, categories=[{cats}]"
        )


# ---------- internal helpers ----------


def _allow_all() -> ContentSafetyResult:
    """All-SAFE result. Used by the degraded/failed paths in
    :class:`ContentSafetyClient` and by tests that need a known-good
    ALLOW fixture."""
    return ContentSafetyResult(
        categories=[CategoryAnalysis(category=c, severity=Severity.SAFE) for c in HarmCategory]
    )


def _result_from_sdk_response(response: Any) -> ContentSafetyResult:
    """Convert the SDK's ``AnalyzeTextResult`` to our typed shape.

    The SDK's ``categories_analysis`` is a list of objects with
    ``category`` (string matching :class:`HarmCategory` values) and
    ``severity`` (int matching :class:`Severity` values). ``HarmCategory``
    is a ``StrEnum`` and ``Severity`` an ``IntEnum``, so the
    constructors validate the SDK's strings/ints in one step.
    """
    return ContentSafetyResult(
        categories=[
            CategoryAnalysis(
                category=HarmCategory(c.category),
                severity=Severity(c.severity),
            )
            for c in response.categories_analysis
        ]
    )


# ---------- the client ----------


class ContentSafetyClient:
    """Azure AI Content Safety client with lazy-init and graceful degrade.

    Construction is cheap: no I/O, no SDK import, no auth attempt. See
    the module docstring for the full lifecycle contract.
    """

    def __init__(self, *, endpoint: str | None = None) -> None:
        self._endpoint = endpoint
        # The SDK client + credential are lazily built. Their types are
        # ``Any`` here to avoid eagerly importing the heavy azure-ai-*
        # modules at framework import time — tests that don't exercise
        # Content Safety shouldn't pay the import cost.
        self._client: Any | None = None
        self._credential: Any | None = None
        self._init_lock = asyncio.Lock()
        self._init_failed = False

    @classmethod
    def from_endpoint(cls, *, endpoint: str) -> ContentSafetyClient:
        return cls(endpoint=endpoint)

    @property
    def endpoint(self) -> str | None:
        return self._endpoint

    @property
    def is_armed(self) -> bool:
        """Whether the client has both an endpoint AND has not been
        marked failed. Useful for tests and for graceful UI degrade
        (Chainlit can skip the "guardrails active" indicator if this is
        ``False``).

        Note this can return ``True`` before the SDK client has actually
        been built — the lazy-init may not have run yet. Use
        :meth:`check_text` to actually exercise the path.
        """
        return self._endpoint is not None and not self._init_failed

    async def _ensure_client(self) -> Any | None:
        """Lazy-init the SDK client. Returns the client or ``None`` if
        the instance is in degraded/failed mode.

        Double-checked locking pattern — the fast path doesn't acquire
        the lock once the client is built or the instance is marked
        failed."""
        if self._client is not None:
            return self._client
        if self._init_failed:
            return None
        async with self._init_lock:
            if self._client is not None:
                return self._client
            if self._init_failed:
                return None
            if not self._endpoint:
                self._init_failed = True
                logger.warning(
                    "ContentSafetyClient has no endpoint configured; "
                    "input/output gates will pass-through ALLOW for the instance lifetime"
                )
                return None
            try:
                from azure.ai.contentsafety.aio import (
                    ContentSafetyClient as _SDKClient,
                )
                from azure.identity.aio import DefaultAzureCredential

                self._credential = DefaultAzureCredential()
                self._client = _SDKClient(endpoint=self._endpoint, credential=self._credential)
            except Exception as exc:
                logger.warning(
                    "ContentSafetyClient init failed (%s); input/output gates will pass-through "
                    "ALLOW for the instance lifetime: %r",
                    type(exc).__name__,
                    exc,
                )
                self._init_failed = True
                return None
        return self._client

    async def check_text(self, text: str) -> ContentSafetyResult:
        """Analyze ``text`` for the four Azure harm categories.

        Returns an ALLOW result (all categories SAFE) if the client has
        no endpoint, init has failed, or this specific call hits a
        transient SDK error. The agent layer's input/output gates check
        :meth:`ContentSafetyResult.is_blocked` and decide. This method
        never raises.
        """
        client = await self._ensure_client()
        if client is None:
            return _allow_all()
        try:
            from azure.ai.contentsafety.models import (
                AnalyzeTextOptions,
                AnalyzeTextOutputType,
                TextCategory,
            )

            response = await client.analyze_text(
                AnalyzeTextOptions(
                    text=text,
                    categories=[
                        TextCategory.HATE,
                        TextCategory.SELF_HARM,
                        TextCategory.SEXUAL,
                        TextCategory.VIOLENCE,
                    ],
                    output_type=AnalyzeTextOutputType.FOUR_SEVERITY_LEVELS,
                )
            )
        except Exception as exc:
            logger.warning(
                "ContentSafety check_text failed for endpoint %s; this call returns ALLOW "
                "but the instance stays armed for the next call: %r",
                self._endpoint,
                exc,
            )
            return _allow_all()
        return _result_from_sdk_response(response)

    async def close(self) -> None:
        """Close the SDK client + credential. Safe to call multiple
        times and safe even if the client never initialised."""
        if self._client is not None:
            await self._client.close()
            self._client = None
        if self._credential is not None:
            await self._credential.close()
            self._credential = None

    async def __aenter__(self) -> ContentSafetyClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
