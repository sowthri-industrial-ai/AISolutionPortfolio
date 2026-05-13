"""LangfuseSink — Langfuse Cloud trace ingestion.

Maps the agent loop's :class:`AgentEvent` stream to Langfuse traces +
spans:

* The first event for a ``session_id`` opens a Langfuse trace whose id
  IS the session id. (1:1 mapping keeps the trace URL deterministic —
  Chainlit reconstructs ``{host}/trace/{session_id}`` for the
  "🔗 View full trace in Langfuse" link without needing a round-trip.)
* ``PLAN_START`` / ``TOOL_CALL`` open spans on the trace; the matching
  ``PLAN_COMPLETE`` / ``TOOL_RESULT`` close them with output payloads
  and the AgentEvent's timestamp as ``end_time``.
* ``REFLECT`` becomes a standalone span (start+end immediate) so it
  shows up in the span tree alongside the plan/tool pairs.
* ``SCHEMA_VALIDATION_FAILED`` and ``GUARDRAIL_BLOCKED`` become
  standalone spans with ``level="ERROR"``. This is a deliberate UX
  choice, not a coincidence: Langfuse's trace-list view uses span
  level to flag runs with errors at a glance, which is exactly what
  we want for quick diagnosis of failed-validation or guardrail-
  blocked runs in the demo.
* ``COMPLETE`` updates the trace's ``output`` to the final answer and
  drops the in-memory bookkeeping for that session.

**Lazy-init pattern** — consistent with
:class:`framework.guardrails.content_safety.ContentSafetyClient` and
:class:`framework.observability.app_insights.AppInsightsSink`:

* Construction is cheap: no Key Vault call, no Langfuse SDK import, no
  network.
* On the FIRST :meth:`emit`, the sink fetches three secrets from Key
  Vault (``langfuse-public-key``, ``langfuse-secret-key``,
  ``langfuse-host``) via ``DefaultAzureCredential``, then constructs
  the Langfuse client.
* Three degraded paths all return silently with **one** warning per
  instance lifetime:
  1. No Key Vault endpoint configured → permanent pass-through.
  2. Init failure (Key Vault unreachable, secret missing, Langfuse
     client construction error) → permanently marked failed.
  3. Per-emit failure (transient API hiccup, malformed payload) →
     THIS event is dropped, instance stays armed for next call.

The agent **never crashes** because Langfuse is unreachable or
unconfigured. Fail-open is the deliberate default — observability is
best-effort, agent availability is guaranteed.

**Key Vault secrets** (populated out-of-band per Phase 4 kickoff):

* ``langfuse-public-key`` — Langfuse project public key (starts with
  ``pk-lf-``).
* ``langfuse-secret-key`` — Langfuse project secret key (starts with
  ``sk-lf-``). Read-only on Langfuse Cloud; safe to keep in KV.
* ``langfuse-host`` — Langfuse Cloud host URL (e.g.
  ``https://cloud.langfuse.com``).

**Memory note:** the in-memory ``_traces`` dict holds one
``StatefulTraceClient`` per active session. The COMPLETE event drops
the entry. If a session crashes mid-run (no COMPLETE), the entry
leaks until process restart. For Phase 4 demo this is harmless
(Chainlit sessions are short, container restarts daily); for a
long-running daemon, a TTL-based cleanup would be needed — captured
on the framework-v2 mental shelf.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from framework.observability.events import AgentEvent, AgentEventType

logger = logging.getLogger(__name__)


# Key Vault secret names — must match what Sowthri populated in batch 5
# kickoff. Constants here so a typo in one place is caught by mypy and
# the tests, not silently translated to an empty value at runtime.
_KV_SECRET_PUBLIC_KEY = "langfuse-public-key"
_KV_SECRET_SECRET_KEY = "langfuse-secret-key"
_KV_SECRET_HOST = "langfuse-host"


class LangfuseSink:
    """Async :class:`framework.observability.events.EventSink` that
    exports :class:`AgentEvent`\\s as Langfuse traces + spans.

    See module docstring for lifecycle and failure semantics.
    """

    def __init__(self, key_vault_endpoint: str | None = None) -> None:
        self._key_vault_endpoint = key_vault_endpoint
        # Langfuse client + per-session bookkeeping built lazily. Typed
        # ``Any`` to avoid eagerly importing the langfuse + azure-keyvault
        # stacks at framework import time.
        self._client: Any | None = None
        self._init_lock = asyncio.Lock()
        self._init_failed = False
        # session_id → StatefulTraceClient. One entry per active run.
        self._traces: dict[str, Any] = {}
        # (session_id, span_key) → StatefulSpanClient. Used to pair
        # *_START events to their *_COMPLETE event.
        self._open_spans: dict[tuple[str, str], Any] = {}

    @property
    def is_armed(self) -> bool:
        """Whether the sink has a Key Vault endpoint AND hasn't failed
        init. Useful for tests and for UI graceful-degrade (Chainlit
        renders the "View full trace in Langfuse" link only when this
        is ``True``).

        Returns ``True`` *before* the Langfuse client has actually been
        built — the lazy-init may not have fired yet."""
        return self._key_vault_endpoint is not None and not self._init_failed

    async def _ensure_client(self) -> Any | None:
        """Lazy-init the Langfuse client via Key Vault. Returns the
        client or ``None`` if the instance is in degraded/failed mode."""
        if self._client is not None:
            return self._client
        if self._init_failed:
            return None
        async with self._init_lock:
            if self._client is not None:
                return self._client
            if self._init_failed:
                return None
            if not self._key_vault_endpoint:
                self._init_failed = True
                logger.warning(
                    "LangfuseSink has no Key Vault endpoint configured; "
                    "events will be silently dropped for the instance lifetime"
                )
                return None
            try:
                from azure.identity.aio import DefaultAzureCredential
                from azure.keyvault.secrets.aio import SecretClient
                from langfuse import Langfuse  # type: ignore[import-untyped]

                async with (
                    DefaultAzureCredential() as cred,
                    SecretClient(self._key_vault_endpoint, cred) as kv,
                ):
                    pk = (await kv.get_secret(_KV_SECRET_PUBLIC_KEY)).value
                    sk = (await kv.get_secret(_KV_SECRET_SECRET_KEY)).value
                    host = (await kv.get_secret(_KV_SECRET_HOST)).value
                self._client = Langfuse(
                    public_key=pk,
                    secret_key=sk,
                    host=host,
                    # Deliberate override of the SDK default (3). When a
                    # sink has "drop this event and retry next time"
                    # semantics at the sink layer (per the lazy-init
                    # graceful-degrade contract above), internal SDK
                    # retry is a duplicate concern. Two retries in series
                    # (sink + SDK) waste time under sustained latency.
                    # The higher-level retry (sink) wins because it's
                    # more context-aware: it sees the event stream as
                    # continuous, where the SDK only sees one request in
                    # isolation. Future readers: do not "fix" this back
                    # to 3 thinking it improves reliability — it doesn't.
                    max_retries=1,
                )
            except Exception as exc:
                logger.warning(
                    "LangfuseSink init failed (%s); events will be silently dropped "
                    "for the instance lifetime: %r",
                    type(exc).__name__,
                    exc,
                )
                self._init_failed = True
                return None
        return self._client

    async def emit(self, event: AgentEvent) -> None:
        """Export ``event`` to Langfuse as part of the session's trace.

        No-op if the sink is degraded (no Key Vault endpoint, init
        failed, or per-emit error). Agent loop is never affected by
        sink failures.
        """
        client = await self._ensure_client()
        if client is None:
            return
        try:
            trace = self._ensure_trace(client, event)
            self._handle_event(trace, event)
        except Exception as exc:
            logger.warning(
                "LangfuseSink emit failed for event %s session=%s; this event lost, "
                "instance stays armed for the next: %r",
                event.type.value,
                event.session_id,
                exc,
            )

    def _ensure_trace(self, client: Any, event: AgentEvent) -> Any:
        """Return the trace for ``event.session_id``, creating it on the
        first event for that session.

        The trace id is the session id (1:1 mapping) so Chainlit can
        reconstruct ``{host}/trace/{session_id}`` for the link without a
        round-trip. The trace's ``input`` is set from the goal payload
        of PLAN_START (most common first-event); otherwise it's left
        unset and the COMPLETE event populates ``output``.
        """
        trace = self._traces.get(event.session_id)
        if trace is not None:
            return trace
        input_payload = (
            event.payload.get("goal") if event.type is AgentEventType.PLAN_START else None
        )
        trace = client.trace(
            id=event.session_id,
            name="agent_run",
            input=input_payload,
        )
        self._traces[event.session_id] = trace
        return trace

    def _handle_event(self, trace: Any, event: AgentEvent) -> None:
        """Per-event-type dispatch. Branches are exhaustive over the
        current ``AgentEventType`` set; unknown types are ignored
        (forward-compat — a future Phase 5+ event type won't crash this
        sink, it just won't be visualised in Langfuse until the mapping
        is added)."""
        if event.type is AgentEventType.PLAN_START:
            self._open_span(trace, event, key="plan")
        elif event.type is AgentEventType.PLAN_COMPLETE:
            self._close_span(event, key="plan")
        elif event.type is AgentEventType.TOOL_CALL:
            self._open_span(trace, event, key=_tool_span_key(event))
        elif event.type is AgentEventType.TOOL_RESULT:
            self._close_span(event, key=_tool_span_key(event))
        elif event.type is AgentEventType.REFLECT:
            self._standalone_span(trace, event, name="reflect")
        elif event.type is AgentEventType.SCHEMA_VALIDATION_FAILED:
            self._standalone_span(trace, event, name="schema_validation_failed", level="ERROR")
        elif event.type is AgentEventType.GUARDRAIL_BLOCKED:
            # Include the gate so the Langfuse span tree distinguishes
            # input-blocked vs output-blocked at a glance.
            gate = event.payload.get("gate", "unknown")
            self._standalone_span(trace, event, name=f"guardrail_blocked:{gate}", level="ERROR")
        elif event.type is AgentEventType.COMPLETE:
            self._finalize_trace(trace, event)

    def _open_span(self, trace: Any, event: AgentEvent, *, key: str) -> None:
        span = trace.span(
            name=key,
            input=event.payload,
            metadata={"node": event.node} if event.node is not None else None,
        )
        self._open_spans[(event.session_id, key)] = span

    def _close_span(self, event: AgentEvent, *, key: str) -> None:
        span = self._open_spans.pop((event.session_id, key), None)
        if span is None:
            # Missing START — emit a warning but don't crash. Happens if
            # COMPLETE arrives before its START (out-of-order) or the
            # session was created with a sink that started mid-run.
            logger.warning(
                "LangfuseSink received %s for session=%s key=%s with no matching open span; "
                "skipping span close",
                event.type.value,
                event.session_id,
                key,
            )
            return
        span.end(output=event.payload, end_time=event.timestamp)

    def _standalone_span(
        self,
        trace: Any,
        event: AgentEvent,
        *,
        name: str,
        level: str | None = None,
    ) -> None:
        """Start + immediately end a span. Used for non-paired events
        (REFLECT, SCHEMA_VALIDATION_FAILED, GUARDRAIL_BLOCKED). Carries
        the full payload as both input and output so the Langfuse UI
        shows everything in one place."""
        kwargs: dict[str, Any] = {"name": name, "input": event.payload}
        if level is not None:
            kwargs["level"] = level
        if event.node is not None:
            kwargs["metadata"] = {"node": event.node}
        span = trace.span(**kwargs)
        span.end(output=event.payload, end_time=event.timestamp)

    def _finalize_trace(self, trace: Any, event: AgentEvent) -> None:
        """COMPLETE handler — update the trace's output and drop the
        in-memory bookkeeping for the session. Also clears any spans
        still in :attr:`_open_spans` for this session (defensive: a
        misbehaving subclass might emit COMPLETE without a matching
        TOOL_RESULT, e.g. on an exception path)."""
        final_answer = event.payload.get("final_answer")
        trace.update(output=final_answer)
        self._traces.pop(event.session_id, None)
        stale = [k for k in self._open_spans if k[0] == event.session_id]
        for k in stale:
            self._open_spans.pop(k, None)

    async def close(self) -> None:
        """Flush pending Langfuse events and clear bookkeeping. Safe to
        call multiple times. Should be called by the agent context's
        ``aclose()`` so traces aren't lost on Chainlit session end."""
        client = self._client
        if client is not None:
            try:
                # Langfuse SDK is sync; flush() blocks until the queue
                # empties. We call it from the running event loop —
                # ``flush()`` is documented to be safe in this context.
                client.flush()
            except Exception as exc:
                logger.warning("LangfuseSink flush failed (events may be lost): %r", exc)
        self._traces.clear()
        self._open_spans.clear()


def _tool_span_key(event: AgentEvent) -> str:
    """Key for a tool span in :attr:`_open_spans`.

    Includes the tool name so the same session can call the same tool
    multiple times sequentially without span collisions. (Concurrent
    same-tool calls would still collide; the agent loop is strictly
    sequential per session, so this is fine for v1 — captured on the
    framework-v2 mental shelf as a future generalisation.)
    """
    if event.node is None:
        return "tool:<unknown>"
    return f"tool:{event.node}"
