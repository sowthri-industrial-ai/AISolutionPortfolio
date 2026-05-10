"""Agent event taxonomy and pluggable-sink fan-out emitter.

The observability layer is the foundation of the framework — every other
module uses :class:`AgentEventEmitter` to publish what is happening in an
agent run. Phase 2 ships:

* the six canonical :class:`AgentEventType` values for the
  Plan → Tool → Reflect → Terminate loop;
* the :class:`AgentEvent` Pydantic model (immutable, JSON-serializable for
  Cosmos persistence);
* the :class:`AgentEventEmitter` (async fan-out, optional error swallowing
  for production loops);
* :class:`InMemorySink` (unit-test fixture) and :class:`LoggingSink`
  (always-on dev fallback);
* typed stubs for App Insights / Langfuse / UI stream sinks — Phase 4
  swaps the stubs for real ingestion.

The Cosmos sink intentionally lives in :mod:`framework.memory.cosmos`
because it depends on :class:`CosmosProvider`; importing it here would
create a layering inversion.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class AgentEventType(StrEnum):
    """Canonical event taxonomy for an agent run.

    These six are the minimum surface every vertical project's runs must
    emit. Phase 4 will add ``GUARDRAIL_BLOCK``,
    ``SCHEMA_VALIDATION_FAILURE``, ``LLM_CALL_START``,
    ``LLM_CALL_COMPLETE``, ``ROUTE``.
    """

    PLAN_START = "plan_start"
    PLAN_COMPLETE = "plan_complete"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    REFLECT = "reflect"
    COMPLETE = "complete"


class AgentEvent(BaseModel):
    """A single observability event in an agent run.

    Designed to round-trip cleanly through Cosmos: every field is
    JSON-serializable; ``UUID`` becomes ``str``; ``datetime`` becomes
    ISO-8601 with timezone.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=False)

    event_id: UUID = Field(default_factory=uuid4)
    session_id: str = Field(min_length=1, max_length=128)
    type: AgentEventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    node: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class EventSink(Protocol):
    """A destination for agent events. Async by contract."""

    async def emit(self, event: AgentEvent) -> None: ...


class AgentEventEmitter:
    """Fan-out emitter — every :meth:`emit` goes to every sink concurrently.

    By default, sink errors propagate (fail-fast — useful for tests). Pass
    ``swallow_sink_errors=True`` for production: failures get logged but
    never break the agent loop. A Cosmos blip should not crash the agent.
    """

    def __init__(
        self,
        sinks: Sequence[EventSink],
        *,
        swallow_sink_errors: bool = False,
    ) -> None:
        # Snapshot the sequence so later mutations to the caller's list
        # don't affect us; covariant Sequence input lets callers pass
        # `list[ConcreteSink]` without invariance complaints.
        self._sinks: list[EventSink] = list(sinks)
        self._swallow_sink_errors = swallow_sink_errors

    @property
    def sinks(self) -> tuple[EventSink, ...]:
        return tuple(self._sinks)

    async def emit(self, event: AgentEvent) -> None:
        """Publish ``event`` to every registered sink concurrently."""
        if not self._sinks:
            return
        results = await asyncio.gather(
            *(sink.emit(event) for sink in self._sinks),
            return_exceptions=True,
        )
        for sink, result in zip(self._sinks, results, strict=True):
            if isinstance(result, BaseException):
                if self._swallow_sink_errors:
                    logger.warning(
                        "sink %s failed for event %s (%s): %r",
                        type(sink).__name__,
                        event.event_id,
                        event.type.value,
                        result,
                    )
                else:
                    raise result

    def with_sink(self, sink: EventSink) -> AgentEventEmitter:
        """Return a new emitter with one extra sink. Useful for layering."""
        return AgentEventEmitter(
            [*self._sinks, sink],
            swallow_sink_errors=self._swallow_sink_errors,
        )


# ---------- concrete sinks (Phase 2 minimum) ----------


class InMemorySink:
    """Test-fixture sink — keeps every event in a list for assertions."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    async def emit(self, event: AgentEvent) -> None:
        self.events.append(event)


class LoggingSink:
    """Fallback sink — emits events to the standard library logger.

    Always-on default in development, useful when no other sinks exist.
    """

    def __init__(self, logger_name: str = "agent.events") -> None:
        self._logger = logging.getLogger(logger_name)

    async def emit(self, event: AgentEvent) -> None:
        self._logger.info(
            "event=%s session=%s node=%s duration_ms=%s payload_keys=%s",
            event.type.value,
            event.session_id,
            event.node,
            event.duration_ms,
            sorted(event.payload.keys()),
        )


# ---------- Phase 3 / Phase 4 stubs ----------


class AppInsightsSink:
    """STUB for Phase 4 — App Insights ingestion via OpenTelemetry.

    Phase 2 ships a no-op-ish sink that satisfies :class:`EventSink`; Phase
    4 swaps in real ``opentelemetry-azure-monitor`` wiring keyed off the
    AOAI-deployed App Insights connection string.
    """

    def __init__(self, connection_string: str | None = None) -> None:
        self._connection_string = connection_string
        self._logger = logging.getLogger("agent.events.appinsights.stub")

    async def emit(self, event: AgentEvent) -> None:
        # TODO(phase4): publish via opentelemetry-azure-monitor.
        self._logger.debug(
            "STUB AppInsights emit: %s session=%s",
            event.type.value,
            event.session_id,
        )


class LangfuseSink:
    """STUB for Phase 4 — Langfuse Cloud ingestion (per ADR-0001).

    Phase 4 will read ``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY``
    from Key Vault and call the Langfuse SDK.
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger("agent.events.langfuse.stub")

    async def emit(self, event: AgentEvent) -> None:
        # TODO(phase4): publish via langfuse SDK.
        self._logger.debug(
            "STUB Langfuse emit: %s session=%s",
            event.type.value,
            event.session_id,
        )


class UIStreamSink:
    """STUB for Phase 3 — pushes events to the Chainlit live-step stream.

    Phase 3's Chainlit integration replaces this with one that posts each
    event as a Chainlit step with collapsible details.
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger("agent.events.ui.stub")

    async def emit(self, event: AgentEvent) -> None:
        # TODO(phase3): push to Chainlit step renderer.
        self._logger.debug("STUB UI stream emit: %s", event.type.value)
