"""AppInsightsSink — App Insights ingestion via OpenTelemetry.

Maps each :class:`AgentEvent` to an OTel span whose name is the event
type and whose attributes carry ``session_id`` + ``node`` +
``duration_ms`` + the flattened payload. The Azure Monitor exporter
sends the spans to App Insights' ``requests`` / ``dependencies`` tables
(by SpanKind), where the Phase 4 workbook queries them via KQL.

**Lazy-init pattern** — consistent with
:class:`framework.guardrails.content_safety.ContentSafetyClient` and
the Phase 4 :class:`LangfuseSink`:

* Construction is cheap: no I/O, no SDK config, no OTel setup.
* The Azure Monitor exporter + tracer are built on the FIRST
  :meth:`emit` call.
* Three degraded paths all return silently (no exception, no event
  emitted):
  1. **No connection string** (``connection_string=None``) → instance
     is permanently in pass-through. One warning logged on the first
     emit.
  2. **Init failure** (malformed connection string, network unreachable
     during exporter setup) → instance is permanently marked failed.
     One warning logged on the failing attempt.
  3. **Per-emit failure** (transient tracer error, attribute coercion
     bug) → THIS event is dropped, the instance stays armed. One
     warning per failed emit.

The agent NEVER crashes because App Insights is unreachable or
misconfigured. Fail-open is the deliberate default — observability is
best-effort, agent availability is guaranteed.

**Why spans, not OTel events?** OTel ``span.add_event`` puts data in the
``traces`` table with customDimensions, which is harder to chart in
workbooks. Spans go to ``requests`` (INTERNAL kind) and ``dependencies``
(CLIENT/PRODUCER kind), which the workbook's "events per minute by type"
chart can query as ``requests | where name in (...) | summarize count()
by bin(timestamp, 1m), name``. Span duration is effectively zero (the
``with`` block scope) — we carry the real duration as the ``duration_ms``
attribute. Simpler than pairing START/COMPLETE events on the SDK side.

**Connection string env var:** The SDK auto-discovers
``APPLICATIONINSIGHTS_CONNECTION_STRING`` from the environment if no
explicit string is passed to ``configure_azure_monitor``. Phase 4 batch
7 threads this exact env-var name into the Container App's env block.
The sink accepts a string at construction time to keep tests offline
and to support per-instance routing if a future project ever needs
multiple App Insights destinations.

**``configure_azure_monitor`` is process-wide.** The first call sets up
the global OTel tracer provider; subsequent calls with the same
connection string are documented as no-ops, but we serialize them with
an instance lock anyway so multiple ``AppInsightsSink`` instances in
the same process behave deterministically.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

from framework.observability.events import AgentEvent

logger = logging.getLogger(__name__)


_MAX_ATTRIBUTE_VALUE_LEN = 8192
"""Maximum string length for one OTel attribute value.

