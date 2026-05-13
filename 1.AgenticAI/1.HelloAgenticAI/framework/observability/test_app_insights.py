"""Unit tests for :class:`AppInsightsSink`.

The Azure Monitor exporter and the OpenTelemetry tracer are mocked
throughout — no network, no process-wide OTel side effects. The
real-deployment behaviour is exercised in the batch 8 smoke test
against the live App Insights resource.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from framework.observability.app_insights import (
    _MAX_ATTRIBUTE_VALUE_LEN,
    AppInsightsSink,
    _build_attributes,
    _coerce,
    _flatten,
)
from framework.observability.events import AgentEvent, AgentEventType


def _make_mock_tracer() -> MagicMock:
    """Mock tracer whose ``start_as_current_span`` returns a context
    manager and records the (name, attributes) it was called with."""
    tracer = MagicMock()
    # nullcontext is a real context manager — using it makes the ``with``
    # body in AppInsightsSink.emit work without further mocking, and the
    # span mock can be inspected via tracer.start_as_current_span.call_args.
    tracer.start_as_current_span = MagicMock(return_value=nullcontext(MagicMock()))
    return tracer


# ---------- construction ----------


def test_construction_is_cheap_no_connection_string() -> None:
    """No I/O, no SDK config, no exporter setup at construction."""
    sink = AppInsightsSink()
    assert sink._connection_string is None
    assert sink._tracer is None
    assert sink._init_failed is False
    assert sink.is_armed is False


def test_construction_is_cheap_with_connection_string() -> None:
    """Even with a connection string, no init runs until first emit."""
    sink = AppInsightsSink(connection_string="InstrumentationKey=fake;IngestionEndpoint=...")
    assert sink._tracer is None
    assert sink._init_failed is False
    assert sink.is_armed is True


# ---------- degraded mode: no connection string ----------


async def test_emit_no_connection_string_is_silent_after_first_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No-connection-string is the pre-first-deploy / test-fixture case.
    First emit logs one warning, subsequent emits are silent. The
    instance is permanently in pass-through mode."""
    sink = AppInsightsSink(connection_string=None)
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    with caplog.at_level(logging.WARNING, logger="framework.observability.app_insights"):
        await sink.emit(e)
        await sink.emit(e)
        await sink.emit(e)
    warnings = [r for r in caplog.records if "no connection string" in r.message]
    assert len(warnings) == 1
    assert sink.is_armed is False


# ---------- init failure ----------


async def test_init_failure_marks_sink_failed_and_returns_silently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``configure_azure_monitor`` raises (malformed connection string,
    OTel SDK error) → instance is permanently marked failed; subsequent
    emits no-op without re-attempting init."""
    sink = AppInsightsSink(connection_string="InstrumentationKey=fake;IngestionEndpoint=bogus")
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    with (
        patch(
            "azure.monitor.opentelemetry.configure_azure_monitor",
            side_effect=ValueError("simulated malformed connection string"),
        ) as cfg_mock,
        patch("opentelemetry.trace.get_tracer", return_value=_make_mock_tracer()),
        caplog.at_level(logging.WARNING, logger="framework.observability.app_insights"),
    ):
        await sink.emit(e)
        await sink.emit(e)
        await sink.emit(e)
    # configure_azure_monitor called exactly once; later emits short-circuit
    # on the _init_failed flag.
    assert cfg_mock.call_count == 1
    warnings = [r for r in caplog.records if "init failed" in r.message]
    assert len(warnings) == 1
    assert "ValueError" in warnings[0].message
    assert sink.is_armed is False


# ---------- happy path: successful init + emit ----------


async def test_emit_successful_init_only_fires_once() -> None:
    """``configure_azure_monitor`` is process-wide and expensive; the
    double-checked-locking in ``_ensure_tracer`` must guarantee it's
    invoked exactly once even under N concurrent emits."""
    sink = AppInsightsSink(connection_string="InstrumentationKey=fake")
    tracer = _make_mock_tracer()
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    with (
        patch("azure.monitor.opentelemetry.configure_azure_monitor") as cfg_mock,
        patch("opentelemetry.trace.get_tracer", return_value=tracer),
    ):
        await sink.emit(e)
        await sink.emit(e)
        await sink.emit(e)
    assert cfg_mock.call_count == 1
    assert tracer.start_as_current_span.call_count == 3


async def test_emit_creates_span_with_event_type_as_name() -> None:
    """Span name = event type value — the workbook's "events per minute
    by type" chart groups by this. Stable contract."""
    sink = AppInsightsSink(connection_string="InstrumentationKey=fake")
    tracer = _make_mock_tracer()
    e = AgentEvent(
        session_id="s1",
        type=AgentEventType.TOOL_RESULT,
        node="apple_orchard",
        duration_ms=123,
        payload={"result": "ok"},
    )
    with (
        patch("azure.monitor.opentelemetry.configure_azure_monitor"),
        patch("opentelemetry.trace.get_tracer", return_value=tracer),
    ):
        await sink.emit(e)
    call = tracer.start_as_current_span.call_args
    assert call.args[0] == "tool_result"


