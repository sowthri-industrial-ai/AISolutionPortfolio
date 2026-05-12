"""Unit tests for FruitMarketAgent.

Mocks AzureOpenAIClient so tests never touch the network. Two key paths:

* Happy path — single shop call, immediate done.
* Canonical replan — first shop returns out_of_stock, agent loops, second
  shop succeeds, agent terminates with a clean answer.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from demo_fruitmarket.agent import (
    FruitMarketAgent,
    FruitMarketPlan,
    _ReflectorVerdictLLM,
    _RouterDecisionLLM,
)
from demo_fruitmarket.prompts import load_prompt
from demo_fruitmarket.schemas import BasketItem
from demo_fruitmarket.shops import (
    register_all_shops,
)
from framework.agents.base import HistoryEntry
from framework.observability.events import (
    AgentEventEmitter,
    AgentEventType,
    InMemorySink,
)
from framework.tools.base import ToolRegistry

# ---------- helpers ----------


def _mock_llm_with_calls(*responses: Any) -> MagicMock:
    """Build a mocked AzureOpenAIClient that returns ``responses`` in order
    on successive ``chat_structured`` calls."""
    llm = MagicMock()
    llm.chat_large_deployment = "gpt-4o"
    llm.chat_mini_deployment = "gpt-4o-mini"
    llm.chat_structured = AsyncMock(side_effect=list(responses))
    return llm


def _emitter_with_sink() -> tuple[AgentEventEmitter, InMemorySink]:
    sink = InMemorySink()
    return AgentEventEmitter([sink]), sink


def _registry_all_shops() -> ToolRegistry:
    reg = ToolRegistry()
    register_all_shops(reg)
    return reg


# ---------- prompt loader ----------


def test_load_prompt_returns_text_for_each_canonical_name() -> None:
    for name in ("planner", "router", "reflector", "terminator"):
        text = load_prompt(name)
        assert isinstance(text, str)
        assert len(text) > 100, f"{name}.md is suspiciously short"


def test_load_prompt_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown prompt"):
        load_prompt("not-a-real-prompt")


def test_planner_prompt_mentions_schema_fields() -> None:
    text = load_prompt("planner").lower()
    for required in ("items", "budget", "preferences", "reasoning"):
        assert required in text, f"planner.md should mention {required!r}"


def test_router_prompt_mentions_descriptors_and_history() -> None:
    text = load_prompt("router").lower()
    for required in ("remaining_items", "available_shops", "history"):
        assert required in text


def test_reflector_prompt_describes_done_decision() -> None:
    text = load_prompt("reflector").lower()
    assert "done" in text
    assert "fulfilled" in text or "out_of_stock" in text


# ---------- planner output validation ----------


def test_fruit_market_plan_requires_at_least_one_item() -> None:
    with pytest.raises(ValidationError):
        FruitMarketPlan(items=[], reasoning="empty")


def test_fruit_market_plan_optional_budget_and_preferences() -> None:
    p = FruitMarketPlan(
        items=[BasketItem(sku="apple_gala", quantity=1)],
        reasoning="just one apple",
    )
    assert p.budget_usd is None
    assert p.preferences == []


# ---------- happy path: single iteration, all in stock ----------


async def test_happy_path_single_shop_terminates_after_one_iteration() -> None:
    emitter, sink = _emitter_with_sink()
    plan_response = FruitMarketPlan(
        items=[BasketItem(sku="apple_gala", quantity=2)],
        budget_usd=5.0,
        preferences=["fresh"],
        reasoning="User wants two gala apples; apple_orchard is the cheapest source.",
    )
    route_response = _RouterDecisionLLM(
        tool_name="apple_orchard",
        items=[BasketItem(sku="apple_gala", quantity=2)],
        reasoning="apple_orchard stocks gala, cheapest in market",
    )
    reflect_response = _ReflectorVerdictLLM(
        done=True,
        answer="Got 2 gala apples from apple_orchard for $1.60.",
        reasoning="Plan fulfilled in one call.",
    )
    llm = _mock_llm_with_calls(plan_response, route_response, reflect_response)

    agent = FruitMarketAgent(
        emitter=emitter,
        tools=_registry_all_shops(),
        llm=llm,
        max_iterations=3,
    )
    final = await agent.run("Pick up two gala apples", session_id="happy-1")

    types_emitted = [e.type for e in sink.events]
    assert types_emitted == [
        AgentEventType.PLAN_START,
        AgentEventType.PLAN_COMPLETE,
        AgentEventType.TOOL_CALL,
        AgentEventType.TOOL_RESULT,
        AgentEventType.REFLECT,
        AgentEventType.COMPLETE,
    ]
    assert final.get("final_answer") == reflect_response.answer

    # Verify the LLM was called exactly 3 times: plan, route, reflect.
    assert llm.chat_structured.await_count == 3

    # Verify the right deployments were used per role.
    deployments_used = [c.kwargs["deployment"] for c in llm.chat_structured.await_args_list]
    assert deployments_used == ["gpt-4o", "gpt-4o-mini", "gpt-4o-mini"]

    # Verify the tool actually ran against the real apple_orchard shop and
    # the right number of items came back.
    tool_result_event = next(e for e in sink.events if e.type is AgentEventType.TOOL_RESULT)
    purchased = tool_result_event.payload["result"]["purchased"]
    assert len(purchased) == 1
    assert purchased[0]["sku"] == "apple_gala"
    assert purchased[0]["quantity"] == 2


# ---------- canonical replan path ----------


async def test_replan_pineapple_tropical_then_global_imports_terminates_clean() -> None:
    """The flagship demo flow:
    plan (1 pineapple) → router picks tropical_paradise (cheaper) → OOS →
    reflect says continue → router picks global_imports → succeeds → reflect says done.
    """
    emitter, sink = _emitter_with_sink()
    plan_response = FruitMarketPlan(
        items=[BasketItem(sku="pineapple", quantity=1)],
        reasoning="User wants one pineapple; try the affordable tropical shop first.",
    )
    route_attempt_1 = _RouterDecisionLLM(
        tool_name="tropical_paradise",
        items=[BasketItem(sku="pineapple", quantity=1)],
        reasoning="tropical_paradise is cheaper than global_imports for tropical fruits",
    )
    reflect_after_attempt_1 = _ReflectorVerdictLLM(
        done=False,
        answer=None,
        reasoning="pineapple was OOS; global_imports also stocks it.",
    )
    route_attempt_2 = _RouterDecisionLLM(
        tool_name="global_imports",
        items=[BasketItem(sku="pineapple", quantity=1)],
        reasoning="tropical_paradise was OOS; global_imports always has pineapple",
    )
    reflect_after_attempt_2 = _ReflectorVerdictLLM(
        done=True,
        answer=(
            "Got 1 pineapple from global_imports for $8.00. tropical_paradise was out of season."
        ),
        reasoning="Plan fulfilled after one replan.",
    )

    llm = _mock_llm_with_calls(
        plan_response,
        route_attempt_1,
        reflect_after_attempt_1,
        route_attempt_2,
        reflect_after_attempt_2,
    )

    agent = FruitMarketAgent(
        emitter=emitter,
        tools=_registry_all_shops(),
        llm=llm,
        max_iterations=4,
    )
    final = await agent.run("Find me one pineapple", session_id="replan-1")

    # Sequence of event types: plan_start, plan_complete, then 2x (tool_call,
    # tool_result, reflect), then complete = 9 events.
    types_emitted = [e.type for e in sink.events]
    assert types_emitted == [
        AgentEventType.PLAN_START,
        AgentEventType.PLAN_COMPLETE,
        AgentEventType.TOOL_CALL,
        AgentEventType.TOOL_RESULT,
        AgentEventType.REFLECT,
        AgentEventType.TOOL_CALL,
        AgentEventType.TOOL_RESULT,
        AgentEventType.REFLECT,
        AgentEventType.COMPLETE,
    ]

    # Two distinct shops actually called.
    tool_calls = [e for e in sink.events if e.type is AgentEventType.TOOL_CALL]
    assert [tc.node for tc in tool_calls] == ["tropical_paradise", "global_imports"]

    # First tool result has the pineapple in out_of_stock; second has it in purchased.
    tool_results = [e for e in sink.events if e.type is AgentEventType.TOOL_RESULT]
    assert tool_results[0].payload["result"]["out_of_stock"] == ["pineapple"]
    assert tool_results[0].payload["result"]["purchased"] == []
    assert tool_results[1].payload["result"]["out_of_stock"] == []
    assert tool_results[1].payload["result"]["purchased"][0]["sku"] == "pineapple"
    assert tool_results[1].payload["result"]["purchased"][0]["unit_price"] == 8.0

    # Final answer wins from the second reflector verdict.
    assert final.get("final_answer") == reflect_after_attempt_2.answer

    # LLM called 5 times: plan, route1, reflect1, route2, reflect2.
    assert llm.chat_structured.await_count == 5


# ---------- _compute_remaining_items ----------


def test_remaining_items_subtracts_purchased_quantities() -> None:
    plan = FruitMarketPlan(
        items=[
            BasketItem(sku="apple_gala", quantity=5),
            BasketItem(sku="pineapple", quantity=2),
        ],
        reasoning="test",
    )
    history = [
        HistoryEntry(
            tool_name="apple_orchard",
            args={"basket": [{"sku": "apple_gala", "quantity": 5}]},
            result={
                "shop_name": "apple_orchard",
                "purchased": [
                    {"sku": "apple_gala", "quantity": 3, "unit_price": 0.80, "line_total": 2.40},
                ],
                "out_of_stock": [],
                "rationed": [],
                "total_price": 2.40,
                "notes": "",
            },
        ),
    ]
    remaining = FruitMarketAgent._compute_remaining_items(plan, history)
    skus = {item.sku: item.quantity for item in remaining}
    assert skus == {"apple_gala": 2, "pineapple": 2}


def test_remaining_items_drops_fully_satisfied_skus() -> None:
    plan = FruitMarketPlan(
        items=[BasketItem(sku="apple_gala", quantity=2)],
        reasoning="test",
    )
    history = [
        HistoryEntry(
            tool_name="apple_orchard",
            args={"basket": [{"sku": "apple_gala", "quantity": 2}]},
            result={
                "shop_name": "apple_orchard",
                "purchased": [
                    {"sku": "apple_gala", "quantity": 2, "unit_price": 0.80, "line_total": 1.60},
                ],
                "out_of_stock": [],
                "rationed": [],
                "total_price": 1.60,
                "notes": "",
            },
        ),
    ]
    remaining = FruitMarketAgent._compute_remaining_items(plan, history)
    assert remaining == []


# ---------- type guard on _route ----------


async def test_route_rejects_non_FruitMarketPlan() -> None:
    """If something other than FruitMarketPlan reaches _route, that's a bug
    in graph wiring — surface it loudly."""
    emitter, _ = _emitter_with_sink()
    llm = _mock_llm_with_calls()  # never called
    agent = FruitMarketAgent(
        emitter=emitter,
        tools=_registry_all_shops(),
        llm=llm,
    )
    with pytest.raises(TypeError, match="FruitMarketPlan"):
        await agent._route(plan={"not": "a plan"}, history=[])


# ---------- prompt overrides for tests ----------


async def test_prompt_overrides_passthrough_to_llm() -> None:
    """Prompt-override constructor args reach the LLM as system messages."""
    emitter, _ = _emitter_with_sink()
    plan_response = FruitMarketPlan(
        items=[BasketItem(sku="apple_gala", quantity=1)],
        reasoning="test",
    )
    route_response = _RouterDecisionLLM(
        tool_name="apple_orchard",
        items=[BasketItem(sku="apple_gala", quantity=1)],
    )
    reflect_response = _ReflectorVerdictLLM(done=True, answer="done", reasoning="done")
    llm = _mock_llm_with_calls(plan_response, route_response, reflect_response)

    agent = FruitMarketAgent(
        emitter=emitter,
        tools=_registry_all_shops(),
        llm=llm,
        planner_prompt="CUSTOM_PLANNER",
        router_prompt="CUSTOM_ROUTER",
        reflector_prompt="CUSTOM_REFLECTOR",
        terminator_prompt="CUSTOM_TERMINATOR",
    )
    await agent.run("just one apple", session_id="prompt-test")

    # _plan: messages[0]['content'] should be CUSTOM_PLANNER
    plan_call = llm.chat_structured.await_args_list[0]
    assert plan_call.kwargs["messages"][0]["content"] == "CUSTOM_PLANNER"

    # _route: CUSTOM_ROUTER
    route_call = llm.chat_structured.await_args_list[1]
    assert route_call.kwargs["messages"][0]["content"] == "CUSTOM_ROUTER"

    # _reflect: concatenated reflector + terminator
    reflect_call = llm.chat_structured.await_args_list[2]
    full_system = reflect_call.kwargs["messages"][0]["content"]
    assert "CUSTOM_REFLECTOR" in full_system
    assert "CUSTOM_TERMINATOR" in full_system
