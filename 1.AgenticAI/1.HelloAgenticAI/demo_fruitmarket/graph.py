"""Composition factory for the fruit-market demo.

Wires :class:`FruitMarketAgent` against deployed Azure resources
(:class:`AzureOpenAIClient` + :class:`CosmosProvider`) and the six
:mod:`demo_fruitmarket.shops` tools, and returns a
:class:`FruitMarketContext` that bundles the agent + the resource handles.

Two factories:

* :func:`build_fruit_market_context` — test-friendly. Caller supplies the
  :class:`AzureOpenAIClient`, :class:`CosmosProvider`, and (optionally)
  a :class:`ContentSafetyClient` and the Phase 4 sinks (typically mocks
  in unit tests, or real instances reused across an app).
* :func:`build_fruit_market_context_from_endpoints` — production. Wires
  :class:`DefaultAzureCredential` to AOAI and Cosmos, optionally builds
  a :class:`ContentSafetyClient` from
  ``AZURE_CONTENT_SAFETY_ENDPOINT``, optionally builds an
  :class:`AppInsightsSink` from ``APPLICATIONINSIGHTS_CONNECTION_STRING``
  and a :class:`LangfuseSink` from ``AZURE_KEY_VAULT_ENDPOINT``. Used
  by the Chainlit app on each chat-session start.

Phase 4 wiring summary — every observability + guardrail component
follows the same fail-open contract: if its env-var configuration is
missing, the component no-ops and the agent runs unchanged. The
deployed Phase 3 demo behaviour is the strict subset where all three
env vars are missing; landing batch 7's Bicep wiring + batch 8's
deploy turns each component on without code changes here.

The :class:`FruitMarketContext` is an async context manager so the caller
gets a clean ``async with`` lifecycle:

.. code-block:: python

    async with build_fruit_market_context_from_endpoints(
        aoai_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        cosmos_endpoint=os.environ["AZURE_COSMOS_ENDPOINT"],
        extra_sinks=[ChainlitSink(...)],
    ) as ctx:
        result = await ctx.agent.run(user_goal, session_id=cl_session_id)

The emitter is built with ``swallow_sink_errors=True`` — production mode.
A Cosmos / App Insights / Langfuse / Chainlit hiccup must not crash
the agent loop.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from types import TracebackType

from demo_fruitmarket.agent import FruitMarketAgent
from demo_fruitmarket.shops import register_all_shops
from framework.guardrails.content_safety import ContentSafetyClient
from framework.llm.azure_openai import AzureOpenAIClient
from framework.memory.cosmos import CosmosProvider, CosmosSink
from framework.observability.app_insights import AppInsightsSink
from framework.observability.events import (
    AgentEventEmitter,
    EventSink,
    LoggingSink,
)
from framework.observability.langfuse import LangfuseSink
from framework.tools.base import ToolRegistry

logger = logging.getLogger(__name__)

# Canonical env-var names — must match what main.bicep threads into the
# Container App in batch 7. Constants here so a typo in one place is
# caught by mypy + the tests, not silently translated to a None at
# runtime that takes the degraded path.
_ENV_CONTENT_SAFETY_ENDPOINT = "AZURE_CONTENT_SAFETY_ENDPOINT"
_ENV_APP_INSIGHTS_CONN = "APPLICATIONINSIGHTS_CONNECTION_STRING"
_ENV_KEY_VAULT_ENDPOINT = "AZURE_KEY_VAULT_ENDPOINT"


@dataclass
class FruitMarketContext:
    """Bundle of resources for one agent session.

    Caller is responsible for closing via :meth:`aclose` or by using the
    async-context-manager interface. ``aclose()`` closes every owned
    resource even if an earlier close raises — observability sinks
    should never leak handles, and one slow flush shouldn't block the
    others.
    """

    agent: FruitMarketAgent
    cosmos: CosmosProvider
    llm: AzureOpenAIClient
    content_safety: ContentSafetyClient | None = None
    # Owned sinks that need explicit close. The Cosmos sink shares the
    # CosmosProvider's lifecycle; logging is stateless.
    _owned_sinks: list[EventSink] = field(default_factory=list)

    async def aclose(self) -> None:
        """Close every owned resource. Best-effort: a failure in one
        close does not skip the others. Observability flush errors
        shouldn't cause the agent context teardown to leak handles."""
        # LLM, Cosmos, Content Safety: each has its own async close.
        # Sinks (AppInsights, Langfuse) close last because they may
        # depend on the upstream resources being alive to flush
        # in-flight buffered events (rare, but defensive ordering).
        for closer in (
            self.llm.close,
            self.cosmos.close,
            self.content_safety.close if self.content_safety is not None else _noop_close,
        ):
            await _safe_close(closer)
        for sink in self._owned_sinks:
            close_attr = getattr(sink, "close", None)
            if close_attr is not None:
                await _safe_close(close_attr)

    async def __aenter__(self) -> FruitMarketContext:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()


async def _noop_close() -> None:
    return None


