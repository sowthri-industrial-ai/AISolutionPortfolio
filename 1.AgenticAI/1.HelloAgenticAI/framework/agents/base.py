"""Agent runtime — :class:`AgentBase` (LangGraph) + :class:`AgentState`.

The framework's central composition. Per ARCHITECTURE.md §4 the canonical
loop is **plan → tool → reflect → (loop or terminate)**. AgentBase wires
that loop as a LangGraph ``StateGraph``; subclasses provide the concrete
``_plan``, ``_route`` and ``_reflect`` implementations (typically calling
the AOAI client with vertical-specific prompts).

Event emission is automatic — every node emits the corresponding
:class:`AgentEventType`. Phase 2 covers the six canonical types
(``PLAN_START`` ``PLAN_COMPLETE`` ``TOOL_CALL`` ``TOOL_RESULT`` ``REFLECT``
``COMPLETE``); Phase 4 will add ``GUARDRAIL_BLOCK`` /
``SCHEMA_VALIDATION_FAILURE`` / ``ROUTE`` etc. as those guardrails wire in.

Subclass contract (concrete vertical implementations, e.g. MinimalAgent
for the integration test, fruit-market planner for Phase 3):

* ``_plan(goal)`` → opaque plan object (typically a Pydantic model)
* ``_route(plan, history)`` → :class:`ToolDecision` saying which tool +
  what args
* ``_reflect(history)`` → :class:`ReflectionDecision` saying whether to
  loop again or terminate, and (when terminating) the final answer

The base class never reads the contents of plan / tool args / tool result
— it just routes them through the graph and emits them as event payloads.
"""

from __future__ import annotations

import logging
import operator
import time
from abc import ABC, abstractmethod
from typing import Annotated, Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from framework.observability.events import (
    AgentEvent,
    AgentEventEmitter,
    AgentEventType,
)
from framework.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


# ---------- shared contract types ----------


class ToolDecision(BaseModel):
    """The router's choice for the next tool call."""

    tool_name: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    reasoning: str | None = None


class ReflectionDecision(BaseModel):
    """The reflector's verdict on the latest result."""

    done: bool
    reasoning: str = ""
    answer: str | None = None  # populated when done=True


class HistoryEntry(BaseModel):
    """One (tool call, tool result) pair appended after each tool node."""

    tool_name: str
    args: dict[str, Any]
    result: dict[str, Any]


# ---------- LangGraph state ----------


class AgentState(TypedDict, total=False):
    """LangGraph state for an agent run.

    Required: ``session_id``, ``goal``, ``history``, ``iteration``,
    ``complete``. Optional: ``plan``, ``tool_call``, ``tool_result``,
    ``reflection``, ``final_answer``.

    ``history`` uses ``operator.add`` reducer so each tool node's
    ``{"history": [entry]}`` accumulates rather than overwrites.
    """

    session_id: str
    goal: str
    plan: Any
    tool_call: dict[str, Any]
    tool_result: dict[str, Any]
    reflection: dict[str, Any]
    history: Annotated[list[dict[str, Any]], operator.add]
    iteration: int
    complete: bool
    final_answer: str


# ---------- AgentBase ----------