async def test_emit_carries_session_id_node_and_duration_in_attributes() -> None:
    sink = AppInsightsSink(connection_string="InstrumentationKey=fake")
    tracer = _make_mock_tracer()
    e = AgentEvent(
        session_id="sid-42",
        type=AgentEventType.TOOL_CALL,
        node="apple_orchard",
        duration_ms=234,
    )
    with (
        patch("azure.monitor.opentelemetry.configure_azure_monitor"),
        patch("opentelemetry.trace.get_tracer", return_value=tracer),
    ):
        await sink.emit(e)
    attrs = tracer.start_as_current_span.call_args.kwargs["attributes"]
    assert attrs["session_id"] == "sid-42"
    assert attrs["node"] == "apple_orchard"
    assert attrs["duration_ms"] == 234


async def test_emit_omits_node_when_event_has_no_node() -> None:
    """``node`` is optional on AgentEvent (plan/reflect/complete don't
    have one). It should be absent from attributes, not present as None
    or empty string — keeps customDimensions tidy."""
    sink = AppInsightsSink(connection_string="InstrumentationKey=fake")
    tracer = _make_mock_tracer()
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    with (
        patch("azure.monitor.opentelemetry.configure_azure_monitor"),
        patch("opentelemetry.trace.get_tracer", return_value=tracer),
    ):
        await sink.emit(e)
    attrs = tracer.start_as_current_span.call_args.kwargs["attributes"]
    assert "node" not in attrs


async def test_emit_duration_defaults_to_minus_one_when_unset() -> None:
    """Unset duration → -1, not None. OTel doesn't accept None
    attribute values; -1 is a sentinel the workbook KQL can filter out."""
    sink = AppInsightsSink(connection_string="InstrumentationKey=fake")
    tracer = _make_mock_tracer()
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    with (
        patch("azure.monitor.opentelemetry.configure_azure_monitor"),
        patch("opentelemetry.trace.get_tracer", return_value=tracer),
    ):
        await sink.emit(e)
    attrs = tracer.start_as_current_span.call_args.kwargs["attributes"]
    assert attrs["duration_ms"] == -1


async def test_emit_flattens_nested_payload_to_dotted_keys() -> None:
    """Nested dict payload → dotted-key attributes. Workbook KQL stays
    readable: ``customDimensions["payload.plan.goal"]`` not deep traversal."""
    sink = AppInsightsSink(connection_string="InstrumentationKey=fake")
    tracer = _make_mock_tracer()
    e = AgentEvent(
        session_id="s1",
        type=AgentEventType.PLAN_COMPLETE,
        payload={
            "plan": {"goal": "buy fruit", "budget": 20.0},
            "iterations": 1,
        },
    )
    with (
        patch("azure.monitor.opentelemetry.configure_azure_monitor"),
        patch("opentelemetry.trace.get_tracer", return_value=tracer),
    ):
        await sink.emit(e)
    attrs = tracer.start_as_current_span.call_args.kwargs["attributes"]
    assert attrs["payload.plan.goal"] == "buy fruit"
    assert attrs["payload.plan.budget"] == 20.0
    assert attrs["payload.iterations"] == 1


# ---------- per-emit failure ----------


