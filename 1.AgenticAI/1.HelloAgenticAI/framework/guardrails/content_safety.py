"""Content Safety client — input and output text-analysis gates.

Per ``docs/ARCHITECTURE.md`` §3, the agent runs three guardrail gates;
this module owns the **input gate** (user goal at agent entry) and the
**output gate** (final answer before it reaches the user). The third
gate — Pydantic schema validation on structured LLM/tool I/O — lives
in :mod:`framework.guardrails.schema` (different concern, different
failure mode, different SDK dependency).

Phase 2 ships the API surface only. The Content Safety client is a
STUB that always returns ALLOW so Phase 2 integration tests run without
touching the real REST API. Phase 4 swaps in the real
``POST /contentsafety/text:analyze`` call (along with the
``GUARDRAIL_BLOCKED`` event type that fires when the verdict is BLOCK).

The stub deliberately does NOT silently mask failures — it logs a clear
warning every time it is called so it's obvious in test output that the
real call hasn't been wired yet.
"""

from __future__ import annotations

import logging
from enum import IntEnum, StrEnum

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

    def verdict(self, threshold: Severity = Severity.MEDIUM) -> ContentSafetyVerdict:
        return (
            ContentSafetyVerdict.BLOCK if self.is_blocked(threshold) else ContentSafetyVerdict.ALLOW
        )


class ContentSafetyClient:
    """Azure AI Content Safety client.

    Phase 2: STUB that always returns ALLOW. Logs a warning on every call
    so it's obvious the real REST call isn't wired yet.

    Phase 4 will replace :meth:`check_text` with the real
    ``POST /contentsafety/text:analyze`` call (AAD-only via the
    user-assigned managed identity, which already holds Cognitive Services
    User on the Phase 1 Content Safety account).
    """

    _STUB_LOGGER = logging.getLogger("agent.guardrails.content_safety.stub")

    def __init__(self, *, endpoint: str | None = None) -> None:
        self._endpoint = endpoint

    @classmethod
    def from_endpoint(cls, *, endpoint: str) -> ContentSafetyClient:
        return cls(endpoint=endpoint)

    @property
    def endpoint(self) -> str | None:
        return self._endpoint

    async def check_text(self, text: str) -> ContentSafetyResult:
        """Analyze ``text`` for harm categories. Returns ALLOW in Phase 2.

        Phase 4 implementation: HTTPS POST to
        ``{endpoint}/contentsafety/text:analyze?api-version=2024-09-01``
        with the AAD bearer token, body ``{"text": text, "categories":
        [...4 categories...], "outputType": "FourSeverityLevels"}``.
        """
        # TODO(phase4): real API call.
        self._STUB_LOGGER.warning(
            "STUB Content Safety check_text — always returns SAFE; Phase 4 wires real API"
        )
        return ContentSafetyResult(
            categories=[
                CategoryAnalysis(category=cat, severity=Severity.SAFE) for cat in HarmCategory
            ]
        )
