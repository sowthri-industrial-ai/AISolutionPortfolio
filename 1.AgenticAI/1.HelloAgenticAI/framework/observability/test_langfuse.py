"""Unit tests for :class:`LangfuseSink`.

Both the Azure Key Vault SecretClient and the Langfuse SDK are mocked
throughout — no network, no real Key Vault calls, no real Langfuse
events. The real-deployment behaviour is exercised in the batch 8
smoke test against the live KV + Langfuse Cloud project.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from framework.observability.events import AgentEvent, AgentEventType
from framework.observability.langfuse import (
    _KV_SECRET_HOST,
    _KV_SECRET_PUBLIC_KEY,
    _KV_SECRET_SECRET_KEY,
    LangfuseSink,
    _tool_span_key,
)

# Public Langfuse key prefix is `pk-lf-`; secret is `sk-lf-`. Use real
# prefixes in fixtures so it's obvious when log output / debug prints
# show "real-looking" keys (still fake — these never reach the wire).
_FAKE_PK = "pk-lf-fake-public-key-1234"
_FAKE_SK = "sk-lf-fake-secret-key-5678"  # gitleaks:allow
_FAKE_HOST = "https://cloud.langfuse.com"


# ---------- mock helpers ----------


def _make_async_cm(inner: Any) -> MagicMock:
    """Build a mock async context manager whose ``__aenter__`` returns
    ``inner``. Used to wrap mocked DefaultAzureCredential and SecretClient
    so the ``async with ...`` blocks in ``_ensure_client`` work."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=inner)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _make_mock_secret_client(secrets: dict[str, str]) -> MagicMock:
    """Build a mock SecretClient whose ``get_secret(name)`` returns an
    object with ``.value`` set from the ``secrets`` dict. Missing
    secrets raise KeyError so tests can simulate "secret not in KV"."""
    kv = MagicMock()

    async def _get_secret(name: str) -> Any:
        if name not in secrets:
            raise KeyError(f"secret {name!r} not found in mock KV")
        return MagicMock(value=secrets[name])

    kv.get_secret = AsyncMock(side_effect=_get_secret)
    return kv


def _make_mock_langfuse_client() -> tuple[MagicMock, MagicMock, MagicMock]:
    """Build a mocked Langfuse client whose ``trace()`` returns a
    mocked trace whose ``span()`` returns a mocked span. Returns the
    triple ``(client, trace, span_factory)``; ``span_factory`` is the
    callable that records each ``trace.span(...)`` call so tests can
    inspect names + inputs."""
    span_factory = MagicMock()
    # span_factory(...) returns a fresh mock span each call
    span_factory.side_effect = lambda **kwargs: MagicMock(
        end=MagicMock(),
        kwargs_at_creation=kwargs,
    )

    trace = MagicMock()
    trace.span = span_factory
    trace.update = MagicMock()
    trace.event = MagicMock()
    trace.get_trace_url = MagicMock(return_value=f"{_FAKE_HOST}/trace/fake")

    client = MagicMock()
    client.trace = MagicMock(return_value=trace)
    client.flush = MagicMock()
    return client, trace, span_factory


def _patch_kv_and_langfuse(
    kv_secrets: dict[str, str],
    langfuse_client: MagicMock,
) -> tuple[Any, Any, Any]:
    """Return three ``patch`` context managers for the lazy-init imports
    inside ``LangfuseSink._ensure_client``. Use::

        cred_p, kv_p, lf_p = _patch_kv_and_langfuse(...)
        with cred_p, kv_p, lf_p:
            ...
    """
    cred_inner = MagicMock()
    cred_p = patch(
        "azure.identity.aio.DefaultAzureCredential",
        return_value=_make_async_cm(cred_inner),
    )
    kv_p = patch(
        "azure.keyvault.secrets.aio.SecretClient",
        return_value=_make_async_cm(_make_mock_secret_client(kv_secrets)),
    )
    lf_p = patch("langfuse.Langfuse", return_value=langfuse_client)
    return cred_p, kv_p, lf_p


def _full_kv_secrets() -> dict[str, str]:
    return {
        _KV_SECRET_PUBLIC_KEY: _FAKE_PK,
        _KV_SECRET_SECRET_KEY: _FAKE_SK,
        _KV_SECRET_HOST: _FAKE_HOST,
    }


# ---------- construction ----------


