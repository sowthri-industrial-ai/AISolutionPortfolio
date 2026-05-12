"""Unit tests for :class:`ChainlitSink`.

Tests inject a stand-in chainlit module so the suite never touches
Chainlit's runtime. We assert both per-event Step shape and the
error-surfacing path.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from demo_fruitmarket.ui.chainlit_sink import ChainlitSink
from framework.observability.events import AgentEvent, AgentEventType

# ---------- fake chainlit ----------


class _FakeStep:
    """Minimal stand-in for cl.Step that records mutations for assertions."""

    def __init__(self, *, name: str, type: str) -> None:
        self.name = name
        self.type = type
        self.input: str | None = None
        self.output: str | None = None
        self.language: str | None = None
        self.is_error: bool = False
        self.send_count = 0
        self.update_count = 0

    async def send(self) -> None:
        self.send_count += 1

    async def update(self) -> None:
        self.update_count += 1


class _FakeMessage:
    def __init__(self, *, content: str, author: str | None = None) -> None:
        self.content = content
        self.author = author
        self.send_count = 0

    async def send(self) -> None:
        self.send_count += 1


def _fake_chainlit_module() -> MagicMock:
    """Build a stand-in `chainlit` module the sink uses for Step / Message."""
    mod = MagicMock()
    created_steps: list[_FakeStep] = []
    created_messages: list[_FakeMessage] = []

    def step_factory(*, name: str, type: str) -> _FakeStep:
        s = _FakeStep(name=name, type=type)
        created_steps.append(s)
        return s

    def message_factory(*, content: str, author: str | None = None) -> _FakeMessage:
        m = _FakeMessage(content=content, author=author)
        created_messages.append(m)
        return m

    mod.Step = MagicMock(side_effect=step_factory)
    mod.Message = MagicMock(side_effect=message_factory)
    mod._created_steps = created_steps
    mod._created_messages = created_messages
    return mod


def _make_sink_with_fake() -> tuple[ChainlitSink, MagicMock]:
    fake = _fake_chainlit_module()
    sink = ChainlitSink(chainlit_module=fake)
    return sink, fake


# ---------- per-event-type rendering ----------


async def test_plan_start_creates_planning_step_with_goal_as_input() -> None:
    sink, fake = _make_sink_with_fake()
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.PLAN_START,
            payload={"goal": "buy a tropical basket"},
        )
    )
    assert len(fake._created_steps) == 1
    step = fake._created_steps[0]
    assert step.name == "Planning…"
    assert step.type == "llm"
    assert step.input == "buy a tropical basket"
    assert step.send_count == 1


async def test_plan_complete_updates_open_step_to_planned_with_json_output() -> None:
    sink, fake = _make_sink_with_fake()
    plan_payload = {"items": [{"sku": "mango", "quantity": 2}], "reasoning": "..."}
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.PLAN_START,
            payload={"goal": "g"},
        )
    )
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.PLAN_COMPLETE,
            payload={"plan": plan_payload},
        )
    )
    # Same Step object updated, not a new one created
    assert len(fake._created_steps) == 1
    step = fake._created_steps[0]
    assert step.name == "Planned"
    assert step.language == "json"
    assert "mango" in (step.output or "")
    assert step.update_count == 1


async def test_plan_complete_creates_step_if_no_open_one() -> None:
    """Defense — if PLAN_COMPLETE arrives without a prior PLAN_START
    (re-entry, sink swap, etc.) we still render a step rather than crash."""
    sink, fake = _make_sink_with_fake()
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.PLAN_COMPLETE,
            payload={"plan": {"items": []}},
        )
    )
    assert len(fake._created_steps) == 1
    assert fake._created_steps[0].name == "Planned"


async def test_tool_call_step_includes_shop_name_and_basket_json() -> None:
    sink, fake = _make_sink_with_fake()
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.TOOL_CALL,
            node="tropical_paradise",
            payload={"args": {"basket": [{"sku": "pineapple", "quantity": 1}]}},
        )
    )
    step = fake._created_steps[0]
    assert step.name == "Calling tropical_paradise…"
    assert step.type == "tool"
    assert "pineapple" in (step.input or "")


async def test_tool_result_step_summary_reflects_purchase_outcome() -> None:
    """Step name encodes the outcome at a glance: '<shop>: 0 bought, 1 OOS'."""
    sink, fake = _make_sink_with_fake()
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.TOOL_CALL,
            node="tropical_paradise",
            payload={"args": {}},
        )
    )
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.TOOL_RESULT,
            node="tropical_paradise",
            payload={
                "result": {
                    "shop_name": "tropical_paradise",
                    "purchased": [],
                    "out_of_stock": ["pineapple"],
                    "rationed": [],
                    "total_price": 0.0,
                }
            },
        )
    )
    assert len(fake._created_steps) == 1  # same step, updated
    assert fake._created_steps[0].name == "tropical_paradise: 1 OOS"


async def test_tool_result_step_summary_combines_bought_and_rationed() -> None:
    sink, fake = _make_sink_with_fake()
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.TOOL_CALL,
            node="tropical_paradise",
            payload={"args": {}},
        )
    )
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.TOOL_RESULT,
            node="tropical_paradise",
            payload={
                "result": {
                    "shop_name": "tropical_paradise",
                    "purchased": [
                        {"sku": "mango_alphonso", "quantity": 2},
                        {"sku": "dragon_fruit", "quantity": 2},
                    ],
                    "out_of_stock": ["pineapple"],
                    "rationed": ["dragon_fruit"],
                    "total_price": 12.00,
                }
            },
        )
    )
    assert fake._created_steps[0].name == "tropical_paradise: 4 bought, 1 OOS, 1 rationed"


async def test_reflect_step_distinguishes_continue_vs_done() -> None:
    sink, fake = _make_sink_with_fake()
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.REFLECT,
            payload={"done": False, "reasoning": "more shops to try", "answer": None},
        )
    )
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.REFLECT,
            payload={"done": True, "reasoning": "all sourced", "answer": "Got it"},
        )
    )
    assert [s.name for s in fake._created_steps] == [
        "Reflecting → Continue",
        "Reflecting → Done",
    ]


async def test_complete_step_then_user_facing_message() -> None:
    """COMPLETE emits BOTH a step AND a top-level cl.Message — the latter
    is the agent's user-facing reply."""
    sink, fake = _make_sink_with_fake()
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.COMPLETE,
            payload={
                "final_answer": "Got 1 pineapple for $8.00.",
                "iterations": 2,
            },
        )
    )
    assert len(fake._created_steps) == 1
    assert fake._created_steps[0].name == "Done — 2 iteration(s)"
    assert "1 pineapple" in (fake._created_steps[0].output or "")
    assert len(fake._created_messages) == 1
    assert fake._created_messages[0].content == "Got 1 pineapple for $8.00."


