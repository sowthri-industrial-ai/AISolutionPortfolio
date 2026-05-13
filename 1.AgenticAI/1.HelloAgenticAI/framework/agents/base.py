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
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Annotated, Any, TypedDict, TypeVar
from uuid import uuid4

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, ValidationError

from framework.guardrails.content_safety import (
    ContentSafetyClient,
    ContentSafetyError,
    HarmCategory,
    Severity,
)
from framework.guardrails.schema import SchemaValidationError
from framework.observability.events import (
    AgentEvent,
    AgentEventEmitter,
    AgentEventType,
)
from framework.tools.base import ToolRegistry

logger = logging.getLogger(__name__)

T = TypeVar("T")


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

    Phase 4 batch 3 adds the optional ``content_safety`` parameter for
    input/output guardrails. When supplied:

    * **Input gate** — :meth:`run` checks the user goal before the
      planner sees it. A BLOCK verdict raises :class:`ContentSafetyError`
      after emitting ``GUARDRAIL_BLOCKED`` (gate=input); ``PLAN_START``
      never fires.
    * **Output gate** — :meth:`_terminate_node` checks the final answer
      before emitting ``COMPLETE``. A BLOCK verdict replaces the answer
      with a redaction notice and emits ``GUARDRAIL_BLOCKED``
      (gate=output) *in addition to* ``COMPLETE`` — the latter carries
      the redacted text so downstream sinks (Chainlit step, Cosmos
      trace, Langfuse trace) still close the run cleanly.

    When ``content_safety=None`` (default), behavior is identical to
    Phase 3 — backward compatible with every existing test.
    """

    def __init__(
        self,
        *,
        emitter: AgentEventEmitter,
        tools: ToolRegistry,
        max_iterations: int = 3,
        content_safety: ContentSafetyClient | None = None,
    ) -> None:
        self._emitter = emitter
        self._tools = tools
        self._max_iterations = max_iterations
        self._content_safety = content_safety
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
        """Run the agent against ``goal`` and return the final state.

        If ``content_safety`` is configured and the input is BLOCKed,
        emits a ``GUARDRAIL_BLOCKED`` event (gate=input) and raises
        :class:`ContentSafetyError` before any agent-loop work happens —
        ``PLAN_START`` does not fire.
        """
        sid = session_id or str(uuid4())
        await self._enforce_input_gate(sid, goal)
        initial: AgentState = {
            "session_id": sid,
            "goal": goal,
            "history": [],
            "iteration": 0,
            "complete": False,
        }
        return await self._graph.ainvoke(initial)  # type: ignore[no-any-return]

    async def _enforce_input_gate(self, session_id: str, goal: str) -> None:
        """Phase 4 batch 3 input gate. No-op if ``content_safety`` is None.

        Emits ``GUARDRAIL_BLOCKED`` (gate=input) before raising so the
        block is visible in App Insights / Langfuse / Cosmos / the UI
        trace even though the agent loop never starts.
        """
        if self._content_safety is None:
            return
        result = await self._content_safety.check_text(goal)
        if not result.is_blocked():
            return
        categories = result.blocking_categories()
        severity = result.max_severity()
        await self._emit(
            session_id,
            AgentEventType.GUARDRAIL_BLOCKED,
            payload=_guardrail_blocked_payload("input", categories, severity),
        )
        raise ContentSafetyError(
            gate="input",
            blocking_categories=categories,
            severity=severity,
        )

    # ----- node implementations -----

    async def _plan_node(self, state: AgentState) -> dict[str, Any]:
        sid = state["session_id"]
        goal = state["goal"]
        await self._emit(sid, AgentEventType.PLAN_START, payload={"goal": goal})
        started = time.monotonic()
        # Schema gate (Phase 4): _plan typically calls chat_structured
        # which raises SchemaValidationError on parsed=None. Retry up to
        # 2x — same prompt, same temperature, fresh LLM dice — before
        # propagating. PROJECT_PLAN Phase 4 criterion.
        plan = await self._invoke_with_validation_retry(
            lambda: self._plan(goal),
            session_id=sid,
            node="plan",
        )
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

        # Schema gate (Phase 4): two failure modes covered by one retry
        # loop:
        # (1) `_route` calls chat_structured → SchemaValidationError if
        #     the LLM SDK can't produce a valid ToolDecision.
        # (2) `tool.input_schema.model_validate(decision.args)` → raw
        #     pydantic ValidationError if the LLM picked a real tool but
        #     gave args that don't fit its schema.
        # Both are LLM-output problems; the right response is to re-route
        # (re-prompt the planner/router), not to re-validate the same
        # args.
        async def _route_and_validate() -> tuple[Any, BaseModel]:
            decision_ = await self._route(state.get("plan"), history)
            tool_ = self._tools.get(decision_.tool_name)
            payload_ = tool_.input_schema.model_validate(decision_.args)
            return decision_, payload_

        decision, payload = await self._invoke_with_validation_retry(
            _route_and_validate,
            session_id=sid,
            node="route",
        )
        tool = self._tools.get(decision.tool_name)

        # TOOL_CALL emits only after the route+validate retry succeeds,
        # so the UI/trace never shows an orphan TOOL_CALL whose
        # tool.call() was never reached.
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
        # Schema gate (Phase 4): same retry treatment as plan/route — if
        # the reflector's chat_structured can't produce a valid
        # ReflectionDecision, try twice more before propagating.
        decision = await self._invoke_with_validation_retry(
            lambda: self._reflect(history),
            session_id=sid,
            node="reflect",
        )
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
        # Phase 4 batch 3 output gate. If a BLOCK fires, we replace the
        # answer with a redaction notice AND emit GUARDRAIL_BLOCKED in
        # addition to COMPLETE. Both fire deliberately:
        # - GUARDRAIL_BLOCKED for the workbook / Langfuse trace
        # - COMPLETE so the UI step trail closes cleanly and the
        #   redacted text is what Chainlit renders
        final_answer = await self._enforce_output_gate(sid, final_answer)
        await self._emit(
            sid,
            AgentEventType.COMPLETE,
            payload={
                "final_answer": final_answer,
                "iterations": state.get("iteration", 0),
            },
        )
        return {"final_answer": final_answer}

    async def _enforce_output_gate(self, session_id: str, final_answer: str) -> str:
        """Phase 4 batch 3 output gate. Returns the (possibly redacted)
        ``final_answer``. No-op if ``content_safety`` is None.

        Unlike the input gate, BLOCK does NOT raise — the run still
        completes; the user sees a polite "answer redacted" message
        instead of the agent's text. Raising here would orphan the run
        (the agent's done; just the answer is unsafe to surface) and
        complicate Chainlit's step rendering.
        """
        if self._content_safety is None:
            return final_answer
        result = await self._content_safety.check_text(final_answer)
        if not result.is_blocked():
            return final_answer
        categories = result.blocking_categories()
        severity = result.max_severity()
        await self._emit(
            session_id,
            AgentEventType.GUARDRAIL_BLOCKED,
            payload=_guardrail_blocked_payload("output", categories, severity),
        )
        return _output_redaction_notice(categories, severity)

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

    async def _invoke_with_validation_retry(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        session_id: str,
        node: str,
        max_retries: int = 2,
    ) -> T:
        """Run ``operation`` with retry-on-validation-failure semantics.

        On each :class:`SchemaValidationError` or :class:`ValidationError`
        from ``operation()``, emits an
        :attr:`AgentEventType.SCHEMA_VALIDATION_FAILED` event carrying the
        offending Pydantic model name, the attempt index, the budget, and
        a truncated error detail. Re-invokes ``operation`` up to
        ``max_retries`` more times; on the final failure, the exception
        propagates to the LangGraph loop (where Chainlit's error sink
        renders it as a failed step).

        PROJECT_PLAN Phase 4 criterion: "Pydantic schema validation
        enforced on every node's structured output (refuses malformed
        LLM outputs and retries up to 2x)." 3 attempts total at
        ``max_retries=2``; 3rd failure propagates.

        ``node`` is the agent-graph node label for the event ("plan" /
        "route" / "reflect") — distinct from the tool name (which would
        only be known after a successful route, and we may never get
        there).
        """
        for attempt in range(max_retries + 1):
            try:
                return await operation()
            except (SchemaValidationError, ValidationError) as exc:
                model_name, errors = _extract_validation_detail(exc)
                await self._emit(
                    session_id,
                    AgentEventType.SCHEMA_VALIDATION_FAILED,
                    node=node,
                    payload={
                        "model": model_name,
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                        "errors": errors,
                    },
                )
                if attempt >= max_retries:
                    raise
        # Unreachable — every loop iteration either returns or raises.
        raise AssertionError("unreachable")


# ---------- module-level helpers ----------


_MAX_VALIDATION_ERRORS_IN_EVENT = 3
"""How many Pydantic errors to include in a SCHEMA_VALIDATION_FAILED payload.

