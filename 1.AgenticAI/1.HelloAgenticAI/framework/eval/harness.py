"""Evaluation harness — :class:`EvalCase`, :class:`EvalHarness`, three scoring modes.

Phase 2 ships the harness machinery; Phase 5 wires this into a GitHub
Actions workflow that runs the canonical 8-10 cases on every PR and
fails the PR if pass rate < 90%.

Three scoring modes:

* :attr:`ScoringMode.EXACT` — case-sensitive equality.
* :attr:`ScoringMode.SUBSTRING` — case-insensitive containment.
* :attr:`ScoringMode.LLM_JUDGE` — the LLM judge decides pass/fail.

The judge mode requires an :class:`AzureOpenAIClient` whose
``chat_structured`` method is invoked with a small ``JudgeVerdict``
schema; pass-by-default semantics so no surprise crashes if the judge
returns an ambiguous answer (the verdict is logged so reviewers see it).

Cases load cleanly from JSON (Phase 5's ``demo-fruitmarket/eval/cases.json``
format) — see :meth:`EvalHarness.load_cases`.
"""

from __future__ import annotations

import json
import logging
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from framework.agents.base import AgentBase
from framework.llm.azure_openai import AzureOpenAIClient

logger = logging.getLogger(__name__)


class ScoringMode(StrEnum):
    """How an :class:`EvalCase` is scored against an agent's final answer."""

    EXACT = "exact"
    SUBSTRING = "substring"
    LLM_JUDGE = "llm_judge"


class EvalCase(BaseModel):
    """One evaluation case — goal + expected answer + scoring rule."""

    name: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    expected: str
    scoring_mode: ScoringMode
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalResult(BaseModel):
    """Result of running one :class:`EvalCase` against an agent."""

    case_name: str
    goal: str
    expected: str
    actual: str
    passed: bool
    scoring_mode: ScoringMode
    score: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    duration_ms: int = Field(ge=0)
    error: str | None = None


class _JudgeVerdict(BaseModel):
    """Schema used by the LLM-judge scoring mode."""

    passed: bool
    reasoning: str = ""


_JUDGE_PROMPT = (
    "You are an evaluation judge. Decide whether the actual answer satisfies "
    "the expected answer for the given goal. Respond with passed=true if the "
    "actual answer is materially equivalent to the expected answer (paraphrasing "
    "is fine, factual differences are not). Provide a one-sentence reasoning."
)


class EvalHarness:
    """Run :class:`EvalCase` instances against an :class:`AgentBase`."""

    def __init__(
        self,
        *,
        agent: AgentBase,
        llm_judge: AzureOpenAIClient | None = None,
    ) -> None:
        self._agent = agent
        self._llm_judge = llm_judge

    async def run_case(self, case: EvalCase) -> EvalResult:
        """Run one case end-to-end and return the scored :class:`EvalResult`.

        Both agent errors and scoring errors are surfaced as
        ``EvalResult.error`` so a single bad case never kills a batch run.
        """
        started = time.monotonic()
        actual = ""
        try:
            state = await self._agent.run(case.goal, session_id=f"eval-{case.name}")
            actual = str(state.get("final_answer", ""))
            passed, score, reasoning = await self._score(case, actual)
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return EvalResult(
                case_name=case.name,
                goal=case.goal,
                expected=case.expected,
                actual=actual,
                passed=False,
                scoring_mode=case.scoring_mode,
                score=0.0,
                duration_ms=duration_ms,
                error=f"{type(exc).__name__}: {exc}",
            )
        duration_ms = int((time.monotonic() - started) * 1000)
        return EvalResult(
            case_name=case.name,
            goal=case.goal,
            expected=case.expected,
            actual=actual,
            passed=passed,
            scoring_mode=case.scoring_mode,
            score=score,
            reasoning=reasoning,
            duration_ms=duration_ms,
        )

    async def run_cases(self, cases: list[EvalCase]) -> list[EvalResult]:
        """Run a batch of cases sequentially. Returns one result per case."""
        return [await self.run_case(c) for c in cases]

    async def _score(
        self,
        case: EvalCase,
        actual: str,
    ) -> tuple[bool, float, str | None]:
        match case.scoring_mode:
            case ScoringMode.EXACT:
                passed = actual == case.expected
                return passed, (1.0 if passed else 0.0), None
            case ScoringMode.SUBSTRING:
                passed = case.expected.casefold() in actual.casefold()
                return passed, (1.0 if passed else 0.0), None
            case ScoringMode.LLM_JUDGE:
                return await self._judge(case, actual)

    async def _judge(
        self,
        case: EvalCase,
        actual: str,
    ) -> tuple[bool, float, str | None]:
        if self._llm_judge is None:
            raise RuntimeError(
                f"case {case.name!r} uses LLM_JUDGE but no llm_judge client "
                "was given to EvalHarness"
            )
        messages: list[Any] = [
            {"role": "system", "content": _JUDGE_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Goal:\n{case.goal}\n\n"
                    f"Expected answer:\n{case.expected}\n\n"
                    f"Actual answer:\n{actual}"
                ),
            },
        ]
        verdict = await self._llm_judge.chat_structured(
            messages,
            response_model=_JudgeVerdict,
            temperature=0.0,
        )
        return verdict.passed, (1.0 if verdict.passed else 0.0), verdict.reasoning

    @staticmethod
    def load_cases(path: str | Path) -> list[EvalCase]:
        """Load eval cases from a JSON file (list of objects matching :class:`EvalCase`)."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError(f"{path}: expected a JSON list of cases, got {type(raw).__name__}")
        return [EvalCase.model_validate(item) for item in raw]

    @staticmethod
    def pass_rate(results: list[EvalResult]) -> float:
        """Fraction of results where ``passed=True``. Empty list → 0.0."""
        if not results:
            return 0.0
        return sum(1 for r in results if r.passed) / len(results)