The OTel SDK applies its own (~32KB) truncation on the wire; we cap
much lower so KQL queries against ``customDimensions`` stay fast and
the App Insights ingestion cost stays low. Lists and dicts get JSON-
stringified; this is the post-serialization cap. Truncation is marked
with a ``...[truncated]`` suffix so the attribute is obviously
incomplete in workbook tables."""


class AppInsightsSink:
    """Async :class:`framework.observability.events.EventSink` that
    exports :class:`AgentEvent`\\s as OpenTelemetry spans to App
    Insights via the Azure Monitor exporter.

    See module docstring for lifecycle and failure semantics.
    """

    def __init__(self, connection_string: str | None = None) -> None:
        self._connection_string = connection_string
        # Tracer is built lazily on first emit. Typed ``Any`` to avoid
        # eagerly importing the OTel + Azure Monitor stack at framework
        # import time — tests that don't exercise observability shouldn't
        # pay the import cost.
        self._tracer: Any | None = None
        self._init_lock = asyncio.Lock()
        self._init_failed = False

    @property
    def is_armed(self) -> bool:
        """Whether the sink has a connection string AND hasn't failed
        init. Useful for tests and UI graceful-degrade detection.

        Returns ``True`` *before* the tracer has actually been built —
        the lazy-init may not have fired yet. ``emit()`` is what
        actually exercises the path."""
        return self._connection_string is not None and not self._init_failed

    async def _ensure_tracer(self) -> Any | None:
        """Lazy-init the OTel tracer + Azure Monitor exporter. Returns
        the tracer or ``None`` if the instance is in degraded/failed
        mode. Double-checked-locking fast path — once initialised or
        marked failed, no lock acquired on subsequent calls."""
        if self._tracer is not None:
            return self._tracer
        if self._init_failed:
            return None
        async with self._init_lock:
            if self._tracer is not None:
                return self._tracer
            if self._init_failed:
                return None
            if not self._connection_string:
                self._init_failed = True
                logger.warning(
                    "AppInsightsSink has no connection string configured; events will be "
                    "silently dropped for the instance lifetime"
                )
                return None
            try:
                from azure.monitor.opentelemetry import configure_azure_monitor
                from opentelemetry import trace

                configure_azure_monitor(connection_string=self._connection_string)
                self._tracer = trace.get_tracer("framework.agent.events")
            except Exception as exc:
                logger.warning(
                    "AppInsightsSink init failed (%s); events will be silently dropped "
                    "for the instance lifetime: %r",
                    type(exc).__name__,
                    exc,
                )
                self._init_failed = True
                return None
        return self._tracer

    async def emit(self, event: AgentEvent) -> None:
        """Export ``event`` as an OTel span to App Insights.

        No-op if the sink is degraded (no connection string, init
        failed, or per-emit error). Agent loop is never affected by
        sink failures.
        """
        tracer = await self._ensure_tracer()
        if tracer is None:
            return
        try:
            attributes = _build_attributes(event)
            # ``start_as_current_span`` has a near-zero scope (the
            # ``with`` body is empty); the span's real duration lives in
            # the ``duration_ms`` attribute. The span name (= event
            # type) is what the workbook groups by.
            with tracer.start_as_current_span(event.type.value, attributes=attributes):
                pass
        except Exception as exc:
            logger.warning(
                "AppInsightsSink emit failed for event %s; this event lost, instance stays "
                "armed for the next: %r",
                event.type.value,
                exc,
            )


# ---------- attribute building ----------


def _build_attributes(event: AgentEvent) -> dict[str, Any]:
    """Flatten an :class:`AgentEvent` into an OTel-compatible attribute
    dict.

    OTel attribute values must be ``str | int | float | bool`` or
    homogeneous lists thereof. The flattening rules:

    * Top-level event fields → top-level attributes: ``session_id``,
      ``node`` (if non-null), ``duration_ms``.
    * ``event.payload`` is one-level flattened: ``{"plan": {"goal":
      "X"}}`` → ``payload.plan.goal = "X"``. Workbook KQL stays readable.
    * Lists are NOT unrolled (they become JSON strings via
      :func:`_coerce`). Workbooks rarely chart over list-of-strings;
      stringifying keeps the queries simple.
    """
    attrs: dict[str, Any] = {
        "session_id": event.session_id,
        "duration_ms": event.duration_ms if event.duration_ms is not None else -1,
    }
    if event.node is not None:
        attrs["node"] = event.node
    for key, value in _flatten(event.payload).items():
        attrs[f"payload.{key}"] = _coerce(value)
    return attrs


def _flatten(d: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Recursively flatten nested dicts to dotted keys. Lists are NOT
    descended into (they're stringified at the leaf by :func:`_coerce`).

    Example::

        {"plan": {"goal": "buy", "items": ["a", "b"]}}
        → {"plan.goal": "buy", "plan.items": ["a", "b"]}
    """
    out: dict[str, Any] = {}
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, Mapping):
            out.update(_flatten(v, full_key))
        else:
            out[full_key] = v
    return out


def _coerce(value: Any) -> str | int | float | bool:
    """Coerce a leaf value to an OTel-compatible attribute type.

    * ``str | int | float | bool`` pass through (string is length-capped).
    * ``None`` → empty string.
    * Anything else (lists, dicts, custom objects) → JSON string with
      ``default=str`` fallback, length-capped.

    Length cap is :data:`_MAX_ATTRIBUTE_VALUE_LEN`; truncation marked
    with a ``...[truncated]`` suffix.
    """
    if isinstance(value, str):
        return _maybe_truncate(value)
    # ``bool`` is a subclass of ``int``; the isinstance union handles both.
    if isinstance(value, bool | int | float):
        return value
    if value is None:
        return ""
    # Lists, dicts, dataclasses, BaseModels, anything else: JSON-stringify
    # with ``default=str`` so non-serialisable objects don't crash.
    try:
        s = json.dumps(value, default=str)
    except (TypeError, ValueError):
        s = str(value)
    return _maybe_truncate(s)


def _maybe_truncate(s: str) -> str:
    if len(s) <= _MAX_ATTRIBUTE_VALUE_LEN:
        return s
    return s[:_MAX_ATTRIBUTE_VALUE_LEN] + "...[truncated]"