# ---------- pairing across multiple tool calls (replan path) ----------


async def test_two_tool_calls_for_different_shops_track_separate_steps() -> None:
    """Replan: TOOL_CALL on shop A, TOOL_RESULT on shop A, TOOL_CALL on B,
    TOOL_RESULT on B → 2 distinct steps, each correctly paired."""
    sink, fake = _make_sink_with_fake()
    for shop in ("tropical_paradise", "global_imports"):
        await sink.emit(
            AgentEvent(
                session_id="s1",
                type=AgentEventType.TOOL_CALL,
                node=shop,
                payload={"args": {"basket": [{"sku": "pineapple", "quantity": 1}]}},
            )
        )
        result_purchased = (
            []
            if shop == "tropical_paradise"
            else [{"sku": "pineapple", "quantity": 1, "unit_price": 8.0, "line_total": 8.0}]
        )
        result_oos = ["pineapple"] if shop == "tropical_paradise" else []
        await sink.emit(
            AgentEvent(
                session_id="s1",
                type=AgentEventType.TOOL_RESULT,
                node=shop,
                payload={
                    "result": {
                        "shop_name": shop,
                        "purchased": result_purchased,
                        "out_of_stock": result_oos,
                        "rationed": [],
                        "total_price": 0.0 if shop == "tropical_paradise" else 8.0,
                    }
                },
            )
        )
    # 2 steps total, each updated once
    assert len(fake._created_steps) == 2
    names = [s.name for s in fake._created_steps]
    assert names == ["tropical_paradise: 1 OOS", "global_imports: 1 bought"]


