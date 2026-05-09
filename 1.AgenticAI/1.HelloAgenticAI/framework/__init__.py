"""HelloAgenticAI framework — reusable scaffolding for agentic AI on Azure.

Subpackages:
- agents: AgentBase, AgentState, graph nodes (Phase 2+)
- tools: MCPToolBase, ToolRegistry (Phase 2+)
- memory: Cosmos DB providers for sessions and traces (Phase 2+)
- observability: AgentEventEmitter sinks for App Insights, Langfuse, UI stream (Phase 2+)
- guardrails: Content Safety + Pydantic schema validation (Phase 2+)
- llm: typed Azure OpenAI client wrapper (Phase 2+)
- eval: EvalHarness, EvalCase, scoring (Phase 2+)
"""

__version__ = "0.1.0"
