"""Cosmos DB persistence — session state + agent trace events.

The Cosmos account is configured AAD-only (``disableLocalAuth: true`` in
``infra/modules/cosmos.bicep``). The runtime managed identity holds the
Cosmos DB Built-in Data Contributor role at account scope, granted by the
same module.

Two containers in the ``agent`` database, both partitioned by
``/sessionId``:

* ``sessions`` — one document per session, holds the agent's working state
  between turns. Upserted as state evolves.
* ``traces`` — one document per :class:`AgentEvent`. Append-only.

The :class:`CosmosSink` here is the production trace sink for
:class:`framework.observability.AgentEventEmitter`. It lives in this
module (not ``framework/observability``) to avoid an inversion: events
shouldn't depend on memory; memory CAN depend on events.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

from framework.observability.events import AgentEvent

DEFAULT_DATABASE = "agent"
SESSIONS_CONTAINER = "sessions"
TRACES_CONTAINER = "traces"


# Container / client types are typed Any: the azure-cosmos SDK signatures
# (overloaded keyword-only args, AsyncItemPaged returns) don't compose
# cleanly into a small Protocol, and the value of constraining them in the
# constructor is low — the integration suite exercises the real SDK end-
# to-end. Unit tests pass plain MagicMock instances.


class CosmosProvider:
    """Async Cosmos data plane — session state + trace persistence.

    Constructor takes pre-built container handles (test-friendly); the
    :meth:`from_endpoint` classmethod wires :class:`DefaultAzureCredential`
    + the SDK for production.
    """

    def __init__(
        self,
        *,
        sessions: Any,
        traces: Any,
        client: Any | None = None,
        credential_close: Any | None = None,
    ) -> None:
        self._sessions = sessions
        self._traces = traces
        self._client = client
        self._credential_close = credential_close

    @classmethod
    def from_endpoint(
        cls,
        *,
        endpoint: str,
        database: str = DEFAULT_DATABASE,
    ) -> CosmosProvider:
        """Production factory — wires DefaultAzureCredential to azure-cosmos."""
        from azure.cosmos.aio import CosmosClient
        from azure.identity.aio import DefaultAzureCredential

        credential = DefaultAzureCredential()
        client = CosmosClient(url=endpoint, credential=credential)
        db = client.get_database_client(database)
        return cls(
            sessions=db.get_container_client(SESSIONS_CONTAINER),
            traces=db.get_container_client(TRACES_CONTAINER),
            client=client,
            credential_close=credential.close,
        )

    # ----- sessions -----

    async def save_session_state(
        self,
        session_id: str,
        state: dict[str, Any],
    ) -> None:
        """Upsert the working state for ``session_id`` (one doc per session)."""
        await self._sessions.upsert_item(
            body={
                "id": session_id,
                "sessionId": session_id,
                "state": state,
            }
        )

    async def get_session_state(self, session_id: str) -> dict[str, Any] | None:
        """Read the working state for ``session_id`` or return None if absent."""
        try:
            doc = await self._sessions.read_item(
                item=session_id,
                partition_key=session_id,
            )
        except Exception as exc:  # azure.cosmos.exceptions.CosmosResourceNotFoundError
            if type(exc).__name__ == "CosmosResourceNotFoundError":
                return None
            raise
        state = doc.get("state")
        return state if isinstance(state, dict) else None

    # ----- traces -----

    async def write_trace(self, event: AgentEvent) -> None:
        """Append one trace document for ``event``."""
        await self._traces.create_item(body=_event_to_doc(event))

    async def query_traces(self, session_id: str) -> list[dict[str, Any]]:
        """Read every trace doc for ``session_id`` (oldest first by timestamp)."""
        query = "SELECT * FROM c WHERE c.sessionId = @sid ORDER BY c.timestamp ASC"
        items = self._traces.query_items(
            query=query,
            parameters=[{"name": "@sid", "value": session_id}],
            partition_key=session_id,
        )
        return [item async for item in items]

    # ----- lifecycle -----

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
        if self._credential_close is not None:
            await self._credential_close()

    async def __aenter__(self) -> CosmosProvider:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()


class CosmosSink:
    """EventSink that persists every event as a Cosmos `traces` doc.

    Plug into :class:`AgentEventEmitter` to make agent runs queryable and
    visible in the integration tests / Phase 4 workbooks.
    """

    def __init__(self, provider: CosmosProvider) -> None:
        self._provider = provider

    async def emit(self, event: AgentEvent) -> None:
        await self._provider.write_trace(event)


# ----- helpers -----


def _event_to_doc(event: AgentEvent) -> dict[str, Any]:
    """Render an :class:`AgentEvent` as a Cosmos document.

    Cosmos requires a top-level ``id`` (string) plus the partition-key
    field (``sessionId`` per the Bicep schema). All other fields are
    flattened — no nested envelope so workbook queries stay simple.
    """
    return {
        "id": str(event.event_id),
        "sessionId": event.session_id,
        "type": event.type.value,
        "timestamp": event.timestamp.isoformat(),
        "node": event.node,
        "duration_ms": event.duration_ms,
        "payload": event.payload,
    }
