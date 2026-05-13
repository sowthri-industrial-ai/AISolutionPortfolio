"""End-to-end integration test for the Phase 2 framework.

Wires :class:`MinimalAgent` (a concrete :class:`AgentBase` subclass) against
the live AOAI + Cosmos resources provisioned in Phase 1, runs one agent
loop, and asserts that every :class:`AgentEventType` lands as a row in the
deployed Cosmos ``traces`` container.

This is the Phase 2 acceptance gate: validates the full event pipeline
end-to-end before Phase 4 wires in Langfuse Cloud + App Insights real
ingestion.

The test is decorated ``@pytest.mark.integration`` so it can be deselected
with ``-m "not integration"``. It needs:

* An ``azd`` environment (defaults to ``dev``) provisioned per Phase 1.
* The signed-in user (or managed identity) holding Cognitive Services
  OpenAI User on the AOAI account and Cosmos DB Built-in Data
  Contributor on the Cosmos account.
* The conftest auto-loads ``azd env get-values`` so the user doesn't
  need to export ``AZURE_OPENAI_ENDPOINT`` / ``AZURE_COSMOS_ENDPOINT``
  manually.

Run locally:

    cd 1.AgenticAI/1.HelloAgenticAI
    uv run pytest tests/integration/ -m integration -v

Cost: ~2 AOAI completion calls (≈1500 tokens, well under $0.01) + 6 Cosmos
trace writes (free under serverless's 1000-RU-baseline). Negligible.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel

from framework.agents.base import (
    AgentBase,
    HistoryEntry,
    ReflectionDecision,
    ToolDecision,
)
from framework.llm.azure_openai import AzureOpenAIClient
from framework.memory.cosmos import CosmosProvider, CosmosSink
from framework.observability.events import (
    AgentEventEmitter,
    AgentEventType,
    InMemorySink,
    LoggingSink,
)
from framework.tools.base import MCPToolBase, ToolRegistry

pytestmark = pytest.mark.integration


# ---------- in-process tool ----------


class _GreetIn(BaseModel):
    name: str


class _GreetOut(BaseModel):
    greeting: str


class _GreetTool(MCPToolBase[_GreetIn, _GreetOut]):
    """Trivial in-process tool — returns a greeting for the supplied name."""

    @property
    def name(self) -> str:
        return "greet"

    @property
    def description(self) -> str:
        return "Returns a friendly greeting for a person's name."

    @property
    def input_schema(self) -> type[_GreetIn]:
        return _GreetIn

    @property
    def output_schema(self) -> type[_GreetOut]:
        return _GreetOut

    async def call(self, payload: _GreetIn) -> _GreetOut:
        return _GreetOut(greeting=f"Hello, {payload.name}! Welcome to HelloAgenticAI.")


# ---------- agent ----------


class _GreetingPlan(BaseModel):
    """The structured plan extracted by the planner."""

    target_name: str


class MinimalAgent(AgentBase):
    """Minimum viable subclass of AgentBase that exercises the full loop.

    * ``_plan`` calls the deployed AOAI (via :meth:`AzureOpenAIClient.chat_structured`)
      to extract a target name from the goal — exercises the LLM auth path,
      structured outputs, and the AAD bearer token wiring.
    * ``_route`` is deterministic: always picks the ``greet`` tool with the
      planned name. Keeps the test reliable.
    * ``_reflect`` is deterministic: always returns ``done=True`` after the
      first tool call, with ``answer`` set to the greeting text. Keeps the
      test fast and avoids second-LLM-call flakiness.

    The framework still emits all six AgentEventTypes regardless of whether
    the subclass uses an LLM or deterministic logic for each step.
    """

    def __init__(
        self,
        *,
        emitter: AgentEventEmitter,
        tools: ToolRegistry,
        llm: AzureOpenAIClient,
        max_iterations: int = 2,
    ) -> None:
        super().__init__(emitter=emitter, tools=tools, max_iterations=max_iterations)
        self._llm = llm

    async def _plan(self, goal: str) -> _GreetingPlan:
        return await self._llm.chat_structured(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract the person's name from a greeting goal. "
                        "Respond with JSON matching the schema. If no specific "
                        "name is given, use 'World'."
                    ),
                },
                {"role": "user", "content": goal},
            ],
            response_model=_GreetingPlan,
            deployment=self._llm.chat_mini_deployment,
        )

    async def _route(
        self,
        plan: Any,
        history: list[HistoryEntry],
    ) -> ToolDecision:
        return ToolDecision(
            tool_name="greet",
            args={"name": plan.target_name},
            reasoning="Single-step plan: greet the planned name.",
        )

    async def _reflect(
        self,
        history: list[HistoryEntry],
    ) -> ReflectionDecision:
        last = history[-1]
        return ReflectionDecision(
            done=True,
            reasoning="One greet call satisfies the goal.",
            answer=str(last.result["greeting"]),
        )


# ---------- fixtures ----------


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} not set; run `azd up` (Phase 1) and re-run this test")
    return value


@pytest.fixture
def aoai_endpoint() -> str:
    return _require_env("AZURE_OPENAI_ENDPOINT")


@pytest.fixture
def cosmos_endpoint() -> str:
    return _require_env("AZURE_COSMOS_ENDPOINT")


# ---------- the test ----------


async def test_minimal_agent_writes_all_six_event_types_to_cosmos(
    aoai_endpoint: str,
    cosmos_endpoint: str,
) -> None:
    """End-to-end: real AOAI plans, in-process tool runs, every event lands
    as a doc in the deployed Cosmos ``traces`` container."""
    llm = AzureOpenAIClient.from_endpoint(endpoint=aoai_endpoint)
    cosmos = CosmosProvider.from_endpoint(endpoint=cosmos_endpoint)
    cosmos_sink = CosmosSink(cosmos)
    in_memory_sink = InMemorySink()
    emitter = AgentEventEmitter([cosmos_sink, in_memory_sink, LoggingSink()])

    tools = ToolRegistry()
    tools.register(_GreetTool())

    agent = MinimalAgent(emitter=emitter, tools=tools, llm=llm, max_iterations=2)

    session_id = f"phase2-it-{uuid4().hex[:12]}"

    try:
        final_state = await agent.run(
            "Greet a person named World",
            session_id=session_id,
        )
    finally:
        await llm.close()

    # ---------- in-memory sink: structural assertions ----------

    types_emitted = [e.type for e in in_memory_sink.events]
    assert types_emitted[0] is AgentEventType.PLAN_START
    assert types_emitted[-1] is AgentEventType.COMPLETE
    # Phase 2's six canonical event types must all appear on a happy-path
    # run. Subset (not equality) check — Phase 4 added
    # SCHEMA_VALIDATION_FAILED which is only emitted on validation
    # failure and is not expected here. Future phases will add more
    # conditional event types; this assertion stays correct as long as
    # the happy path keeps producing the canonical six.
    phase_2_canonical = {
        AgentEventType.PLAN_START,
        AgentEventType.PLAN_COMPLETE,
        AgentEventType.TOOL_CALL,
        AgentEventType.TOOL_RESULT,
        AgentEventType.REFLECT,
        AgentEventType.COMPLETE,
    }
    assert phase_2_canonical <= set(types_emitted), (
        f"Phase 2 canonical events missing from in-memory sink: "
        f"{phase_2_canonical - set(types_emitted)}"
    )

    assert all(e.session_id == session_id for e in in_memory_sink.events)
    assert final_state.get("final_answer") is not None
    assert "World" in str(final_state.get("final_answer"))

    # ---------- Cosmos round-trip: every type is persisted ----------

    try:
        docs = await cosmos.query_traces(session_id)
    finally:
        await cosmos.close()

    assert len(docs) == len(
        in_memory_sink.events
    ), f"Cosmos persisted {len(docs)} docs but emitter emitted {len(in_memory_sink.events)}"
    types_in_cosmos = {d["type"] for d in docs}
    types_emitted_values = {t.value for t in types_emitted}
    # Cosmos must persist exactly what the emitter emitted — no more, no
    # less. This catches a CosmosSink that silently drops events as well
    # as one that double-writes.
    assert types_in_cosmos == types_emitted_values, (
        f"Cosmos type set diverges from emitter type set: "
        f"in cosmos only={types_in_cosmos - types_emitted_values}; "
        f"in emitter only={types_emitted_values - types_in_cosmos}"
    )

    # Every persisted doc carries the right partition key + a UUID id.
    for doc in docs:
        assert doc["sessionId"] == session_id
        assert isinstance(doc["id"], str) and len(doc["id"]) >= 36

    # The TOOL_CALL doc names our tool; the TOOL_RESULT doc carries the
    # greeting payload — proves end-to-end through the framework.
    tool_call_doc = next(d for d in docs if d["type"] == AgentEventType.TOOL_CALL.value)
    assert tool_call_doc["node"] == "greet"
    assert tool_call_doc["payload"]["args"] == {"name": "World"}

    tool_result_doc = next(d for d in docs if d["type"] == AgentEventType.TOOL_RESULT.value)
    assert "World" in tool_result_doc["payload"]["result"]["greeting"]