class AgentBase(ABC):
    """Abstract agent — composes the canonical loop and emits events.

    Subclasses implement ``_plan`` / ``_route`` / ``_reflect``. The base
    class owns the graph, event emission, tool invocation, iteration
    capping, and termination.
    """

    def __init__(
        self,
        *,
        emitter: AgentEventEmitter,
        tools: ToolRegistry,
        max_iterations: int = 3,
    ) -> None:
        self._emitter = emitter
        self._tools = tools
        self._max_iterations = max_iterations
        self._graph = self._build_graph()

    # ----- subclass contract -----

    @abstractmethod
    async def _plan(self, goal: str) -> Any:
        """Decompose ``goal`` into a plan. Return any pickleable shape."""

    @abstractmethod
    async def _route(
        self,
        plan: Any,
        history: list[HistoryEntry],
    ) -> ToolDecision:
        """Pick the next tool + args given the plan and history so far."""

    @abstractmethod
    async def _reflect(
        self,
        history: list[HistoryEntry],
    ) -> ReflectionDecision:
        """Decide whether the run is done, and (when done) the final answer."""

    # ----- graph construction -----

    def _build_graph(self) -> Any:
        g: StateGraph[AgentState, Any, AgentState, AgentState] = StateGraph(AgentState)
        g.add_node("plan", self._plan_node)
        g.add_node("tool", self._tool_node)
        g.add_node("reflect", self._reflect_node)
        g.add_node("terminate", self._terminate_node)
        g.set_entry_point("plan")
        g.add_edge("plan", "tool")
        g.add_edge("tool", "reflect")
        g.add_conditional_edges(
            "reflect",
            self._should_continue,
            {"continue": "tool", "done": "terminate"},
        )
        g.add_edge("terminate", END)
        return g.compile()

    # ----- public entrypoint -----

    async def run(
        self,
        goal: str,
        *,
        session_id: str | None = None,
    ) -> AgentState:
        """Run the agent against ``goal`` and return the final state."""
        sid = session_id or str(uuid4())
        initial: AgentState = {
            "session_id": sid,
            "goal": goal,
            "history": [],
            "iteration": 0,
            "complete": False,
        }
        return await self._graph.ainvoke(initial)  # type: ignore[no-any-return]

    # ----- node implementations -----

    async def _plan_node(self, state: AgentState) -> dict[str, Any]:
        sid = state["session_id"]
        goal = state["goal"]
        await self._emit(sid, AgentEventType.PLAN_START, payload={"goal": goal})
        started = time.monotonic()
        plan = await self._plan(goal)
        duration_ms = int((time.monotonic() - started) * 1000)
        await self._emit(
            sid,
            AgentEventType.PLAN_COMPLETE,
            duration_ms=duration_ms,
            payload={"plan": _to_payload(plan)},
        )
        return {"plan": plan}

    async def _tool_node(self, state: AgentState) -> dict[str, Any]:
        sid = state["session_id"]
        history = _coerce_history(state.get("history", []))
        decision = await self._route(state.get("plan"), history)
        tool = self._tools.get(decision.tool_name)
        await self._emit(
            sid,
            AgentEventType.TOOL_CALL,
            node=decision.tool_name,
            payload={
                "args": decision.args,
                "reasoning": decision.reasoning,
            },
        )
        started = time.monotonic()
        payload = tool.input_schema.model_validate(decision.args)
        result = await tool.call(payload)
        duration_ms = int((time.monotonic() - started) * 1000)
        result_payload = (
            result.model_dump() if isinstance(result, BaseModel) else _to_payload(result)
        )
        await self._emit(
            sid,
            AgentEventType.TOOL_RESULT,
            node=decision.tool_name,
            duration_ms=duration_ms,
            payload={"result": result_payload},
        )
        entry = HistoryEntry(
            tool_name=decision.tool_name,
            args=decision.args,
            result=result_payload,
        )
        return {
            "tool_call": {
                "tool_name": decision.tool_name,
                "args": decision.args,
            },
            "tool_result": result_payload,
            "history": [entry.model_dump()],
        }

    async def _reflect_node(self, state: AgentState) -> dict[str, Any]:
        sid = state["session_id"]
        history = _coerce_history(state.get("history", []))
        started = time.monotonic()
        decision = await self._reflect(history)
        duration_ms = int((time.monotonic() - started) * 1000)
        await self._emit(
            sid,
            AgentEventType.REFLECT,
            duration_ms=duration_ms,
            payload={
                "done": decision.done,
                "reasoning": decision.reasoning,
                "answer": decision.answer,
            },
        )
        next_iteration = state.get("iteration", 0) + 1
        complete = decision.done or next_iteration >= self._max_iterations
        update: dict[str, Any] = {
            "reflection": decision.model_dump(),
            "iteration": next_iteration,
            "complete": complete,
        }
        if complete and decision.answer is not None:
            update["final_answer"] = decision.answer
        return update

    def _should_continue(self, state: AgentState) -> str:
        return "done" if state.get("complete", False) else "continue"

    async def _terminate_node(self, state: AgentState) -> dict[str, Any]:
        sid = state["session_id"]
        final_answer = state.get("final_answer") or _fallback_answer(state)
        await self._emit(
            sid,
            AgentEventType.COMPLETE,
            payload={
                "final_answer": final_answer,
                "iterations": state.get("iteration", 0),
            },
        )
        return {"final_answer": final_answer}

    # ----- helpers -----

    async def _emit(
        self,
        session_id: str,
        type_: AgentEventType,
        *,
        node: str | None = None,
        duration_ms: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        await self._emitter.emit(
            AgentEvent(
                session_id=session_id,
                type=type_,
                node=node,
                duration_ms=duration_ms,
                payload=payload or {},
            )
        )


# ---------- module-level helpers ----------


def _coerce_history(raw: list[dict[str, Any]]) -> list[HistoryEntry]:
    """Re-hydrate the history list back into Pydantic models for subclasses."""
    return [HistoryEntry.model_validate(entry) for entry in raw]


def _to_payload(value: Any) -> Any:
    """Best-effort JSON-serializable form for an arbitrary state value."""
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _to_payload(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_payload(v) for v in value]
    if isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _fallback_answer(state: AgentState) -> str:
    """Used when the reflector terminated without giving an explicit answer."""
    history = state.get("history", [])
    if not history:
        return "Task completed (no tool calls made)."
    last = history[-1]
    return f"Task completed after {len(history)} tool call(s); last result: {last.get('result')}"