async def test_per_emit_failure_logs_and_stays_armed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If ``start_as_current_span`` raises (transient OTel error), THIS
    event is dropped but the instance stays armed for next call."""
    sink = AppInsightsSink(connection_string="InstrumentationKey=fake")
    tracer = MagicMock()
    tracer.start_as_current_span = MagicMock(side_effect=RuntimeError("OTel hiccup"))
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    with (
        patch("azure.monitor.opentelemetry.configure_azure_monitor"),
        patch("opentelemetry.trace.get_tracer", return_value=tracer),
        caplog.at_level(logging.WARNING, logger="framework.observability.app_insights"),
    ):
        await sink.emit(e)
        # is_armed stays True — second call may succeed
        assert sink.is_armed is True
    warnings = [r for r in caplog.records if "emit failed" in r.message]
    assert len(warnings) == 1


# ---------- _flatten ----------


def test_flatten_returns_empty_dict_for_empty_input() -> None:
    assert _flatten({}) == {}


def test_flatten_one_level() -> None:
    assert _flatten({"a": 1, "b": "two"}) == {"a": 1, "b": "two"}


def test_flatten_nested_dict_to_dotted_keys() -> None:
    assert _flatten({"a": {"b": {"c": 1}}}) == {"a.b.c": 1}


def test_flatten_does_not_unroll_lists() -> None:
    """Lists at any depth stay intact — :func:`_coerce` stringifies them
    at the leaf."""
    result = _flatten({"items": [1, 2, 3]})
    assert result == {"items": [1, 2, 3]}


def test_flatten_mixed_nesting() -> None:
    payload = {
        "plan": {"goal": "buy", "items": ["a", "b"]},
        "iter": 1,
    }
    assert _flatten(payload) == {
        "plan.goal": "buy",
        "plan.items": ["a", "b"],
        "iter": 1,
    }


# ---------- _coerce ----------


def test_coerce_short_string_passes_through() -> None:
    assert _coerce("hello") == "hello"


def test_coerce_int_passes_through() -> None:
    assert _coerce(42) == 42


def test_coerce_bool_passes_through() -> None:
    assert _coerce(True) is True


def test_coerce_float_passes_through() -> None:
    assert _coerce(3.14) == 3.14


def test_coerce_none_becomes_empty_string() -> None:
    """None is not an OTel-compatible attribute value."""
    assert _coerce(None) == ""


def test_coerce_dict_becomes_json_string() -> None:
    result = _coerce({"a": 1, "b": "two"})
    assert isinstance(result, str)
    # Order-stable serialization for the simple case
    assert '"a"' in result and '"b"' in result


def test_coerce_list_becomes_json_string() -> None:
    assert _coerce([1, 2, 3]) == "[1, 2, 3]"


def test_coerce_long_string_truncates_with_marker() -> None:
    long_text = "x" * (_MAX_ATTRIBUTE_VALUE_LEN + 100)
    out = _coerce(long_text)
    assert isinstance(out, str)
    assert out.endswith("...[truncated]")
    assert len(out) == _MAX_ATTRIBUTE_VALUE_LEN + len("...[truncated]")


def test_coerce_unserialisable_falls_back_to_str() -> None:
    """Custom objects that aren't JSON-serialisable still produce a
    string, never raise — agent crashes are not acceptable."""

    class Custom:
        def __str__(self) -> str:
            return "custom-repr"

    out = _coerce(Custom())
    assert isinstance(out, str)
    assert "custom-repr" in out


# ---------- _build_attributes ----------


def test_build_attributes_minimal_event() -> None:
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    attrs = _build_attributes(e)
    assert attrs == {"session_id": "s1", "duration_ms": -1}


def test_build_attributes_full_event() -> None:
    e = AgentEvent(
        session_id="s1",
        type=AgentEventType.TOOL_RESULT,
        node="apple_orchard",
        duration_ms=99,
        payload={"result": {"items": 3, "total": 9.5}},
    )
    attrs = _build_attributes(e)
    assert attrs["session_id"] == "s1"
    assert attrs["node"] == "apple_orchard"
    assert attrs["duration_ms"] == 99
    assert attrs["payload.result.items"] == 3
    assert attrs["payload.result.total"] == 9.5


def test_build_attributes_handles_empty_payload() -> None:
    e = AgentEvent(session_id="s1", type=AgentEventType.COMPLETE)
    attrs = _build_attributes(e)
    # Only the top-level fields; no payload.* keys
    assert set(attrs.keys()) == {"session_id", "duration_ms"}


def test_build_attributes_keeps_attribute_values_otel_compatible() -> None:
    """Every value in the attribute dict must be a primitive or a
    string (per OTel SDK requirements). No dicts, no None, no custom
    objects."""

    class CustomObj:
        def __str__(self) -> str:
            return "custom"

    e = AgentEvent(
        session_id="s1",
        type=AgentEventType.PLAN_COMPLETE,
        payload={
            "list_field": [1, 2, 3],
            "obj_field": CustomObj(),
            "none_field": None,
            "scalar_field": 42,
        },
    )
    attrs = _build_attributes(e)
    for key, value in attrs.items():
        assert isinstance(
            value, str | int | float | bool
        ), f"attribute {key!r} has non-primitive type {type(value).__name__}"
    # The list became a JSON string
    assert attrs["payload.list_field"] == "[1, 2, 3]"
    # The custom object got str()'d
    assert "custom" in attrs["payload.obj_field"]
    # None became empty string
    assert attrs["payload.none_field"] == ""
    # The scalar passed through
    assert attrs["payload.scalar_field"] == 42
