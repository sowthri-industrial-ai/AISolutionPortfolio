"""Unit tests for the Cosmos memory layer.

Tests inject mocked container handles via the public constructor — the
production-only :meth:`CosmosProvider.from_endpoint` is exercised by the
integration suite against the real Cosmos account.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.memory.cosmos import CosmosProvider, CosmosSink, _event_to_doc
from framework.observability.events import AgentEvent, AgentEventType


def _async_iter(items: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    """Build an async iterator over ``items`` for query_items mocking."""

    async def _gen() -> AsyncIterator[dict[str, Any]]:
        for item in items:
            yield item

    return _gen()


def _mock_container() -> MagicMock:
    """Mock with the four ContainerProxy methods we use."""
    c = MagicMock()
    c.create_item = AsyncMock()
    c.upsert_item = AsyncMock()
    c.read_item = AsyncMock()
    c.query_items = MagicMock()  # sync — returns the async iterator
    return c


@pytest.fixture
def sessions() -> MagicMock:
    return _mock_container()


@pytest.fixture
def traces() -> MagicMock:
    return _mock_container()


@pytest.fixture
def provider(sessions: MagicMock, traces: MagicMock) -> CosmosProvider:
    return CosmosProvider(sessions=sessions, traces=traces)


# ---------- _event_to_doc ----------


def test_event_to_doc_top_level_id_and_partition_key() -> None:
    e = AgentEvent(
        session_id="s1",
        type=AgentEventType.PLAN_START,
        node="planner",
        duration_ms=120,
        payload={"goal": "buy fruit"},
    )
    doc = _event_to_doc(e)
    assert doc["id"] == str(e.event_id)
    assert doc["sessionId"] == "s1"
    assert doc["type"] == "plan_start"
    assert doc["timestamp"] == e.timestamp.isoformat()
    assert doc["node"] == "planner"
    assert doc["duration_ms"] == 120
    assert doc["payload"] == {"goal": "buy fruit"}


def test_event_to_doc_handles_optional_fields() -> None:
    e = AgentEvent(session_id="s1", type=AgentEventType.COMPLETE)
    doc = _event_to_doc(e)
    assert doc["node"] is None
    assert doc["duration_ms"] is None
    assert doc["payload"] == {}


# ---------- session state ----------


async def test_save_session_state_upserts_with_partition_key(
    provider: CosmosProvider, sessions: MagicMock
) -> None:
    await provider.save_session_state("s1", {"goal": "x", "step": 2})
    sessions.upsert_item.assert_awaited_once()
    body = sessions.upsert_item.await_args.kwargs["body"]
    assert body == {
        "id": "s1",
        "sessionId": "s1",
        "state": {"goal": "x", "step": 2},
    }


async def test_get_session_state_returns_state_when_present(
    provider: CosmosProvider, sessions: MagicMock
) -> None:
    sessions.read_item.return_value = {
        "id": "s1",
        "sessionId": "s1",
        "state": {"k": "v"},
    }
    out = await provider.get_session_state("s1")
    assert out == {"k": "v"}
    args = sessions.read_item.await_args
    assert args.kwargs["item"] == "s1"
    assert args.kwargs["partition_key"] == "s1"


async def test_get_session_state_returns_none_on_not_found(
    provider: CosmosProvider, sessions: MagicMock
) -> None:
    class CosmosResourceNotFoundError(Exception):  # mimic SDK type by name
        pass

    sessions.read_item.side_effect = CosmosResourceNotFoundError("missing")
    out = await provider.get_session_state("s-missing")
    assert out is None


async def test_get_session_state_propagates_other_errors(
    provider: CosmosProvider, sessions: MagicMock
) -> None:
    sessions.read_item.side_effect = RuntimeError("network down")
    with pytest.raises(RuntimeError, match="network down"):
        await provider.get_session_state("s1")


async def test_get_session_state_returns_none_for_malformed_state(
    provider: CosmosProvider, sessions: MagicMock
) -> None:
    """Defense — if a doc lacks `state` or `state` is not a dict, return None."""
    sessions.read_item.return_value = {
        "id": "s1",
        "sessionId": "s1",
        "state": "this should not be a string",
    }
    out = await provider.get_session_state("s1")
    assert out is None


# ---------- traces ----------


async def test_write_trace_creates_event_doc(provider: CosmosProvider, traces: MagicMock) -> None:
    e = AgentEvent(session_id="s1", type=AgentEventType.TOOL_CALL, node="shop-A")
    await provider.write_trace(e)
    traces.create_item.assert_awaited_once()
    body = traces.create_item.await_args.kwargs["body"]
    assert body["id"] == str(e.event_id)
    assert body["sessionId"] == "s1"
    assert body["type"] == "tool_call"
    assert body["node"] == "shop-A"


async def test_query_traces_returns_list_in_order(
    provider: CosmosProvider, traces: MagicMock
) -> None:
    docs = [
        {"id": "1", "sessionId": "s1", "type": "plan_start"},
        {"id": "2", "sessionId": "s1", "type": "complete"},
    ]
    traces.query_items.return_value = _async_iter(docs)
    out = await provider.query_traces("s1")
    assert out == docs
    args = traces.query_items.call_args
    assert "WHERE c.sessionId = @sid" in args.kwargs["query"]
    assert args.kwargs["parameters"] == [{"name": "@sid", "value": "s1"}]
    assert args.kwargs["partition_key"] == "s1"


# ---------- CosmosSink ----------


async def test_cosmos_sink_delegates_to_write_trace() -> None:
    provider = MagicMock()
    provider.write_trace = AsyncMock()
    sink = CosmosSink(provider)
    e = AgentEvent(session_id="s1", type=AgentEventType.REFLECT)
    await sink.emit(e)
    provider.write_trace.assert_awaited_once_with(e)


# ---------- lifecycle ----------


async def test_close_calls_client_and_credential_close() -> None:
    client = MagicMock()
    client.close = AsyncMock()
    credential_close = AsyncMock()
    provider = CosmosProvider(
        sessions=_mock_container(),
        traces=_mock_container(),
        client=client,
        credential_close=credential_close,
    )
    await provider.close()
    client.close.assert_awaited_once()
    credential_close.assert_awaited_once()


async def test_close_is_safe_when_no_client_or_credential(
    provider: CosmosProvider,
) -> None:
    """Test-time CosmosProvider has no SDK client to close — must not raise."""
    await provider.close()


async def test_async_context_manager() -> None:
    client = MagicMock()
    client.close = AsyncMock()
    provider = CosmosProvider(
        sessions=_mock_container(),
        traces=_mock_container(),
        client=client,
    )
    async with provider as p:
        assert p is provider
    client.close.assert_awaited_once()