def test_construction_is_cheap_no_endpoint() -> None:
    """No KV call, no Langfuse SDK import, no auth at construction."""
    sink = LangfuseSink()
    assert sink._key_vault_endpoint is None
    assert sink._client is None
    assert sink._init_failed is False
    assert sink._traces == {}
    assert sink._open_spans == {}
    assert sink.is_armed is False


def test_construction_is_cheap_with_endpoint() -> None:
    sink = LangfuseSink(key_vault_endpoint="https://kv.example.vault.azure.net/")
    assert sink._client is None
    assert sink._init_failed is False
    assert sink.is_armed is True


# ---------- degraded mode: no KV endpoint ----------


async def test_emit_no_endpoint_is_silent_after_first_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No-endpoint construction is the test-fixture / pre-deploy case.
    First emit logs one warning, subsequent emits are silent."""
    sink = LangfuseSink(key_vault_endpoint=None)
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    with caplog.at_level(logging.WARNING, logger="framework.observability.langfuse"):
        await sink.emit(e)
        await sink.emit(e)
        await sink.emit(e)
    warnings = [r for r in caplog.records if "no Key Vault endpoint" in r.message]
    assert len(warnings) == 1
    assert sink.is_armed is False


# ---------- init failure paths ----------


async def test_init_failure_kv_unreachable_marks_sink_failed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SecretClient raises (network unreachable, malformed endpoint) →
    instance is permanently marked failed; subsequent emits no-op
    without re-attempting init."""
    sink = LangfuseSink(key_vault_endpoint="https://kv.example.vault.azure.net/")
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    with (
        patch(
            "azure.identity.aio.DefaultAzureCredential",
            return_value=_make_async_cm(MagicMock()),
        ),
        patch(
            "azure.keyvault.secrets.aio.SecretClient",
            side_effect=ConnectionError("simulated KV unreachable"),
        ),
        patch("langfuse.Langfuse"),
        caplog.at_level(logging.WARNING, logger="framework.observability.langfuse"),
    ):
        await sink.emit(e)
        await sink.emit(e)
    warnings = [r for r in caplog.records if "init failed" in r.message]
    assert len(warnings) == 1
    assert "ConnectionError" in warnings[0].message
    assert sink.is_armed is False