Real ValidationErrors on a deeply-nested model can balloon to dozens of
entries; trimming keeps the event small enough for Cosmos / App Insights
without losing the leading signal. The full exception still propagates if
retries exhaust — observability is the consolation prize, not the audit
trail."""


def _extract_validation_detail(
    exc: SchemaValidationError | ValidationError,
) -> tuple[str, list[Mapping[str, Any]] | str]:
    """Extract ``(model_name, error_detail)`` for the event payload.

    ``SchemaValidationError`` carries the model class directly + either a
    wrapped Pydantic ``ValidationError`` (use ``.errors()``) or a free-
    form ``reason`` string (use that as the detail). Raw ``ValidationError``
    has ``.title`` and ``.errors()``.

    The returned ``error_detail`` is either a list of Pydantic-error dicts
    (capped at :data:`_MAX_VALIDATION_ERRORS_IN_EVENT`) or a single string
    — both are JSON-serialisable for the event payload.
    """
    if isinstance(exc, SchemaValidationError):
        model_name = exc.model.__name__
        if exc.cause is not None:
            return model_name, _truncate_errors(exc.cause.errors())
        # reason-only construction (e.g. chat_structured parsed=None)
        return model_name, exc.reason or "no detail"
    # raw pydantic ValidationError — happens at the tool input gate
    model_name = exc.title or "<unknown>"
    return model_name, _truncate_errors(exc.errors())


def _truncate_errors(errors: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Cap a Pydantic ``.errors()`` list at the event-payload budget.

    Accepts the wider :class:`Sequence[Mapping]` so pydantic's typed
    :class:`pydantic_core.ErrorDetails` (a ``TypedDict``) and plain
    :class:`dict` test fixtures both pass.
    """
    if len(errors) <= _MAX_VALIDATION_ERRORS_IN_EVENT:
        return list(errors)
    head = list(errors[:_MAX_VALIDATION_ERRORS_IN_EVENT])
    tail_count = len(errors) - _MAX_VALIDATION_ERRORS_IN_EVENT
    return [*head, {"type": "_truncated", "msg": f"+{tail_count} more error(s) omitted"}]


