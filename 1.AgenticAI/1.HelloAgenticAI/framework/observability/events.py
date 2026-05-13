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
  (always-on dev fallback).

Phase 4 adds:

* ``SCHEMA_VALIDATION_FAILED`` and ``GUARDRAIL_BLOCKED`` event types;
* :class:`AppInsightsSink` (re-exported from
  :mod:`framework.observability.app_insights`) — real OTel-based App
  Insights ingestion with lazy init.

The Cosmos sink intentionally lives in :mod:`framework.memory.cosmos`
because it depends on :class:`CosmosProvider`; importing it here would
create a layering inversion. The same separation applies to
:class:`AppInsightsSink` (its own module under
:mod:`framework.observability`) and :class:`LangfuseSink` (batch 5).
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
    """Canonical agent-loop event types, emitted via :class:`AgentEventEmitter`.

    **Contract.**

    * **The Phase 2 canonical six** — ``PLAN_START``, ``PLAN_COMPLETE``,
      ``TOOL_CALL``, ``TOOL_RESULT``, ``REFLECT``, ``COMPLETE`` — are
      required and stable. Every vertical project's agent runs must emit
      all six on a happy-path execution. Removing or renaming any of
      these is a breaking change to the framework.

    * **Additional event types may be added in future phases.** Phase 4
      adds ``SCHEMA_VALIDATION_FAILED`` (emitted on each retry attempt
      when a structured LLM output or tool-input payload fails Pydantic
      validation — 3 attempts total per node per PROJECT_PLAN; the 3rd
      failure also propagates as a typed exception, so a run that
      exhausts retries produces three events plus an error). Phase 4
      will also add ``GUARDRAIL_BLOCKED`` (Content Safety input/output
      gates). Future phases may add ``LLM_CALL_START`` /
      ``LLM_CALL_COMPLETE`` / ``ROUTE``. Sinks and tests should treat
      the canonical six as a **subset** of the live enum, not equal to
      it.

    * **``*_START`` events must have a matching ``*_COMPLETE`` event in
      normal control flow.** Emit ``*_START`` only when the operation is
      committed to running, not while still evaluating whether to run
      it. This is a Phase 4 design principle adopted after ``TOOL_CALL``
      was tightened to fire only AFTER the route + tool-input-validation
      retry block succeeds — guarantees the trace produces strict pairs
      that downstream consumers (Langfuse span pairing, UI step
      rendering, latency-pair calculation in App Insights workbook) can
      rely on. The principle generalises to event types we haven't
      built yet (e.g. an ``LLM_CALL_START`` must only fire when the
      bound LLM call is about to be issued).
    """

    PLAN_START = "plan_start"
    PLAN_COMPLETE = "plan_complete"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    REFLECT = "reflect"
    COMPLETE = "complete"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    GUARDRAIL_BLOCKED = "guardrail_blocked"


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


# ---------- Phase 4 real sinks (re-exported from sibling modules) ----------

# AppInsightsSink lives in framework.observability.app_insights to keep
# the OTel + Azure Monitor imports out of this base module — projects
# that don't need App Insights shouldn't pay that import cost. Re-
# exported here so existing callers' import paths (``from
# framework.observability.events import AppInsightsSink``) keep
# working.
from framework.observability.app_insights import (  # noqa: E402
    AppInsightsSink as AppInsightsSink,
)

# ---------- Phase 4 stubs (replaced in batches 5+) ----------


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
