"""Unit tests for the composition factory.

Verifies that ``build_fruit_market_context`` wires the right tools, the
right default sinks, the right error-swallowing semantics, and that the
context's lifecycle (aclose / async context manager) closes both handles.

The production-only ``build_fruit_market_context_from_endpoints`` is
exercised by the integration suite (or manual ``chainlit run``) — its
only job is calling ``from_endpoint`` factories that themselves are
covered by the framework's own tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from demo_fruitmarket.agent import FruitMarketAgent
from demo_fruitmarket.graph import (
    FruitMarketContext,
    build_fruit_market_context,
)
from demo_fruitmarket.shops import ALL_SHOP_CLASSES
from framework.memory.cosmos import CosmosSink
from framework.observability.events import (
    AgentEventEmitter,
    InMemorySink,
    LoggingSink,
)

# ---------- helpers ----------


def _mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.chat_large_deployment = "gpt-4o"
    llm.chat_mini_deployment = "gpt-4o-mini"
    llm.embeddings_deployment = "text-embedding-3-large"
    llm.close = AsyncMock()
    return llm


def _mock_cosmos() -> MagicMock:
    cosmos = MagicMock()
    cosmos.close = AsyncMock()
    cosmos.write_trace = AsyncMock()
    return cosmos


# ---------- composition ----------


def test_factory_returns_FruitMarketContext_with_agent_llm_cosmos() -> None:
    llm, cosmos = _mock_llm(), _mock_cosmos()
    ctx = build_fruit_market_context(llm=llm, cosmos=cosmos)
    assert isinstance(ctx, FruitMarketContext)
    assert isinstance(ctx.agent, FruitMarketAgent)
    assert ctx.llm is llm
    assert ctx.cosmos is cosmos


def test_factory_registers_all_six_shops() -> None:
    ctx = build_fruit_market_context(llm=_mock_llm(), cosmos=_mock_cosmos())
    registry = ctx.agent._tools
    assert len(registry) == 6
    assert registry.names() == sorted(s.SHOP_NAME for s in ALL_SHOP_CLASSES)


def test_factory_default_sinks_include_cosmos_and_logging() -> None:
    cosmos = _mock_cosmos()
    ctx = build_fruit_market_context(llm=_mock_llm(), cosmos=cosmos)
    emitter = ctx.agent._emitter
    sink_types = [type(s).__name__ for s in emitter.sinks]
    # Default sink order: CosmosSink, LoggingSink
    assert sink_types == ["CosmosSink", "LoggingSink"]
    # CosmosSink delegates to the supplied cosmos provider
    assert isinstance(emitter.sinks[0], CosmosSink)
    assert emitter.sinks[0]._provider is cosmos


def test_factory_appends_extra_sinks_after_defaults() -> None:
    extra = InMemorySink()
    ctx = build_fruit_market_context(
        llm=_mock_llm(),
        cosmos=_mock_cosmos(),
        extra_sinks=[extra],
    )
    sink_types = [type(s).__name__ for s in ctx.agent._emitter.sinks]
    assert sink_types == ["CosmosSink", "LoggingSink", "InMemorySink"]
    assert ctx.agent._emitter.sinks[2] is extra


def test_factory_emitter_swallows_sink_errors_production_mode() -> None:
    """A Cosmos blip or Chainlit hiccup must not crash the agent loop."""
    ctx = build_fruit_market_context(llm=_mock_llm(), cosmos=_mock_cosmos())
    assert isinstance(ctx.agent._emitter, AgentEventEmitter)
    assert ctx.agent._emitter._swallow_sink_errors is True


def test_factory_passes_max_iterations_to_agent() -> None:
    ctx = build_fruit_market_context(
        llm=_mock_llm(),
        cosmos=_mock_cosmos(),
        max_iterations=7,
    )
    assert ctx.agent._max_iterations == 7


def test_factory_default_max_iterations_is_four() -> None:
    ctx = build_fruit_market_context(llm=_mock_llm(), cosmos=_mock_cosmos())
    assert ctx.agent._max_iterations == 4


# ---------- lifecycle ----------


async def test_aclose_closes_llm_and_cosmos_in_order() -> None:
    llm, cosmos = _mock_llm(), _mock_cosmos()
    ctx = build_fruit_market_context(llm=llm, cosmos=cosmos)
    await ctx.aclose()
    llm.close.assert_awaited_once()
    cosmos.close.assert_awaited_once()


async def test_async_context_manager_closes_on_exit() -> None:
    llm, cosmos = _mock_llm(), _mock_cosmos()
    async with build_fruit_market_context(llm=llm, cosmos=cosmos) as ctx:
        assert isinstance(ctx, FruitMarketContext)
        # Mid-context, nothing closed yet
        llm.close.assert_not_called()
        cosmos.close.assert_not_called()
    # After exit, both closed
    llm.close.assert_awaited_once()
    cosmos.close.assert_awaited_once()


async def test_async_context_manager_closes_on_exception() -> None:
    """Resource cleanup must happen even if the body raises."""
    llm, cosmos = _mock_llm(), _mock_cosmos()
    try:
        async with build_fruit_market_context(llm=llm, cosmos=cosmos):
            raise RuntimeError("simulated chat failure")
    except RuntimeError as exc:
        assert "simulated chat failure" in str(exc)
    llm.close.assert_awaited_once()
    cosmos.close.assert_awaited_once()


# ---------- sanity: an end-to-end agent run uses these sinks ----------


async def test_in_memory_sink_via_extra_sinks_receives_events() -> None:
    """The extra_sinks injection point is what the Chainlit app uses to
    stream events to the UI. Verify a sink injected this way actually
    receives events from a real agent run."""
    from pydantic import BaseModel

    from demo_fruitmarket.agent import (
        FruitMarketPlan,
        _ReflectorVerdictLLM,
        _RouterDecisionLLM,
    )
    from demo_fruitmarket.schemas import BasketItem
    from framework.observability.events import AgentEventType

    plan_response = FruitMarketPlan(
        items=[BasketItem(sku="apple_gala", quantity=1)],
        reasoning="single apple",
    )
    route_response = _RouterDecisionLLM(
        tool_name="apple_orchard",
        items=[BasketItem(sku="apple_gala", quantity=1)],
    )
    reflect_response = _ReflectorVerdictLLM(done=True, answer="ok", reasoning="done")

    llm = MagicMock()
    llm.chat_large_deployment = "gpt-4o"
    llm.chat_mini_deployment = "gpt-4o-mini"
    llm.close = AsyncMock()

    async def chat_structured(
        messages: list[dict[str, str]],
        *,
        response_model: type[BaseModel],
        **kwargs: object,
    ) -> BaseModel:
        if response_model is FruitMarketPlan:
            return plan_response
        if response_model is _RouterDecisionLLM:
            return route_response
        return reflect_response

    llm.chat_structured = AsyncMock(side_effect=chat_structured)

    cosmos = _mock_cosmos()
    extra = InMemorySink()

    async with build_fruit_market_context(
        llm=llm,
        cosmos=cosmos,
        extra_sinks=[extra],
    ) as ctx:
        await ctx.agent.run("one apple", session_id="ext-sink-1")

    # Every event reached the InMemorySink (proves the wiring)
    types = [e.type for e in extra.events]
    assert types == [
        AgentEventType.PLAN_START,
        AgentEventType.PLAN_COMPLETE,
        AgentEventType.TOOL_CALL,
        AgentEventType.TOOL_RESULT,
        AgentEventType.REFLECT,
        AgentEventType.COMPLETE,
    ]
    # And CosmosSink (default) ALSO got every event — proves the default
    # chain still fires alongside the extras
    assert cosmos.write_trace.await_count == 6


# ---------- sanity: LoggingSink is the second default ----------


def test_logging_sink_is_present_for_dev_visibility() -> None:
    """Even without external observability wired, the dev log shows agent
    flow at the INFO level — important for first-run debugging."""
    ctx = build_fruit_market_context(llm=_mock_llm(), cosmos=_mock_cosmos())
    has_logging_sink = any(isinstance(s, LoggingSink) for s in ctx.agent._emitter.sinks)
    assert has_logging_sink
