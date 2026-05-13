""":class:`FruitMarketAgent` — a concrete :class:`AgentBase` subclass for the demo.

The framework's :class:`AgentBase` owns the LangGraph loop and the six
canonical event types. This subclass provides the vertical-specific
``_plan`` / ``_route`` / ``_reflect`` implementations: all three call
Azure OpenAI via :class:`AzureOpenAIClient.chat_structured` with the
prompts loaded from ``demo_fruitmarket/prompts/*.md``.

Models:

* Planner uses :attr:`AzureOpenAIClient.chat_large_deployment` (gpt-4o)
  for stronger goal decomposition.
* Router and reflector use :attr:`chat_mini_deployment` (gpt-4o-mini)
  for cost — they do narrower, more bounded reasoning.

Framework limitation worked around here:
:class:`AgentBase._reflect` receives only ``history``, not the original
goal or plan. The reflector wants both for the verdict + final answer.
We stash them on instance state in ``_plan`` and read them in ``_reflect``.
**This is not safe for concurrent runs of the same agent instance** —
the Chainlit app creates a new agent per chat session, so this is fine
in practice. A future framework refactor (Phase 4 or beyond) should pass
``state["goal"]`` / ``state["plan"]`` to ``_reflect`` directly.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from demo_fruitmarket.prompts import load_prompt
from demo_fruitmarket.schemas import BasketItem
from framework.agents.base import (
    AgentBase,
    HistoryEntry,
    ReflectionDecision,
    ToolDecision,
)
from framework.guardrails.content_safety import ContentSafetyClient
from framework.llm.azure_openai import AzureOpenAIClient
from framework.observability.events import AgentEventEmitter
from framework.tools.base import ToolRegistry

# ---------- planner output ----------


class FruitMarketPlan(BaseModel):
    """Structured output of the planner — what we're trying to buy."""

    items: list[BasketItem] = Field(
        min_length=1,
        description="Specific fruits + quantities to acquire.",
    )
    budget_usd: float | None = Field(
        default=None,
        ge=0,
        description="Optional dollar budget pulled from the goal.",
    )
    preferences: list[str] = Field(
        default_factory=list,
        description="Tags like 'organic', 'local', 'tropical', 'breakfast'.",
    )
    reasoning: str = Field(
        min_length=1,
        description="One sentence explaining the plan to the user.",
    )


# ---------- internal LLM I/O ----------


class _RouterDecisionLLM(BaseModel):
    """What we ask the router LLM to return."""

    tool_name: str = Field(min_length=1)
    items: list[BasketItem] = Field(min_length=0)
    reasoning: str = Field(default="")


class _ReflectorVerdictLLM(BaseModel):
    """What we ask the reflector LLM to return."""

    done: bool
    answer: str | None = None
    reasoning: str = ""


# ---------- the agent ----------


