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

import pytest

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


# ---------- Phase 4: optional content_safety + AppInsightsSink + LangfuseSink ----------


def test_factory_without_phase4_components_matches_phase_3_chain() -> None:
    """No content_safety / app_insights_sink / langfuse_sink supplied →
    the sink chain is exactly the Phase 3 chain (CosmosSink, LoggingSink).
    Backward compatibility for every existing test."""
    ctx = build_fruit_market_context(llm=_mock_llm(), cosmos=_mock_cosmos())
    sink_types = [type(s).__name__ for s in ctx.agent._emitter.sinks]
    assert sink_types == ["CosmosSink", "LoggingSink"]
    assert ctx.content_safety is None
    assert ctx.agent._content_safety is None


def test_factory_with_content_safety_passes_it_to_agent() -> None:
    from framework.guardrails.content_safety import ContentSafetyClient

    cs = ContentSafetyClient(endpoint="https://cs.example/")
    ctx = build_fruit_market_context(
        llm=_mock_llm(),
        cosmos=_mock_cosmos(),
        content_safety=cs,
    )
    assert ctx.content_safety is cs
    assert ctx.agent._content_safety is cs


def test_factory_with_app_insights_sink_appended_after_logging() -> None:
    from framework.observability.app_insights import AppInsightsSink

    ai = AppInsightsSink(connection_string=None)  # degraded mode, no real init
    ctx = build_fruit_market_context(
        llm=_mock_llm(),
        cosmos=_mock_cosmos(),
        app_insights_sink=ai,
    )
    sink_types = [type(s).__name__ for s in ctx.agent._emitter.sinks]
    # AppInsightsSink slots between LoggingSink and extra_sinks
    assert sink_types == ["CosmosSink", "LoggingSink", "AppInsightsSink"]
    assert ctx.agent._emitter.sinks[2] is ai


def test_factory_with_langfuse_sink_appended_after_app_insights() -> None:
    from framework.observability.app_insights import AppInsightsSink
    from framework.observability.langfuse import LangfuseSink

    ai = AppInsightsSink(connection_string=None)
    lf = LangfuseSink(key_vault_endpoint=None)
    ctx = build_fruit_market_context(
        llm=_mock_llm(),
        cosmos=_mock_cosmos(),
        app_insights_sink=ai,
        langfuse_sink=lf,
    )
    sink_types = [type(s).__name__ for s in ctx.agent._emitter.sinks]
    # Order: Cosmos (persistence) → Logging (dev) → AppInsights (queryable)
    # → Langfuse (trace UI) → extras (UI sink). Stable contract.
    assert sink_types == ["CosmosSink", "LoggingSink", "AppInsightsSink", "LangfuseSink"]


def test_factory_with_only_langfuse_skips_app_insights_slot() -> None:
    """A vertical project might wire Langfuse but not App Insights (or
    vice versa). The chain just skips the missing slot."""
    from framework.observability.langfuse import LangfuseSink

    lf = LangfuseSink(key_vault_endpoint=None)
    ctx = build_fruit_market_context(
        llm=_mock_llm(),
        cosmos=_mock_cosmos(),
        langfuse_sink=lf,
    )
    sink_types = [type(s).__name__ for s in ctx.agent._emitter.sinks]
    assert sink_types == ["CosmosSink", "LoggingSink", "LangfuseSink"]


def test_factory_extra_sinks_come_last_after_phase4_sinks() -> None:
    from framework.observability.app_insights import AppInsightsSink
    from framework.observability.langfuse import LangfuseSink

    ai = AppInsightsSink(connection_string=None)
    lf = LangfuseSink(key_vault_endpoint=None)
    extra = InMemorySink()
    ctx = build_fruit_market_context(
        llm=_mock_llm(),
        cosmos=_mock_cosmos(),
        app_insights_sink=ai,
        langfuse_sink=lf,
        extra_sinks=[extra],
    )
    sink_types = [type(s).__name__ for s in ctx.agent._emitter.sinks]
    assert sink_types == [
        "CosmosSink",
        "LoggingSink",
        "AppInsightsSink",
        "LangfuseSink",
        "InMemorySink",
    ]


# ---------- env-driven production factory ----------


