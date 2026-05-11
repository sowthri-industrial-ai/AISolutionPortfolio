"""Composition factory for the fruit-market demo.

Wires :class:`FruitMarketAgent` against deployed Azure resources
(:class:`AzureOpenAIClient` + :class:`CosmosProvider`) and the six
:mod:`demo_fruitmarket.shops` tools, and returns a
:class:`FruitMarketContext` that bundles the agent + the resource handles.

Two factories:

* :func:`build_fruit_market_context` — test-friendly. Caller supplies the
  :class:`AzureOpenAIClient` and :class:`CosmosProvider` (typically mocks
  in unit tests, or real instances reused across an app).
* :func:`build_fruit_market_context_from_endpoints` — production. Wires
  :class:`DefaultAzureCredential` to both services and returns a fully
  prepared context. Used by the Chainlit app on each chat-session start.

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
A Cosmos blip or a Chainlit hiccup must not crash the agent loop.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from types import TracebackType

from demo_fruitmarket.agent import FruitMarketAgent
from demo_fruitmarket.shops import register_all_shops
from framework.llm.azure_openai import AzureOpenAIClient
from framework.memory.cosmos import CosmosProvider, CosmosSink
from framework.observability.events import (
    AgentEventEmitter,
    EventSink,
    LoggingSink,
)
from framework.tools.base import ToolRegistry


@dataclass
class FruitMarketContext:
    """Bundle of resources for one agent session.

    Caller is responsible for closing via :meth:`aclose` or by using the
    async-context-manager interface.
    """

    agent: FruitMarketAgent
    cosmos: CosmosProvider
    llm: AzureOpenAIClient

    async def aclose(self) -> None:
        """Close LLM and Cosmos handles in order."""
        await self.llm.close()
        await self.cosmos.close()

    async def __aenter__(self) -> FruitMarketContext:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()


def build_fruit_market_context(
    *,
    llm: AzureOpenAIClient,
    cosmos: CosmosProvider,
    extra_sinks: Sequence[EventSink] = (),
    max_iterations: int = 4,
) -> FruitMarketContext:
    """Compose the agent + tools + sinks given pre-built LLM and Cosmos.

    The default sink chain is ``[CosmosSink(cosmos), LoggingSink()]``.
    Caller-supplied ``extra_sinks`` are appended after the defaults — so
    a Chainlit sink fires after Cosmos persistence and after the dev log.

    The emitter swallows sink errors (production mode) — any individual
    sink failure is logged but does not break the agent loop.
    """
    sinks: list[EventSink] = [CosmosSink(cosmos), LoggingSink(), *extra_sinks]
    emitter = AgentEventEmitter(sinks, swallow_sink_errors=True)

    tools = ToolRegistry()
    register_all_shops(tools)

    agent = FruitMarketAgent(
        emitter=emitter,
        tools=tools,
        llm=llm,
        max_iterations=max_iterations,
    )
    return FruitMarketContext(agent=agent, cosmos=cosmos, llm=llm)


def build_fruit_market_context_from_endpoints(
    *,
    aoai_endpoint: str,
    cosmos_endpoint: str,
    extra_sinks: Sequence[EventSink] = (),
    max_iterations: int = 4,
) -> FruitMarketContext:
    """Production factory — wires DefaultAzureCredential to both services."""
    llm = AzureOpenAIClient.from_endpoint(endpoint=aoai_endpoint)
    cosmos = CosmosProvider.from_endpoint(endpoint=cosmos_endpoint)
    return build_fruit_market_context(
        llm=llm,
        cosmos=cosmos,
        extra_sinks=extra_sinks,
        max_iterations=max_iterations,
    )
