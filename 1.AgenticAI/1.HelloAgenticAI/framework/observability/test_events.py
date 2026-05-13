"""Unit tests for the observability events module."""

from __future__ import annotations

import asyncio
import logging

import pytest
from pydantic import ValidationError

from framework.observability.events import (
    AgentEvent,
    AgentEventEmitter,
    AgentEventType,
    AppInsightsSink,
    InMemorySink,
    LangfuseSink,
    LoggingSink,
    UIStreamSink,
)

# ---------- AgentEventType ----------


def test_agent_event_type_includes_phase_2_canonical_six() -> None:
    """The six minimum events agreed for Phase 2 remain present as
    Phase 4 (and later) adds more types. This is a *subset* check, not
    an equality check — Phase 4's ``SCHEMA_VALIDATION_FAILED`` and
    follow-ons (``GUARDRAIL_BLOCKED`` etc.) are expected additions, not
    failures."""
    phase_2_canonical = {
        "plan_start",
        "plan_complete",
        "tool_call",
        "tool_result",
        "reflect",
        "complete",
    }
    actual = {t.value for t in AgentEventType}
    assert (
        phase_2_canonical <= actual
    ), f"Phase 2 canonical events missing from enum: {phase_2_canonical - actual}"


def test_agent_event_type_includes_phase_4_schema_validation_failed() -> None:
    """Phase 4 deliverable 1 — explicit assertion that the new event type
    is wired into the enum (and not accidentally removed by a future
    refactor)."""
    assert AgentEventType.SCHEMA_VALIDATION_FAILED.value == "schema_validation_failed"


def test_agent_event_type_includes_phase_4_guardrail_blocked() -> None:
    """Phase 4 deliverable 2 — Content Safety input/output gates emit
    ``GUARDRAIL_BLOCKED`` when the verdict is BLOCK. Explicit presence
    assertion to prevent silent regression."""
    assert AgentEventType.GUARDRAIL_BLOCKED.value == "guardrail_blocked"


def test_agent_event_type_is_string_enum() -> None:
    """StrEnum so values serialize cleanly for Cosmos."""
    assert AgentEventType.PLAN_START.value == "plan_start"
    assert isinstance(AgentEventType.PLAN_START, str)


# ---------- AgentEvent ----------


def test_agent_event_defaults() -> None:
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    assert e.session_id == "s1"
    assert e.type is AgentEventType.PLAN_START
    assert e.event_id is not None
    assert e.timestamp.tzinfo is not None  # always tz-aware
    assert e.node is None
    assert e.duration_ms is None
    assert e.payload == {}


def test_agent_event_is_frozen() -> None:
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    with pytest.raises(ValidationError):
        e.session_id = "s2"


def test_agent_event_session_id_min_length() -> None:
    with pytest.raises(ValidationError):
        AgentEvent(session_id="", type=AgentEventType.PLAN_START)


def test_agent_event_round_trips_through_json() -> None:
    """Cosmos persists JSON; events must serialize cleanly."""
    e = AgentEvent(
        session_id="s1",
        type=AgentEventType.TOOL_CALL,
        node="shop-A",
        duration_ms=42,
        payload={"tool": "list_inventory", "args": {"sku": "apple"}},
    )
    payload = e.model_dump_json()
    e2 = AgentEvent.model_validate_json(payload)
    assert e2 == e


def test_agent_event_negative_duration_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="s1",
            type=AgentEventType.TOOL_RESULT,
            duration_ms=-1,
        )


# ---------- AgentEventEmitter ----------


async def test_emitter_fans_out_to_every_sink() -> None:
    s1, s2 = InMemorySink(), InMemorySink()
    emitter = AgentEventEmitter([s1, s2])
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    await emitter.emit(e)
    assert s1.events == [e]
    assert s2.events == [e]


async def test_emitter_with_no_sinks_is_noop() -> None:
    emitter = AgentEventEmitter([])
    await emitter.emit(AgentEvent(session_id="s1", type=AgentEventType.COMPLETE))