# ---------- error surfacing ----------


async def test_mark_failed_marks_all_open_steps_and_posts_error_message() -> None:
    sink, fake = _make_sink_with_fake()
    # Simulate two open steps (planner started + a tool call started)
    await sink.emit(
        AgentEvent(session_id="s1", type=AgentEventType.PLAN_START, payload={"goal": "g"})
    )
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.TOOL_CALL,
            node="tropical_paradise",
            payload={"args": {}},
        )
    )

    # Now agent.run() blows up with some error
    error = RuntimeError("Cosmos write timed out")
    await sink.mark_failed(error)

    # Both open steps marked errored with the failure label
    for step in fake._created_steps:
        assert step.is_error is True
        assert step.name.startswith("FAILED:")
        assert "Cosmos write timed out" in (step.output or "")
        assert "RuntimeError" in (step.output or "")

    # And a top-level message visible to the user
    assert len(fake._created_messages) == 1
    msg = fake._created_messages[0]
    assert "Cosmos write timed out" in msg.content
    assert "RuntimeError" in msg.content
    assert "❌" in msg.content  # the visible failure marker


async def test_mark_failed_with_no_open_steps_still_posts_message() -> None:
    sink, fake = _make_sink_with_fake()
    await sink.mark_failed(ValueError("planner returned empty plan"))
    assert len(fake._created_messages) == 1
    assert "ValueError" in fake._created_messages[0].content
    assert "planner returned empty plan" in fake._created_messages[0].content


async def test_subsequent_emit_after_failure_does_not_crash() -> None:
    """Belt-and-braces — sink errors must not break the agent loop."""
    sink, fake = _make_sink_with_fake()
    await sink.mark_failed(RuntimeError("fail"))
    # Even after failure, further events should not raise.
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.COMPLETE,
            payload={"final_answer": "post-failure event", "iterations": 0},
        )
    )
    # The complete event still rendered a step + message normally.
    assert any(s.name.startswith("Done") for s in fake._created_steps)


# ---------- sink is exception-safe ----------


async def test_sink_swallows_internal_exceptions(caplog: pytest.LogCaptureFixture) -> None:
    """If the chainlit module itself raises, sink logs and continues —
    must not propagate to the agent loop."""
    fake = MagicMock()
    fake.Step = MagicMock(side_effect=RuntimeError("chainlit websocket dropped"))
    fake.Message = MagicMock()
    sink = ChainlitSink(chainlit_module=fake)

    import logging

    with caplog.at_level(logging.ERROR):
        await sink.emit(
            AgentEvent(session_id="s1", type=AgentEventType.PLAN_START, payload={"goal": "g"})
        )
    assert "ChainlitSink failed handling plan_start" in caplog.text


# ---------- json serialisation defense ----------


async def test_non_json_serialisable_payload_falls_back_to_str() -> None:
    """If a payload field contains something json.dumps can't handle,
    we don't crash — we coerce to str(...) for display."""

    class _NotJsonable:
        def __repr__(self) -> str:
            return "<NotJsonable>"

    sink, fake = _make_sink_with_fake()
    await sink.emit(
        AgentEvent(
            session_id="s1",
            type=AgentEventType.PLAN_START,
            payload={"goal": "g"},
        )
    )
    # Hand-craft a PLAN_COMPLETE payload with a non-serialisable value
    # in plan; the sink must produce a string output, not raise.
    bad_payload: dict[str, Any] = {"plan": {"weird": _NotJsonable()}}
    e = AgentEvent(session_id="s1", type=AgentEventType.PLAN_COMPLETE, payload=bad_payload)
    await sink.emit(e)
    step = fake._created_steps[0]
    assert step.output is not None
    assert "<NotJsonable>" in step.output
