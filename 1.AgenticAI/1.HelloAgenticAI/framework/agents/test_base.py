"""Unit tests for AgentBase — verifies the canonical loop emits the
six AgentEventTypes in the right order, supports replanning iterations,
caps at max_iterations, and threads tool input/output schemas correctly.

Phase 4 additions exercise the schema-validation retry/emit helper:
``SCHEMA_VALIDATION_FAILED`` events on each retry attempt, exception
propagation after the budget exhausts, and tool-input-validation
failures routed through the same gate.

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
from framework.guardrails.schema import SchemaValidationError
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


# ---------- Phase 4: schema-validation retry + SCHEMA_VALIDATION_FAILED ----------


class _PlanModel(BaseModel):
    """Stand-in Pydantic model — exists only to carry a ``__name__`` for
    SchemaValidationError so the event payload's ``model`` field is
    realistic."""

    goal: str


class _RouteModel(BaseModel):
    """Stand-in model for router-validation failures."""

    tool_name: str


class _ReflectModel(BaseModel):
    """Stand-in model for reflector-validation failures."""

    done: bool


class _FlakyPlanAgent(_OneShotAgent):
    """``_plan`` raises ``SchemaValidationError`` the first ``fail_count``
    times it's called; afterwards behaves like ``_OneShotAgent``. Lets us
    assert retry-then-recover paths without an LLM."""

    def __init__(self, *args: Any, fail_count: int = 2, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._fail_count = fail_count
        self._plan_attempts = 0

    async def _plan(self, goal: str) -> dict[str, Any]:
        self._plan_attempts += 1
        if self._plan_attempts <= self._fail_count:
            raise SchemaValidationError(_PlanModel, reason=f"flaky attempt {self._plan_attempts}")
        return await super()._plan(goal)


class _FlakyRouteAgent(_OneShotAgent):
    """``_route`` raises ``SchemaValidationError`` ``fail_count`` times,
    then returns the normal ``ToolDecision``."""

    def __init__(self, *args: Any, fail_count: int = 2, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._fail_count = fail_count
        self._route_attempts = 0

    async def _route(self, plan: Any, history: list[HistoryEntry]) -> ToolDecision:
        self._route_attempts += 1
        if self._route_attempts <= self._fail_count:
            raise SchemaValidationError(
                _RouteModel, reason=f"flaky route attempt {self._route_attempts}"
            )
        return await super()._route(plan, history)


class _FlakyReflectAgent(_OneShotAgent):
    """``_reflect`` raises ``SchemaValidationError`` ``fail_count`` times,
    then returns the normal terminal ``ReflectionDecision``."""

    def __init__(self, *args: Any, fail_count: int = 2, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._fail_count = fail_count
        self._reflect_attempts = 0

    async def _reflect(self, history: list[HistoryEntry]) -> ReflectionDecision:
        self._reflect_attempts += 1
        if self._reflect_attempts <= self._fail_count:
            raise SchemaValidationError(
                _ReflectModel, reason=f"flaky reflect attempt {self._reflect_attempts}"
            )
        return await super()._reflect(history)


class _BadArgsAgent(_OneShotAgent):
    """``_route`` returns a ``ToolDecision`` with args that fail the
    tool's ``input_schema`` ``fail_count`` times, then returns valid args.

    Exercises the raw ``pydantic.ValidationError`` path through the same
    retry helper (the tool-input gate, line 217 of agents/base.py)."""

    def __init__(self, *args: Any, fail_count: int = 2, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._fail_count = fail_count
        self._route_attempts = 0

    async def _route(self, plan: Any, history: list[HistoryEntry]) -> ToolDecision:
        self._route_attempts += 1
        if self._route_attempts <= self._fail_count:
            # `text` is required on _EchoIn — wrong-typed arg trips
            # pydantic.ValidationError at `tool.input_schema.model_validate`.
            return ToolDecision(tool_name="echo", args={"text": 12345})
        return await super()._route(plan, history)


async def test_plan_retries_then_succeeds_emits_validation_failed_then_complete() -> None:
    """Two plan failures, then success: assert 2x ``SCHEMA_VALIDATION_FAILED``
    events with monotonically-increasing attempt counter, then the normal
    six-event happy path follows."""
    emitter, sink = _make_emitter_with_sink()
    agent = _FlakyPlanAgent(emitter=emitter, tools=_make_registry(), fail_count=2)
    await agent.run("hello", session_id="s1")
    types = [e.type for e in sink.events]
    # PLAN_START is emitted ONCE (before the retry loop), then two failed
    # attempts emit SCHEMA_VALIDATION_FAILED, then PLAN_COMPLETE fires
    # after the 3rd (successful) attempt.
    assert types == [
        AgentEventType.PLAN_START,
        AgentEventType.SCHEMA_VALIDATION_FAILED,
        AgentEventType.SCHEMA_VALIDATION_FAILED,
        AgentEventType.PLAN_COMPLETE,
        AgentEventType.TOOL_CALL,
        AgentEventType.TOOL_RESULT,
        AgentEventType.REFLECT,
        AgentEventType.COMPLETE,
    ]
    failures = [e for e in sink.events if e.type is AgentEventType.SCHEMA_VALIDATION_FAILED]
    assert [f.payload["attempt"] for f in failures] == [1, 2]
    assert all(f.payload["model"] == "_PlanModel" for f in failures)
    assert all(f.payload["max_retries"] == 2 for f in failures)
    assert all(f.node == "plan" for f in failures)


async def test_plan_retries_exhausted_propagates_after_three_attempts() -> None:
    """fail_count=3 means all three attempts fail. Assert the exception
    propagates AND three SCHEMA_VALIDATION_FAILED events were emitted
    (the final attempt fires the event before raising — observability is
    not skipped on the propagating attempt)."""
    emitter, sink = _make_emitter_with_sink()
    agent = _FlakyPlanAgent(emitter=emitter, tools=_make_registry(), fail_count=3)
    with pytest.raises(SchemaValidationError) as excinfo:
        await agent.run("hello", session_id="s1")
    assert excinfo.value.model is _PlanModel
    failures = [e for e in sink.events if e.type is AgentEventType.SCHEMA_VALIDATION_FAILED]
    assert [f.payload["attempt"] for f in failures] == [1, 2, 3]
    # PLAN_COMPLETE is NOT in the trace — the loop never got there.
    assert not any(e.type is AgentEventType.PLAN_COMPLETE for e in sink.events)


async def test_route_retries_emit_at_route_node_not_tool_name() -> None:
    """A route-side schema failure carries node='route' (the agent-graph
    node label), not the eventual tool name — at retry time we may not
    even know what tool we're heading for."""
    emitter, sink = _make_emitter_with_sink()
    agent = _FlakyRouteAgent(emitter=emitter, tools=_make_registry(), fail_count=1)
    await agent.run("hello", session_id="s1")
    failures = [e for e in sink.events if e.type is AgentEventType.SCHEMA_VALIDATION_FAILED]
    assert len(failures) == 1
    assert failures[0].node == "route"
    assert failures[0].payload["model"] == "_RouteModel"
    # TOOL_CALL fires exactly once — only after the successful retry.
    tool_calls = [e for e in sink.events if e.type is AgentEventType.TOOL_CALL]
    assert len(tool_calls) == 1


