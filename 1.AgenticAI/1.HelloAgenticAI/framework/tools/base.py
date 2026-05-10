"""Tool abstractions — :class:`MCPToolBase` + :class:`ToolRegistry`.

The agent's router selects a tool from the registry by name, the agent
invokes it with a typed Pydantic input, and the tool returns a typed
Pydantic output. Phase 2 uses in-process subclasses (the integration test
defines one); Phase 3 introduces a transport-level subclass that calls a
single MCP-server Container App over HTTP/SSE — the agent code stays
identical across deployment models because both subclass
:class:`MCPToolBase`.

Per ADR / Q16 of the Phase 1 kickoff: in-process for Phase 2, single
shared MCP server (not 10 separate Container Apps) for Phase 3.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel


class MCPToolBase[I: BaseModel, O: BaseModel](ABC):
    """A tool the agent can route to.

    Subclasses provide:

    * :attr:`name` — unique identifier the router uses
    * :attr:`description` — natural-language hint the router LLM reads
    * :attr:`input_schema` / :attr:`output_schema` — typed I/O Pydantic
      models exposed to the router as JSON Schema
    * :meth:`call` — the actual implementation

    PEP 695 generic so subclass authoring stays type-safe; the registry
    erases the type parameters because it stores tools of different
    shapes by name.
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def input_schema(self) -> type[I]: ...

    @property
    @abstractmethod
    def output_schema(self) -> type[O]: ...

    @abstractmethod
    async def call(self, payload: I) -> O: ...

    def to_router_descriptor(self) -> dict[str, Any]:
        """JSON-serializable description for the router LLM prompt."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema.model_json_schema(),
            "output_schema": self.output_schema.model_json_schema(),
        }


class ToolNotFoundError(KeyError):
    """Raised by :meth:`ToolRegistry.get` when a name isn't registered."""

    def __init__(self, name: str) -> None:
        super().__init__(f"no such tool: {name}")
        self.tool_name = name


class ToolAlreadyRegisteredError(ValueError):
    """Raised by :meth:`ToolRegistry.register` on a duplicate name."""

    def __init__(self, name: str) -> None:
        super().__init__(f"tool already registered: {name}")
        self.tool_name = name


class ToolRegistry:
    """Registry of available tools, lookup by name.

    Stores tools as :class:`MCPToolBase[Any, Any]` — type erasure at the
    container is the price of mixing differently-shaped tools by name.
    The router and tool-call sites validate types at runtime via the
    tools' own ``input_schema`` / ``output_schema``.
    """

    def __init__(self) -> None:
        self._tools: dict[str, MCPToolBase[Any, Any]] = {}

    def register(self, tool: MCPToolBase[Any, Any]) -> None:
        if tool.name in self._tools:
            raise ToolAlreadyRegisteredError(tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> MCPToolBase[Any, Any]:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolNotFoundError(name) from None

    def names(self) -> list[str]:
        """Sorted tool names."""
        return sorted(self._tools.keys())

    def descriptors(self) -> list[dict[str, Any]]:
        """All tools' router descriptors — for the planner / router prompt."""
        return [self._tools[n].to_router_descriptor() for n in self.names()]

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self) -> Iterator[str]:
        return iter(self.names())