class FruitMarketAgent(AgentBase):
    """Demo-fruitmarket vertical of :class:`AgentBase`.

    Constructor takes the same emitter / tools / max_iterations as the base
    plus the LLM client. Optional prompt overrides for tests; production
    loads from ``demo_fruitmarket/prompts/*.md`` automatically.
    """

    def __init__(
        self,
        *,
        emitter: AgentEventEmitter,
        tools: ToolRegistry,
        llm: AzureOpenAIClient,
        max_iterations: int = 4,
        content_safety: ContentSafetyClient | None = None,
        planner_prompt: str | None = None,
        router_prompt: str | None = None,
        reflector_prompt: str | None = None,
        terminator_prompt: str | None = None,
    ) -> None:
        super().__init__(
            emitter=emitter,
            tools=tools,
            max_iterations=max_iterations,
            content_safety=content_safety,
        )
        self._llm = llm
        self._planner_prompt = planner_prompt or load_prompt("planner")
        self._router_prompt = router_prompt or load_prompt("router")
        self._reflector_prompt = reflector_prompt or load_prompt("reflector")
        self._terminator_prompt = terminator_prompt or load_prompt("terminator")
        # Stashed in _plan, read in _reflect — see module docstring.
        self._current_goal: str | None = None
        self._current_plan: FruitMarketPlan | None = None

    # ----- subclass contract -----

    async def _plan(self, goal: str) -> FruitMarketPlan:
        plan = await self._llm.chat_structured(
            messages=[
                {"role": "system", "content": self._planner_prompt},
                {"role": "user", "content": goal},
            ],
            response_model=FruitMarketPlan,
            deployment=self._llm.chat_large_deployment,
        )
        self._current_goal = goal
        self._current_plan = plan
        return plan

    async def _route(
        self,
        plan: Any,
        history: list[HistoryEntry],
    ) -> ToolDecision:
        if not isinstance(plan, FruitMarketPlan):
            raise TypeError(
                f"FruitMarketAgent._route expected a FruitMarketPlan; got {type(plan).__name__}"
            )
        remaining = self._compute_remaining_items(plan, history)
        descriptors = self._tools.descriptors()
        history_summary = self._summarize_history_for_router(history)

        context = {
            "remaining_items": [item.model_dump() for item in remaining],
            "available_shops": descriptors,
            "history_summary": history_summary,
        }

        decision = await self._llm.chat_structured(
            messages=[
                {"role": "system", "content": self._router_prompt},
                {"role": "user", "content": json.dumps(context, indent=2)},
            ],
            response_model=_RouterDecisionLLM,
            deployment=self._llm.chat_mini_deployment,
        )

        return ToolDecision(
            tool_name=decision.tool_name,
            args={"basket": [item.model_dump() for item in decision.items]},
            reasoning=decision.reasoning,
        )

    async def _reflect(
        self,
        history: list[HistoryEntry],
    ) -> ReflectionDecision:
        # Stashed in _plan; framework doesn't pass goal/plan to _reflect today.
        goal = self._current_goal or ""
        plan = self._current_plan

        context = {
            "goal": goal,
            "plan": plan.model_dump() if plan is not None else None,
            "history": [h.model_dump() for h in history],
        }

        # Reflector + terminator prompts concatenated — single LLM call.
        full_prompt = (
            f"{self._reflector_prompt}\n\n"
            "# Final answer style (when done=True):\n"
            f"{self._terminator_prompt}"
        )

        verdict = await self._llm.chat_structured(
            messages=[
                {"role": "system", "content": full_prompt},
                {"role": "user", "content": json.dumps(context, indent=2)},
            ],
            response_model=_ReflectorVerdictLLM,
            deployment=self._llm.chat_mini_deployment,
        )

        return ReflectionDecision(
            done=verdict.done,
            answer=verdict.answer,
            reasoning=verdict.reasoning,
        )

    # ----- internals -----

    @staticmethod
    def _compute_remaining_items(
        plan: FruitMarketPlan,
        history: list[HistoryEntry],
    ) -> list[BasketItem]:
        """Subtract purchased quantities from planned quantities."""
        remaining: dict[str, int] = {item.sku: item.quantity for item in plan.items}
        for h in history:
            purchased = h.result.get("purchased", []) if isinstance(h.result, dict) else []
            for line in purchased:
                if not isinstance(line, dict):
                    continue
                sku = line.get("sku")
                qty = line.get("quantity", 0)
                if isinstance(sku, str) and sku in remaining:
                    remaining[sku] = max(0, remaining[sku] - int(qty))
        return [BasketItem(sku=sku, quantity=qty) for sku, qty in remaining.items() if qty > 0]

    @staticmethod
    def _summarize_history_for_router(
        history: list[HistoryEntry],
    ) -> list[dict[str, Any]]:
        """A compact view of past shop calls for the router prompt."""
        return [
            {
                "tool_name": h.tool_name,
                "args": h.args,
                "result": h.result,
            }
            for h in history
        ]