async def test_emitter_fan_out_is_concurrent() -> None:
    """Sinks fire in parallel, not sequentially."""

    class SlowSink:
        async def emit(self, event: AgentEvent) -> None:
            await asyncio.sleep(0.05)

    emitter = AgentEventEmitter([SlowSink(), SlowSink(), SlowSink()])
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    loop = asyncio.get_event_loop()
    start = loop.time()
    await emitter.emit(e)
    elapsed = loop.time() - start
    # 3 sequential sleeps would be 0.15s; concurrent ~0.05-0.07s
    assert elapsed < 0.12, f"emit was sequential ({elapsed:.3f}s)"


async def test_emitter_default_raises_on_sink_error() -> None:
    class BadSink:
        async def emit(self, event: AgentEvent) -> None:
            raise RuntimeError("sink down")

    good = InMemorySink()
    emitter = AgentEventEmitter([good, BadSink()])
    with pytest.raises(RuntimeError, match="sink down"):
        await emitter.emit(AgentEvent(session_id="s1", type=AgentEventType.REFLECT))
    # the good sink still received the event before the error propagated
    assert len(good.events) == 1


async def test_emitter_swallow_sink_errors_keeps_loop_alive(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class BadSink:
        async def emit(self, event: AgentEvent) -> None:
            raise RuntimeError("cosmos blip")

    good = InMemorySink()
    emitter = AgentEventEmitter([good, BadSink()], swallow_sink_errors=True)
    with caplog.at_level(logging.WARNING, logger="framework.observability.events"):
        await emitter.emit(AgentEvent(session_id="s1", type=AgentEventType.PLAN_COMPLETE))
    assert len(good.events) == 1
    assert "BadSink" in caplog.text or "cosmos blip" in caplog.text


def test_emitter_with_sink_returns_layered_emitter() -> None:
    base = AgentEventEmitter([InMemorySink()])
    extra = InMemorySink()
    layered = base.with_sink(extra)
    assert len(base.sinks) == 1
    assert len(layered.sinks) == 2
    assert layered.sinks[1] is extra


def test_emitter_sinks_property_is_immutable_view() -> None:
    sinks_list = [InMemorySink()]
    emitter = AgentEventEmitter(sinks_list)
    # mutating the original list must not affect the emitter
    sinks_list.append(InMemorySink())
    assert len(emitter.sinks) == 1


# ---------- InMemorySink ----------


async def test_in_memory_sink_accumulates() -> None:
    sink = InMemorySink()
    for i in range(3):
        await sink.emit(AgentEvent(session_id=f"s{i}", type=AgentEventType.PLAN_START))
    assert len(sink.events) == 3
    assert {e.session_id for e in sink.events} == {"s0", "s1", "s2"}


# ---------- LoggingSink ----------


async def test_logging_sink_logs(caplog: pytest.LogCaptureFixture) -> None:
    sink = LoggingSink(logger_name="test.agent.events")
    with caplog.at_level(logging.INFO, logger="test.agent.events"):
        await sink.emit(
            AgentEvent(
                session_id="s1",
                type=AgentEventType.TOOL_CALL,
                node="shop-A",
                duration_ms=12,
                payload={"k": 1},
            )
        )
    assert "tool_call" in caplog.text
    assert "shop-A" in caplog.text
    assert "session=s1" in caplog.text


# ---------- Phase 4 sinks (real impls + remaining stubs) ----------


async def test_sinks_satisfy_event_sink_protocol_and_dont_raise() -> None:
    """All Phase 4 sinks satisfy :class:`EventSink` and complete without
    error on the degraded/unconfigured paths.

    The :class:`AppInsightsSink` is constructed with
    ``connection_string=None`` so it takes the no-connection-string
    pass-through path (logs a warning, no-ops emit). The real-init
    behaviour is exercised in
    :mod:`framework.observability.test_app_insights` with mocked OTel.
    :class:`LangfuseSink` and :class:`UIStreamSink` are still Phase
    2-style stubs at this point (batch 5 replaces LangfuseSink)."""
    e = AgentEvent(session_id="s1", type=AgentEventType.COMPLETE)
    for sink in (
        AppInsightsSink(connection_string=None),
        LangfuseSink(),
        UIStreamSink(),
    ):
        await sink.emit(e)