async def test_tool_input_validation_failure_routes_through_same_gate() -> None:
    """Tool-input validation (raw ``pydantic.ValidationError`` from
    ``tool.input_schema.model_validate``) goes through the same retry
    helper as LLM-side ``SchemaValidationError``."""
    emitter, sink = _make_emitter_with_sink()
    agent = _BadArgsAgent(emitter=emitter, tools=_make_registry(), fail_count=1)
    await agent.run("hello", session_id="s1")
    failures = [e for e in sink.events if e.type is AgentEventType.SCHEMA_VALIDATION_FAILED]
    assert len(failures) == 1
    assert failures[0].node == "route"
    # Pydantic v2 ValidationError.title is the model class name — the
    # tool's `_EchoIn`, not the agent's `_RouteModel`.
    assert failures[0].payload["model"] == "_EchoIn"
    # error detail is the structured Pydantic .errors() list
    assert isinstance(failures[0].payload["errors"], list)
    assert failures[0].payload["errors"][0]["type"] == "string_type"


async def test_reflect_retries_succeed_then_complete_fires() -> None:
    emitter, sink = _make_emitter_with_sink()
    agent = _FlakyReflectAgent(emitter=emitter, tools=_make_registry(), fail_count=2)
    await agent.run("hello", session_id="s1")
    failures = [e for e in sink.events if e.type is AgentEventType.SCHEMA_VALIDATION_FAILED]
    assert [f.payload["attempt"] for f in failures] == [1, 2]
    assert all(f.node == "reflect" for f in failures)
    # The REFLECT event still fires after the successful retry, and
    # COMPLETE follows. The user sees one reflect step (not three).
    assert any(e.type is AgentEventType.REFLECT for e in sink.events)
    assert any(e.type is AgentEventType.COMPLETE for e in sink.events)


async def test_validation_failed_event_truncates_long_error_lists() -> None:
    """A pathological ValidationError with many errors gets capped in the
    event payload (full exception still propagates on the final attempt)."""
    from pydantic import ValidationError

    from framework.agents.base import _truncate_errors

    fake_errors = [
        {"type": "missing", "loc": (f"field_{i}",), "msg": f"required field {i}"} for i in range(10)
    ]
    truncated = _truncate_errors(fake_errors)
    assert len(truncated) == 4  # 3 head + 1 truncation marker
    assert truncated[-1]["type"] == "_truncated"
    assert "+7 more" in truncated[-1]["msg"]
    # ValidationError import is sanity — proves the type is reachable
    # from the helper's perspective (the helper accepts it).
    assert ValidationError is not None
