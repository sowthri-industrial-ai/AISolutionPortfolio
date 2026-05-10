"""Unit tests for the tool base + registry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from framework.tools.base import (
    MCPToolBase,
    ToolAlreadyRegisteredError,
    ToolNotFoundError,
    ToolRegistry,
)

# ---------- test fixtures: concrete tool subclasses ----------


class _EchoIn(BaseModel):
    text: str


class _EchoOut(BaseModel):
    echoed: str


class _EchoTool(MCPToolBase[_EchoIn, _EchoOut]):
    """Trivial tool — returns its input wrapped in `echoed`."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes the supplied text back to the caller."

    @property
    def input_schema(self) -> type[_EchoIn]:
        return _EchoIn

    @property
    def output_schema(self) -> type[_EchoOut]:
        return _EchoOut

    async def call(self, payload: _EchoIn) -> _EchoOut:
        return _EchoOut(echoed=payload.text)


class _AddIn(BaseModel):
    a: int
    b: int


class _AddOut(BaseModel):
    sum: int


class _AddTool(MCPToolBase[_AddIn, _AddOut]):
    @property
    def name(self) -> str:
        return "add"

    @property
    def description(self) -> str:
        return "Adds two integers."

    @property
    def input_schema(self) -> type[_AddIn]:
        return _AddIn

    @property
    def output_schema(self) -> type[_AddOut]:
        return _AddOut

    async def call(self, payload: _AddIn) -> _AddOut:
        return _AddOut(sum=payload.a + payload.b)


# ---------- MCPToolBase ----------


def test_cannot_instantiate_abstract_base() -> None:
    """ABC enforcement — must subclass and implement everything."""
    with pytest.raises(TypeError):
        MCPToolBase()  # type: ignore[abstract]


async def test_subclass_call_works() -> None:
    tool = _EchoTool()
    out = await tool.call(_EchoIn(text="hi"))
    assert out.echoed == "hi"


def test_to_router_descriptor_shape() -> None:
    tool = _EchoTool()
    d = tool.to_router_descriptor()
    assert d["name"] == "echo"
    assert "Echoes" in d["description"]
    assert d["input_schema"]["properties"]["text"]["type"] == "string"
    assert d["output_schema"]["properties"]["echoed"]["type"] == "string"


# ---------- ToolRegistry: register / get ----------


def test_register_and_get() -> None:
    reg = ToolRegistry()
    tool = _EchoTool()
    reg.register(tool)
    assert reg.get("echo") is tool


def test_register_collision_raises() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    with pytest.raises(ToolAlreadyRegisteredError) as excinfo:
        reg.register(_EchoTool())
    assert excinfo.value.tool_name == "echo"


def test_get_unknown_tool_raises() -> None:
    reg = ToolRegistry()
    with pytest.raises(ToolNotFoundError) as excinfo:
        reg.get("missing")
    assert excinfo.value.tool_name == "missing"


def test_tool_not_found_is_a_key_error() -> None:
    """Subclass relationship — generic except KeyError still catches it."""
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.get("missing")


def test_tool_already_registered_is_a_value_error() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    with pytest.raises(ValueError):
        reg.register(_EchoTool())


# ---------- ToolRegistry: collection protocol ----------


def test_names_returns_sorted_list() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    reg.register(_AddTool())
    assert reg.names() == ["add", "echo"]


def test_contains_membership() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    assert "echo" in reg
    assert "missing" not in reg
    assert 42 not in reg  # non-string is never a member


def test_len_reflects_registered_count() -> None:
    reg = ToolRegistry()
    assert len(reg) == 0
    reg.register(_EchoTool())
    assert len(reg) == 1
    reg.register(_AddTool())
    assert len(reg) == 2


def test_iter_yields_names_in_sorted_order() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    reg.register(_AddTool())
    assert list(reg) == ["add", "echo"]


# ---------- ToolRegistry: descriptors ----------


def test_descriptors_returns_one_entry_per_tool_in_sorted_order() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    reg.register(_AddTool())
    descriptors = reg.descriptors()
    assert [d["name"] for d in descriptors] == ["add", "echo"]
    # Each descriptor has all four required keys.
    for d in descriptors:
        assert set(d) >= {"name", "description", "input_schema", "output_schema"}


# ---------- end-to-end registry → call ----------


async def test_get_and_call_round_trip() -> None:
    reg = ToolRegistry()
    reg.register(_AddTool())
    tool = reg.get("add")
    payload = tool.input_schema.model_validate({"a": 2, "b": 3})
    result = await tool.call(payload)
    assert isinstance(result, _AddOut)
    assert result.sum == 5