def test_from_endpoints_reads_phase4_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_fruit_market_context_from_endpoints constructs the optional
    Phase 4 components from env vars. Test it without spinning up real
    AOAI / Cosmos / KV clients — we just check the wiring decisions."""
    from demo_fruitmarket.graph import build_fruit_market_context_from_endpoints

    # Stub the LLM and Cosmos factories so we don't try to hit Azure.
    fake_llm = _mock_llm()
    fake_cosmos = _mock_cosmos()
    monkeypatch.setattr(
        "framework.llm.azure_openai.AzureOpenAIClient.from_endpoint",
        classmethod(lambda cls, **kw: fake_llm),
    )
    monkeypatch.setattr(
        "framework.memory.cosmos.CosmosProvider.from_endpoint",
        classmethod(lambda cls, **kw: fake_cosmos),
    )

    monkeypatch.setenv("AZURE_CONTENT_SAFETY_ENDPOINT", "https://cs.example/")
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=fake;...")
    monkeypatch.setenv("AZURE_KEY_VAULT_ENDPOINT", "https://kv.example.vault.azure.net/")

    ctx = build_fruit_market_context_from_endpoints(
        aoai_endpoint="https://aoai.example/",
        cosmos_endpoint="https://cosmos.example/",
    )
    sink_types = [type(s).__name__ for s in ctx.agent._emitter.sinks]
    assert sink_types == ["CosmosSink", "LoggingSink", "AppInsightsSink", "LangfuseSink"]
    assert ctx.content_safety is not None
    assert ctx.content_safety.endpoint == "https://cs.example/"


def test_from_endpoints_absent_env_vars_match_phase_3_behaviour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With none of the Phase 4 env vars set, the factory returns the
    Phase 3 chain unchanged. The deployed Phase 3 demo at revision
    --0000003 is exactly this state."""
    from demo_fruitmarket.graph import build_fruit_market_context_from_endpoints

    fake_llm = _mock_llm()
    fake_cosmos = _mock_cosmos()
    monkeypatch.setattr(
        "framework.llm.azure_openai.AzureOpenAIClient.from_endpoint",
        classmethod(lambda cls, **kw: fake_llm),
    )
    monkeypatch.setattr(
        "framework.memory.cosmos.CosmosProvider.from_endpoint",
        classmethod(lambda cls, **kw: fake_cosmos),
    )
    monkeypatch.delenv("AZURE_CONTENT_SAFETY_ENDPOINT", raising=False)
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_KEY_VAULT_ENDPOINT", raising=False)

    ctx = build_fruit_market_context_from_endpoints(
        aoai_endpoint="https://aoai.example/",
        cosmos_endpoint="https://cosmos.example/",
    )
    sink_types = [type(s).__name__ for s in ctx.agent._emitter.sinks]
    assert sink_types == ["CosmosSink", "LoggingSink"]
    assert ctx.content_safety is None


# ---------- aclose covers Phase 4 owned resources ----------


async def test_aclose_closes_content_safety_when_present() -> None:
    from framework.guardrails.content_safety import ContentSafetyClient

    cs = ContentSafetyClient(endpoint="https://cs.example/")
    cs.close = AsyncMock()  # type: ignore[method-assign]
    llm, cosmos = _mock_llm(), _mock_cosmos()
    ctx = build_fruit_market_context(llm=llm, cosmos=cosmos, content_safety=cs)
    await ctx.aclose()
    cs.close.assert_awaited_once()


async def test_aclose_closes_owned_sinks() -> None:
    from framework.observability.app_insights import AppInsightsSink
    from framework.observability.langfuse import LangfuseSink

    ai = AppInsightsSink(connection_string=None)
    lf = LangfuseSink(key_vault_endpoint=None)
    # LangfuseSink has an async close; AppInsightsSink doesn't define one.
    # aclose should handle both gracefully.
    lf.close = AsyncMock()  # type: ignore[method-assign]
    llm, cosmos = _mock_llm(), _mock_cosmos()
    ctx = build_fruit_market_context(
        llm=llm,
        cosmos=cosmos,
        app_insights_sink=ai,
        langfuse_sink=lf,
    )
    await ctx.aclose()
    lf.close.assert_awaited_once()


async def test_aclose_continues_when_one_closer_raises() -> None:
    """A failing close on one resource must not skip closes on the others.
    Observability flush errors at shutdown shouldn't leak Cosmos / LLM
    handles."""
    llm, cosmos = _mock_llm(), _mock_cosmos()
    llm.close = AsyncMock(side_effect=RuntimeError("simulated LLM close failure"))
    ctx = build_fruit_market_context(llm=llm, cosmos=cosmos)
    # Should not raise
    await ctx.aclose()
    # cosmos still closed despite LLM failure
    cosmos.close.assert_awaited_once()