async def _safe_close(closer: Callable[[], Awaitable[None]]) -> None:
    """Call ``closer()`` and log on failure rather than propagate.

    Used by :meth:`FruitMarketContext.aclose` so one closer's failure
    doesn't skip the others. Sink flush errors at shutdown shouldn't
    cause the agent context teardown to leak handles.

    Used during shutdown/cleanup only. Propagating on close would
    leave subsequent resources unclosed, leaking handles. Logging and
    continuing ensures all owned resources get a chance to release.
    This diverges deliberately from the agent-loop pattern, where
    errors during a request propagate to surface failure to the
    user — at shutdown the user has already disconnected, so silent
    cleanup wins.
    """
    try:
        await closer()
    except Exception as exc:
        logger.warning(
            "FruitMarketContext.aclose: %s raised %r — continuing with remaining closers",
            getattr(closer, "__qualname__", repr(closer)),
            exc,
        )


def build_fruit_market_context(
    *,
    llm: AzureOpenAIClient,
    cosmos: CosmosProvider,
    content_safety: ContentSafetyClient | None = None,
    app_insights_sink: AppInsightsSink | None = None,
    langfuse_sink: LangfuseSink | None = None,
    extra_sinks: Sequence[EventSink] = (),
    max_iterations: int = 4,
) -> FruitMarketContext:
    """Compose the agent + tools + sinks given pre-built dependencies.

    Default sink chain (in this order):

    1. :class:`CosmosSink` — every event persisted as a Cosmos doc.
    2. :class:`LoggingSink` — always-on dev log.
    3. :class:`AppInsightsSink` — if supplied. No-op without conn string.
    4. :class:`LangfuseSink` — if supplied. No-op without KV secrets.
    5. ``extra_sinks`` (typically the Chainlit UI sink).

    Order matters: Cosmos and Logging are the persistent record; App
    Insights and Langfuse are queryable summaries; the UI sink fires
    last so the user sees the step before the trace is fully durable.
    The emitter swallows sink errors (production mode) — any individual
    sink failure is logged but does not break the agent loop.
    """
    sinks: list[EventSink] = [CosmosSink(cosmos), LoggingSink()]
    owned: list[EventSink] = []
    if app_insights_sink is not None:
        sinks.append(app_insights_sink)
        owned.append(app_insights_sink)
    if langfuse_sink is not None:
        sinks.append(langfuse_sink)
        owned.append(langfuse_sink)
    sinks.extend(extra_sinks)

    emitter = AgentEventEmitter(sinks, swallow_sink_errors=True)

    tools = ToolRegistry()
    register_all_shops(tools)

    agent = FruitMarketAgent(
        emitter=emitter,
        tools=tools,
        llm=llm,
        max_iterations=max_iterations,
        content_safety=content_safety,
    )
    return FruitMarketContext(
        agent=agent,
        cosmos=cosmos,
        llm=llm,
        content_safety=content_safety,
        _owned_sinks=owned,
    )


def build_fruit_market_context_from_endpoints(
    *,
    aoai_endpoint: str,
    cosmos_endpoint: str,
    extra_sinks: Sequence[EventSink] = (),
    max_iterations: int = 4,
) -> FruitMarketContext:
    """Production factory — wires DefaultAzureCredential to all services
    and constructs the Phase 4 observability + guardrails from env vars.

    Three env vars are read; each is optional. Missing → that
    component runs in its own degraded path (logs one warning, no-ops
    forever). The agent loop is unaffected.

    * ``AZURE_CONTENT_SAFETY_ENDPOINT`` →
      :class:`ContentSafetyClient` for input/output gates. If absent,
      ``content_safety=None`` and Phase 3 demo behaviour is preserved.
    * ``APPLICATIONINSIGHTS_CONNECTION_STRING`` →
      :class:`AppInsightsSink` for OTel-based App Insights ingestion.
    * ``AZURE_KEY_VAULT_ENDPOINT`` → :class:`LangfuseSink` for
      Langfuse Cloud trace + span ingestion (the sink lazily fetches
      the three Langfuse secrets from the vault on first emit).

    All three env vars are threaded into the Container App in batch
    7's Bicep update.
    """
    llm = AzureOpenAIClient.from_endpoint(endpoint=aoai_endpoint)
    cosmos = CosmosProvider.from_endpoint(endpoint=cosmos_endpoint)

    cs_endpoint = os.getenv(_ENV_CONTENT_SAFETY_ENDPOINT)
    content_safety = (
        ContentSafetyClient.from_endpoint(endpoint=cs_endpoint) if cs_endpoint else None
    )

    appi_conn = os.getenv(_ENV_APP_INSIGHTS_CONN)
    app_insights_sink = AppInsightsSink(connection_string=appi_conn) if appi_conn else None

    kv_endpoint = os.getenv(_ENV_KEY_VAULT_ENDPOINT)
    langfuse_sink = LangfuseSink(key_vault_endpoint=kv_endpoint) if kv_endpoint else None

    return build_fruit_market_context(
        llm=llm,
        cosmos=cosmos,
        content_safety=content_safety,
        app_insights_sink=app_insights_sink,
        langfuse_sink=langfuse_sink,
        extra_sinks=extra_sinks,
        max_iterations=max_iterations,
    )
