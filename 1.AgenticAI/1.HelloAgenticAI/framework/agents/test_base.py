"""Unit tests for AgentBase — verifies the canonical loop emits the
six AgentEventTypes in the right order, supports replanning iterations,
caps at max_iterations, and threads tool input/output schemas correctly.

Tests use a deterministic in-process tool and a deterministic AgentBase
subclass — no LLM, no Cosmos. The integration suite exercises the live
AOAI + Cosmos path with all 6 event types.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from framework.agents.base import (
    AgentBase,
    HistoryEntry,
    ReflectionDecision,
    ToolDecision,
)
from framework.observability.events import (
    AgentEventEmitter,
    AgentEventType,
    InMemorySink,
)
from framework.tools.base import MCPToolBase, ToolRegistry

# ---------- shared fixtures ----------


class _EchoIn(BaseModel):
    text: str


class _EchoOut(BaseModel):
    echoed: str


class _EchoTool(MCPToolBase[_EchoIn, _EchoOut]):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes the supplied text."

    @property
    def input_schema(self) -> type[_EchoIn]:
        return _EchoIn

    @property
    def output_schema(self) -> type[_EchoOut]:
        return _EchoOut

    async def call(self, payload: _EchoIn) -> _EchoOut:
        return _EchoOut(echoed=payload.text.upper())


def _make_emitter_with_sink() -> tuple[AgentEventEmitter, InMemorySink]:
    sink = InMemorySink()
    return AgentEventEmitter([sink]), sink


def _make_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    return reg


class _OneShotAgent(AgentBase):
    """Single-iteration agent — terminates after one tool call.

    _plan returns a fixed plan; _route always picks `echo`; _reflect
    always returns done=True with answer=last result's echoed text.
    """

    async def _plan(self, goal: str) -> dict[str, Any]:
        return {"goal": goal, "steps": ["echo it"]}

    async def _route(self, plan: Any, history: list[HistoryEntry]) -> ToolDecision:
        return ToolDecision(
            tool_name="echo",
            args={"text": plan["goal"]},
            reasoning="echo to fulfil the plan",
        )

    async def _reflect(self, history: list[HistoryEntry]) -> ReflectionDecision:
        last = history[-1]
        return ReflectionDecision(
            done=True,
            reasoning="goal echoed",
            answer=str(last.result["echoed"]),
        )


class _TwoShotAgent(_OneShotAgent):
    """Two-iteration agent — first reflect says continue, second says done."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._reflect_count = 0

    async def _reflect(self, history: list[HistoryEntry]) -> ReflectionDecision:
        self._reflect_count += 1
        if self._reflect_count == 1:
            return ReflectionDecision(
                done=False,
                reasoning="want one more echo",
            )
        return ReflectionDecision(
            done=True,
            reasoning="enough",
            answer=str(history[-1].result["echoed"]),
        )


class _NeverDoneAgent(_OneShotAgent):
    """Always says continue — exercises the max_iterations cap."""

    async def _reflect(self, history: list[HistoryEntry]) -> ReflectionDecision:
        return ReflectionDecision(done=False, reasoning="never satisfied")


# ---------- happy path: single iteration ----------


async def test_run_emits_all_six_event_types_in_order() -> None:
    emitter, sink = _make_emitter_with_sink()
    agent = _OneShotAgent(emitter=emitter, tools=_make_registry())
    final = await agent.run("hello", session_id="s1")
    types = [e.type for e in sink.events]
    assert types == [
        AgentEventType.PLAN_START,
        AgentEventType.PLAN_COMPLETE,
        AgentEventType.TOOL_CALL,
        AgentEventType.TOOL_RESULT,
        AgentEventType.REFLECT,
        AgentEventType.COMPLETE,
    ]
    assert final.get("final_answer") == "HELLO"


async def test_every_event_carries_session_id() -> None:
    emitter, sink = _make_emitter_with_sink()
    agent = _OneShotAgent(emitter=emitter, tools=_make_registry())
    await agent.run("hi", session_id="my-sid")
    assert all(e.session_id == "my-sid" for e in sink.events)


async def test_run_uses_uuid_session_id_when_omitted() -> None:
    emitter, sink = _make_emitter_with_sink()
    agent = _OneShotAgent(emitter=emitter, tools=_make_registry())
    await agent.run("hi")
    assert len(sink.events) == 6
    sid = sink.events[0].session_id
    assert len(sid) > 0
    assert all(e.session_id == sid for e in sink.events)


