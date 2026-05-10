"""Unit tests for the evaluation harness — three scoring modes, batch
runs, JSON loading, error handling, pass-rate aggregation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from framework.agents.base import (
    AgentBase,
    HistoryEntry,
    ReflectionDecision,
    ToolDecision,
)
from framework.eval.harness import (
    EvalCase,
    EvalHarness,
    EvalResult,
    ScoringMode,
)
from framework.observability.events import AgentEventEmitter, InMemorySink
from framework.tools.base import MCPToolBase, ToolRegistry

# ---------- minimal agent harness fixtures ----------


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


class _OneShotAgent(AgentBase):
    """Returns the goal upper-cased as the final answer."""

    async def _plan(self, goal: str) -> dict[str, Any]:
        return {"goal": goal}

    async def _route(self, plan: Any, history: list[HistoryEntry]) -> ToolDecision:
        return ToolDecision(tool_name="echo", args={"text": plan["goal"]})

    async def _reflect(self, history: list[HistoryEntry]) -> ReflectionDecision:
        return ReflectionDecision(
            done=True,
            reasoning="echoed",
            answer=str(history[-1].result["echoed"]),
        )


def _make_agent() -> _OneShotAgent:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    return _OneShotAgent(emitter=AgentEventEmitter([InMemorySink()]), tools=reg)


# ---------- ScoringMode + EvalCase ----------


def test_scoring_modes_have_three_canonical_values() -> None:
    assert {m.value for m in ScoringMode} == {"exact", "substring", "llm_judge"}


def test_eval_case_requires_non_empty_name_and_goal() -> None:
    with pytest.raises(ValidationError):
        EvalCase(name="", goal="g", expected="x", scoring_mode=ScoringMode.EXACT)
    with pytest.raises(ValidationError):
        EvalCase(name="n", goal="", expected="x", scoring_mode=ScoringMode.EXACT)


# ---------- EXACT scoring ----------


async def test_exact_scoring_passes_on_exact_match() -> None:
    harness = EvalHarness(agent=_make_agent())
    case = EvalCase(
        name="echo-exact",
        goal="hello",
        expected="HELLO",
        scoring_mode=ScoringMode.EXACT,
    )
    result = await harness.run_case(case)
    assert result.passed is True
    assert result.score == 1.0
    assert result.actual == "HELLO"
    assert result.error is None


async def test_exact_scoring_fails_on_case_mismatch() -> None:
    harness = EvalHarness(agent=_make_agent())
    case = EvalCase(
        name="echo-exact-case",
        goal="hello",
        expected="hello",  # actual will be HELLO
        scoring_mode=ScoringMode.EXACT,
    )
    result = await harness.run_case(case)
    assert result.passed is False
    assert result.score == 0.0


# ---------- SUBSTRING scoring ----------


async def test_substring_scoring_passes_case_insensitively() -> None:
    harness = EvalHarness(agent=_make_agent())
    case = EvalCase(
        name="echo-sub",
        goal="hello world",
        expected="WORLD",
        scoring_mode=ScoringMode.SUBSTRING,
    )
    result = await harness.run_case(case)
    assert result.passed is True
    assert result.score == 1.0


async def test_substring_scoring_fails_when_absent() -> None:
    harness = EvalHarness(agent=_make_agent())
    case = EvalCase(
        name="echo-sub-miss",
        goal="hello",
        expected="goodbye",
        scoring_mode=ScoringMode.SUBSTRING,
    )
    result = await harness.run_case(case)
    assert result.passed is False


# ---------- LLM_JUDGE scoring ----------


def _mock_judge_returning(passed: bool, reasoning: str = "ok") -> MagicMock:
    """Mock AzureOpenAIClient.chat_structured returning a _JudgeVerdict."""
    judge = MagicMock()
    from framework.eval.harness import _JudgeVerdict

    judge.chat_structured = AsyncMock(
        return_value=_JudgeVerdict(passed=passed, reasoning=reasoning)
    )
    return judge


async def test_llm_judge_passes_when_verdict_passes() -> None:
    judge = _mock_judge_returning(passed=True, reasoning="materially equivalent")
    harness = EvalHarness(agent=_make_agent(), llm_judge=judge)
    case = EvalCase(
        name="judge-pass",
        goal="hello",
        expected="any case",
        scoring_mode=ScoringMode.LLM_JUDGE,
    )
    result = await harness.run_case(case)
    assert result.passed is True
    assert result.score == 1.0
    assert result.reasoning == "materially equivalent"
    judge.chat_structured.assert_awaited_once()


async def test_llm_judge_fails_when_verdict_fails() -> None:
    judge = _mock_judge_returning(passed=False, reasoning="not equivalent")
    harness = EvalHarness(agent=_make_agent(), llm_judge=judge)
    case = EvalCase(
        name="judge-fail",
        goal="hello",
        expected="something else",
        scoring_mode=ScoringMode.LLM_JUDGE,
    )
    result = await harness.run_case(case)
    assert result.passed is False
    assert result.reasoning == "not equivalent"


async def test_llm_judge_without_judge_client_raises() -> None:
    harness = EvalHarness(agent=_make_agent())  # no llm_judge
    case = EvalCase(
        name="needs-judge",
        goal="hi",
        expected="x",
        scoring_mode=ScoringMode.LLM_JUDGE,
    )
    # Note: error is raised inside run_case, where it's caught and surfaced
    # as a result with error set.
    result = await harness.run_case(case)
    assert result.error is not None
    assert "llm_judge" in result.error.lower() or "no llm_judge" in result.error.lower()


# ---------- batch run + pass-rate ----------


async def test_run_cases_returns_one_result_per_case() -> None:
    harness = EvalHarness(agent=_make_agent())
    cases = [
        EvalCase(name="a", goal="hello", expected="HELLO", scoring_mode=ScoringMode.EXACT),
        EvalCase(name="b", goal="world", expected="WORLD", scoring_mode=ScoringMode.EXACT),
        EvalCase(name="c", goal="hi", expected="MISS", scoring_mode=ScoringMode.EXACT),
    ]
    results = await harness.run_cases(cases)
    assert len(results) == 3
    assert [r.case_name for r in results] == ["a", "b", "c"]
    assert [r.passed for r in results] == [True, True, False]


def test_pass_rate_computation() -> None:
    results = [
        EvalResult(
            case_name=f"r{i}",
            goal="g",
            expected="e",
            actual="a",
            passed=passed,
            scoring_mode=ScoringMode.EXACT,
            score=1.0 if passed else 0.0,
            duration_ms=1,
        )
        for i, passed in enumerate([True, True, False, True])
    ]
    assert EvalHarness.pass_rate(results) == 0.75


def test_pass_rate_for_empty_list() -> None:
    assert EvalHarness.pass_rate([]) == 0.0


# ---------- JSON loading ----------


def test_load_cases_from_json(tmp_path: Path) -> None:
    file = tmp_path / "cases.json"
    file.write_text(
        json.dumps(
            [
                {
                    "name": "happy",
                    "goal": "hello",
                    "expected": "HELLO",
                    "scoring_mode": "exact",
                },
                {
                    "name": "judge",
                    "goal": "tell me a fruit",
                    "expected": "any tropical fruit name",
                    "scoring_mode": "llm_judge",
                    "metadata": {"category": "open_ended"},
                },
            ]
        )
    )
    cases = EvalHarness.load_cases(file)
    assert len(cases) == 2
    assert cases[0].name == "happy"
    assert cases[0].scoring_mode is ScoringMode.EXACT
    assert cases[1].metadata == {"category": "open_ended"}


def test_load_cases_rejects_non_list(tmp_path: Path) -> None:
    file = tmp_path / "bad.json"
    file.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(ValueError, match="expected a JSON list"):
        EvalHarness.load_cases(file)


# ---------- agent error handling ----------


class _ExplodingAgent(AgentBase):
    async def _plan(self, goal: str) -> Any:
        raise RuntimeError("planner exploded")

    async def _route(self, plan: Any, history: list[HistoryEntry]) -> ToolDecision:
        raise NotImplementedError

    async def _reflect(self, history: list[HistoryEntry]) -> ReflectionDecision:
        raise NotImplementedError


async def test_agent_error_is_surfaced_as_failed_result() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    agent = _ExplodingAgent(emitter=AgentEventEmitter([InMemorySink()]), tools=reg)
    harness = EvalHarness(agent=agent)
    case = EvalCase(
        name="boom",
        goal="hi",
        expected="x",
        scoring_mode=ScoringMode.EXACT,
    )
    result = await harness.run_case(case)
    assert result.passed is False
    assert result.score == 0.0
    assert result.error is not None
    assert "planner exploded" in result.error
    assert result.actual == ""