def _coerce_history(raw: list[dict[str, Any]]) -> list[HistoryEntry]:
    """Re-hydrate the history list back into Pydantic models for subclasses."""
    return [HistoryEntry.model_validate(entry) for entry in raw]


# ---------- Phase 4 batch 3: guardrail payload + redaction notice ----------


def _guardrail_blocked_payload(
    gate: str,
    categories: list[HarmCategory],
    severity: Severity,
) -> dict[str, Any]:
    """Standardised payload for a ``GUARDRAIL_BLOCKED`` event.

    The workbook (deliverable 5) groups by ``payload.gate`` and
    ``payload.severity_name``; Langfuse tags traces with both. Keep this
    shape stable — sinks and KQL queries depend on it.
    """
    return {
        "gate": gate,
        "categories": [c.value for c in categories],
        "severity": severity.value,
        "severity_name": severity.name,
    }


def _output_redaction_notice(
    categories: list[HarmCategory],
    severity: Severity,
) -> str:
    """User-facing message when the output gate redacts the answer.

    Mentions the categories + severity so the user knows WHY their
    answer was withheld — opaque "filtered" messages are worse than no
    answer because they offer no guidance for rephrasing. The text is
    intentionally agent-voice (not error-voice) so Chainlit can render
    it as the final agent message, not as an error step.
    """
    cats = ", ".join(c.value for c in categories) or "<unknown>"
    return (
        "I generated an answer, but it was redacted by safety filters "
        f"before I could share it. Internal categories: {cats} "
        f"(severity={severity.name}). Please rephrase your goal or try "
        "a different prompt."
    )


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