# ---------- payload contents ----------


async def test_plan_complete_payload_carries_plan() -> None:
    emitter, sink = _make_emitter_with_sink()
    agent = _OneShotAgent(emitter=emitter, tools=_make_registry())
    await agent.run("buy fruit", session_id="s1")
    plan_complete = next(e for e in sink.events if e.type is AgentEventType.PLAN_COMPLETE)
    assert plan_complete.payload["plan"]["goal"] == "buy fruit"


async def test_tool_call_payload_has_args_and_node() -> None:
    emitter, sink = _make_emitter_with_sink()
    agent = _OneShotAgent(emitter=emitter, tools=_make_registry())
    await agent.run("hello", session_id="s1")
    tc = next(e for e in sink.events if e.type is AgentEventType.TOOL_CALL)
    assert tc.node == "echo"
    assert tc.payload["args"] == {"text": "hello"}


async def test_tool_result_payload_carries_result_dict() -> None:
    emitter, sink = _make_emitter_with_sink()
    agent = _OneShotAgent(emitter=emitter, tools=_make_registry())
    await agent.run("hello", session_id="s1")
    tr = next(e for e in sink.events if e.type is AgentEventType.TOOL_RESULT)
    assert tr.node == "echo"
    assert tr.payload["result"] == {"echoed": "HELLO"}


async def test_reflect_payload_records_decision_fields() -> None:
    emitter, sink = _make_emitter_with_sink()
    agent = _OneShotAgent(emitter=emitter, tools=_make_registry())
    await agent.run("hello", session_id="s1")
    refl = next(e for e in sink.events if e.type is AgentEventType.REFLECT)
    assert refl.payload["done"] is True
    assert refl.payload["answer"] == "HELLO"


async def test_complete_payload_has_final_answer_and_iteration_count() -> None:
    emitter, sink = _make_emitter_with_sink()
    agent = _OneShotAgent(emitter=emitter, tools=_make_registry())
    await agent.run("hello", session_id="s1")
    done = next(e for e in sink.events if e.type is AgentEventType.COMPLETE)
    assert done.payload["final_answer"] == "HELLO"
    assert done.payload["iterations"] == 1


# ---------- looping ----------


async def test_two_iteration_run_emits_extra_tool_and_reflect_events() -> None:
    emitter, sink = _make_emitter_with_sink()
    agent = _TwoShotAgent(emitter=emitter, tools=_make_registry())
    await agent.run("hello", session_id="s1")
    types = [e.type for e in sink.events]
    # plan_start, plan_complete, then 2 x (tool_call, tool_result, reflect),
    # then complete = 9 events
    assert types == [
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


async def test_max_iterations_cap_terminates_run() -> None:
    emitter, sink = _make_emitter_with_sink()
    agent = _NeverDoneAgent(
        emitter=emitter,
        tools=_make_registry(),
        max_iterations=2,
    )
    await agent.run("hello", session_id="s1")
    # should terminate after 2 iterations even though _reflect always says continue
    tool_calls = [e for e in sink.events if e.type is AgentEventType.TOOL_CALL]
    assert len(tool_calls) == 2
    done = next(e for e in sink.events if e.type is AgentEventType.COMPLETE)
    assert done.payload["iterations"] == 2


# ---------- timing + duration ----------


async def test_duration_ms_is_recorded_for_timed_steps() -> None:
    emitter, sink = _make_emitter_with_sink()
    agent = _OneShotAgent(emitter=emitter, tools=_make_registry())
    await agent.run("hi", session_id="s1")
    timed_types = {
        AgentEventType.PLAN_COMPLETE,
        AgentEventType.TOOL_RESULT,
        AgentEventType.REFLECT,
    }
    for e in sink.events:
        if e.type in timed_types:
            assert e.duration_ms is not None
            assert e.duration_ms >= 0


# ---------- abstract base enforcement ----------


def test_cannot_instantiate_agent_base_directly() -> None:
    emitter, _ = _make_emitter_with_sink()
    with pytest.raises(TypeError):
        AgentBase(emitter=emitter, tools=_make_registry())  # type: ignore[abstract]