async def test_init_failure_secret_missing_marks_sink_failed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Key Vault returns successfully but a required secret is absent
    (typo'd name, secret never populated). Treat as init failure —
    Langfuse construction would fail downstream anyway."""
    sink = LangfuseSink(key_vault_endpoint="https://kv.example.vault.azure.net/")
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    incomplete_secrets = {_KV_SECRET_PUBLIC_KEY: _FAKE_PK}  # missing the other two
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(incomplete_secrets, MagicMock())
    with (
        cred_p,
        kv_p,
        lf_p,
        caplog.at_level(logging.WARNING, logger="framework.observability.langfuse"),
    ):
        await sink.emit(e)
    warnings = [r for r in caplog.records if "init failed" in r.message]
    assert len(warnings) == 1
    assert "KeyError" in warnings[0].message
    assert sink.is_armed is False


async def test_init_failure_langfuse_constructor_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """KV returns valid secrets but Langfuse() construction raises
    (invalid host, library version mismatch)."""
    sink = LangfuseSink(key_vault_endpoint="https://kv.example.vault.azure.net/")
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    cred_p = patch(
        "azure.identity.aio.DefaultAzureCredential",
        return_value=_make_async_cm(MagicMock()),
    )
    kv_p = patch(
        "azure.keyvault.secrets.aio.SecretClient",
        return_value=_make_async_cm(_make_mock_secret_client(_full_kv_secrets())),
    )
    lf_p = patch("langfuse.Langfuse", side_effect=ValueError("invalid Langfuse host"))
    with (
        cred_p,
        kv_p,
        lf_p,
        caplog.at_level(logging.WARNING, logger="framework.observability.langfuse"),
    ):
        await sink.emit(e)
    warnings = [r for r in caplog.records if "init failed" in r.message]
    assert len(warnings) == 1
    assert "ValueError" in warnings[0].message
    assert sink.is_armed is False


# ---------- happy path: init + per-event-type mapping ----------


async def test_init_only_fires_once() -> None:
    """Successful KV+Langfuse init must happen exactly once even under
    N concurrent emits. Double-checked-locking proof."""
    sink = LangfuseSink(key_vault_endpoint="https://kv.example.vault.azure.net/")
    client, _, _ = _make_mock_langfuse_client()
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_START)
    with cred_p, kv_p, lf_p as lf_class:
        await sink.emit(e)
        await sink.emit(e)
        await sink.emit(e)
    assert lf_class.call_count == 1


async def test_first_event_starts_a_trace_with_session_id_as_trace_id() -> None:
    """The Langfuse trace id IS the agent session id (1:1 mapping).
    Chainlit constructs the trace URL from the session_id without a
    round-trip; this is the contract."""
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, _trace, _ = _make_mock_langfuse_client()
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    e = AgentEvent(
        session_id="my-session-id",
        type=AgentEventType.PLAN_START,
        payload={"goal": "buy fruit"},
    )
    with cred_p, kv_p, lf_p:
        await sink.emit(e)
    client.trace.assert_called_once()
    assert client.trace.call_args.kwargs["id"] == "my-session-id"
    assert client.trace.call_args.kwargs["name"] == "agent_run"
    # PLAN_START's goal becomes the trace input
    assert client.trace.call_args.kwargs["input"] == "buy fruit"


async def test_subsequent_events_reuse_same_trace_for_same_session() -> None:
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, _, _ = _make_mock_langfuse_client()
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    with cred_p, kv_p, lf_p:
        await sink.emit(AgentEvent(session_id="s1", type=AgentEventType.PLAN_START))
        await sink.emit(AgentEvent(session_id="s1", type=AgentEventType.PLAN_COMPLETE))
        await sink.emit(AgentEvent(session_id="s1", type=AgentEventType.TOOL_CALL, node="x"))
    # Three emits, only one trace creation
    assert client.trace.call_count == 1


async def test_different_sessions_get_different_traces() -> None:
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, _, _ = _make_mock_langfuse_client()
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    with cred_p, kv_p, lf_p:
        await sink.emit(AgentEvent(session_id="s1", type=AgentEventType.PLAN_START))
        await sink.emit(AgentEvent(session_id="s2", type=AgentEventType.PLAN_START))
    assert client.trace.call_count == 2
    # Each call carries the right session id
    seen_ids = {call.kwargs["id"] for call in client.trace.call_args_list}
    assert seen_ids == {"s1", "s2"}


async def test_plan_start_opens_span_and_plan_complete_closes_it() -> None:
    """The ``plan`` span is opened on PLAN_START and closed (via
    ``span.end``) on PLAN_COMPLETE. Output payload comes from the
    PLAN_COMPLETE event."""
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, _trace, span_factory = _make_mock_langfuse_client()
    # Override side_effect with a fixed return_value so we can assert
    # against the same span object the sink received.
    plan_span = MagicMock(end=MagicMock())
    span_factory.side_effect = None
    span_factory.return_value = plan_span
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    with cred_p, kv_p, lf_p:
        await sink.emit(
            AgentEvent(
                session_id="s1",
                type=AgentEventType.PLAN_START,
                payload={"goal": "g"},
            )
        )
        await sink.emit(
            AgentEvent(
                session_id="s1",
                type=AgentEventType.PLAN_COMPLETE,
                payload={"plan": {"items": ["a"]}},
                duration_ms=100,
            )
        )
    # One span created (the plan span)
    assert span_factory.call_count == 1
    plan_span_call = span_factory.call_args_list[0]
    assert plan_span_call.kwargs["name"] == "plan"
    assert plan_span_call.kwargs["input"] == {"goal": "g"}
    # The span's end() was called with the PLAN_COMPLETE payload
    plan_span.end.assert_called_once()
    end_kwargs = plan_span.end.call_args.kwargs
    assert end_kwargs["output"] == {"plan": {"items": ["a"]}}


async def test_tool_call_opens_span_and_tool_result_closes_it() -> None:
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, _trace, span_factory = _make_mock_langfuse_client()
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    # Each span_factory call must return a UNIQUE mock so we can
    # distinguish opened-and-closed pairs.
    spans_created: list[MagicMock] = []

    def _make_span(**kwargs: Any) -> MagicMock:
        s = MagicMock(end=MagicMock(), kwargs=kwargs)
        spans_created.append(s)
        return s

    span_factory.side_effect = _make_span
    with cred_p, kv_p, lf_p:
        await sink.emit(
            AgentEvent(
                session_id="s1",
                type=AgentEventType.TOOL_CALL,
                node="apple_orchard",
                payload={"args": {"sku": "apple"}},
            )
        )
        await sink.emit(
            AgentEvent(
                session_id="s1",
                type=AgentEventType.TOOL_RESULT,
                node="apple_orchard",
                payload={"result": {"items": 1}},
            )
        )
    # One span (the apple_orchard tool span)
    assert len(spans_created) == 1
    assert spans_created[0].kwargs["name"] == "tool:apple_orchard"
    spans_created[0].end.assert_called_once()


async def test_same_tool_called_twice_in_one_session_paired_correctly() -> None:
    """Two sequential TOOL_CALL/TOOL_RESULT pairs for the same node
    must each open + close their own span. The agent loop is strictly
    sequential per session, so the second TOOL_CALL never overlaps
    the first TOOL_RESULT."""
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, _trace, span_factory = _make_mock_langfuse_client()
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    spans_created: list[MagicMock] = []

    def _make_span(**kwargs: Any) -> MagicMock:
        s = MagicMock(end=MagicMock(), kwargs=kwargs)
        spans_created.append(s)
        return s

    span_factory.side_effect = _make_span
    with cred_p, kv_p, lf_p:
        for _ in range(2):
            await sink.emit(AgentEvent(session_id="s1", type=AgentEventType.TOOL_CALL, node="x"))
            await sink.emit(AgentEvent(session_id="s1", type=AgentEventType.TOOL_RESULT, node="x"))
    assert len(spans_created) == 2
    for s in spans_created:
        assert s.kwargs["name"] == "tool:x"
        s.end.assert_called_once()


async def test_reflect_creates_standalone_span() -> None:
    """REFLECT is point-in-time (no pairing) but renders as a span so
    the Langfuse tree shows it alongside plan/tool pairs."""
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, _trace, span_factory = _make_mock_langfuse_client()
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    span = MagicMock(end=MagicMock())
    span_factory.side_effect = None
    span_factory.return_value = span
    with cred_p, kv_p, lf_p:
        await sink.emit(
            AgentEvent(
                session_id="s1",
                type=AgentEventType.REFLECT,
                payload={"done": True, "answer": "ok"},
            )
        )
    span_factory.assert_called_once()
    assert span_factory.call_args.kwargs["name"] == "reflect"
    # Standalone spans end immediately with the same payload as output
    span.end.assert_called_once()


async def test_schema_validation_failed_creates_error_level_span() -> None:
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, _, span_factory = _make_mock_langfuse_client()
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    span = MagicMock(end=MagicMock())
    span_factory.side_effect = None
    span_factory.return_value = span
    with cred_p, kv_p, lf_p:
        await sink.emit(
            AgentEvent(
                session_id="s1",
                type=AgentEventType.SCHEMA_VALIDATION_FAILED,
                node="plan",
                payload={"model": "FruitMarketPlan", "attempt": 1},
            )
        )
    assert span_factory.call_args.kwargs["name"] == "schema_validation_failed"
    assert span_factory.call_args.kwargs["level"] == "ERROR"


async def test_guardrail_blocked_creates_error_level_span_with_gate_in_name() -> None:
    """The span name includes the gate (input vs output) so the Langfuse
    tree visually distinguishes the two block types at a glance."""
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, _, span_factory = _make_mock_langfuse_client()
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    span = MagicMock(end=MagicMock())
    span_factory.side_effect = None
    span_factory.return_value = span
    with cred_p, kv_p, lf_p:
        await sink.emit(
            AgentEvent(
                session_id="s1",
                type=AgentEventType.GUARDRAIL_BLOCKED,
                payload={"gate": "input", "categories": ["Hate"]},
            )
        )
    assert span_factory.call_args.kwargs["name"] == "guardrail_blocked:input"
    assert span_factory.call_args.kwargs["level"] == "ERROR"


async def test_complete_updates_trace_output_and_clears_bookkeeping() -> None:
    """COMPLETE updates the trace's output to the final answer and
    drops the in-memory map entry. Subsequent events for the same
    session_id would create a NEW trace (rare/probably-never happens
    in practice — agent runs are one COMPLETE per session)."""
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, trace, _ = _make_mock_langfuse_client()
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    with cred_p, kv_p, lf_p:
        await sink.emit(AgentEvent(session_id="s1", type=AgentEventType.PLAN_START))
        assert "s1" in sink._traces
        await sink.emit(
            AgentEvent(
                session_id="s1",
                type=AgentEventType.COMPLETE,
                payload={"final_answer": "the answer"},
            )
        )
    trace.update.assert_called_once()
    assert trace.update.call_args.kwargs["output"] == "the answer"
    # bookkeeping cleared
    assert "s1" not in sink._traces


async def test_complete_clears_orphan_open_spans_for_the_session() -> None:
    """Defensive: if a session ends with an unclosed span (e.g. the
    agent crashed mid-tool-call), COMPLETE clears the bookkeeping so
    the dict doesn't leak."""
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, _, _ = _make_mock_langfuse_client()
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    with cred_p, kv_p, lf_p:
        await sink.emit(AgentEvent(session_id="s1", type=AgentEventType.PLAN_START))
        await sink.emit(AgentEvent(session_id="s1", type=AgentEventType.TOOL_CALL, node="x"))
        # No TOOL_RESULT / PLAN_COMPLETE — straight to COMPLETE
        await sink.emit(
            AgentEvent(
                session_id="s1",
                type=AgentEventType.COMPLETE,
                payload={"final_answer": "premature"},
            )
        )
    # Both stale entries cleared
    assert sink._open_spans == {}
    assert sink._traces == {}


async def test_close_span_with_no_matching_start_warns_and_skips(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If TOOL_RESULT arrives without a prior TOOL_CALL (impossible
    under normal control flow but defensive), log + skip; do not
    crash."""
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, _, _ = _make_mock_langfuse_client()
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    with (
        cred_p,
        kv_p,
        lf_p,
        caplog.at_level(logging.WARNING, logger="framework.observability.langfuse"),
    ):
        await sink.emit(AgentEvent(session_id="s1", type=AgentEventType.TOOL_RESULT, node="x"))
    warnings = [r for r in caplog.records if "no matching open span" in r.message]
    assert len(warnings) == 1


# ---------- per-emit failure ----------


async def test_per_emit_failure_logs_and_stays_armed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If trace/span creation raises (transient API error), THIS event
    is dropped but the instance stays armed for next call."""
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, _, _ = _make_mock_langfuse_client()
    client.trace = MagicMock(side_effect=RuntimeError("transient Langfuse hiccup"))
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    with (
        cred_p,
        kv_p,
        lf_p,
        caplog.at_level(logging.WARNING, logger="framework.observability.langfuse"),
    ):
        await sink.emit(AgentEvent(session_id="s1", type=AgentEventType.PLAN_START))
    assert sink.is_armed is True  # stays armed
    warnings = [r for r in caplog.records if "emit failed" in r.message]
    assert len(warnings) == 1


# ---------- close() lifecycle ----------


async def test_close_flushes_client_and_clears_bookkeeping() -> None:
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, _, _ = _make_mock_langfuse_client()
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    with cred_p, kv_p, lf_p:
        await sink.emit(AgentEvent(session_id="s1", type=AgentEventType.PLAN_START))
        await sink.close()
    client.flush.assert_called_once()
    assert sink._traces == {}
    assert sink._open_spans == {}


async def test_close_is_safe_when_never_initialised() -> None:
    """close() on a never-emitted sink (e.g. test fixture, agent
    constructed but never run) must not raise."""
    sink = LangfuseSink()
    await sink.close()  # no-op, no client to flush


async def test_close_swallows_flush_errors(caplog: pytest.LogCaptureFixture) -> None:
    """Flush failures during close (e.g. Langfuse Cloud unreachable at
    shutdown) must not propagate — agent shutdown shouldn't crash on
    observability."""
    sink = LangfuseSink(key_vault_endpoint="https://kv.example/")
    client, _, _ = _make_mock_langfuse_client()
    client.flush = MagicMock(side_effect=ConnectionError("flush couldn't reach LF"))
    cred_p, kv_p, lf_p = _patch_kv_and_langfuse(_full_kv_secrets(), client)
    with (
        cred_p,
        kv_p,
        lf_p,
        caplog.at_level(logging.WARNING, logger="framework.observability.langfuse"),
    ):
        await sink.emit(AgentEvent(session_id="s1", type=AgentEventType.PLAN_START))
        await sink.close()  # must not raise
    warnings = [r for r in caplog.records if "flush failed" in r.message]
    assert len(warnings) == 1


# ---------- _tool_span_key helper ----------


def test_tool_span_key_includes_node() -> None:
    e = AgentEvent(session_id="s1", type=AgentEventType.TOOL_CALL, node="apple_orchard")
    assert _tool_span_key(e) == "tool:apple_orchard"


def test_tool_span_key_falls_back_when_node_is_none() -> None:
    """Defensive: TOOL_CALL events should always carry a node, but the
    key helper handles None to avoid a crash if a future caller
    bypasses the convention."""
    e = AgentEvent(session_id="s1", type=AgentEventType.TOOL_CALL)
    assert _tool_span_key(e) == "tool:<unknown>"
