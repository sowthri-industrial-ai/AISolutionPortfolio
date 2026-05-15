"""F3 LangGraph agent — Claude Sonnet 4.6 + MCP tools over stdio.

Wires the FastMCP server (mcp_server.py) into a LangGraph ReAct agent.

Architecture:
  CLI process  ─── stdio ───>  mcp_server.py  ─── httpx ───>  Stage 3 FastAPI
  (this file)                  (subprocess)                   (separate process)

The MCP server is launched as a subprocess by MultiServerMCPClient. The
agent calls tools over the stdio channel; mutations land at Stage 3's
HTTP API, which talks to the Stage 2 streamer via the perturbation inbox.

MemorySaver checkpointer provides conversation continuity within one CLI
session. Sessions are scoped by thread_id (UUID per REPL session, supplied
by cli.py).

Env vars consumed at agent build time:
    ANTHROPIC_API_KEY   required (langchain-anthropic reads it)
    AGENT_MODEL         default claude-sonnet-4-6
    AGENT_TEMPERATURE   default 0.0 (deterministic tool selection)
    AGENT_MAX_TOKENS    default 4096
    STAGE3_BASE_URL     default http://localhost:8080 (passed through to MCP server)
    SETPOINT_DICT_PATH  optional override, passed through
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from prompts import SYSTEM_PROMPT

_HERE = Path(__file__).resolve().parent

# Spawn the MCP server using THIS venv's interpreter. The MCP server lives
# alongside this file, so the path is stable.
MCP_SERVER_PATH = str(_HERE / "mcp_server.py")
MCP_SERVER_PYTHON = str(_HERE / ".venv" / "bin" / "python")

MODEL_NAME = os.environ.get("AGENT_MODEL", "claude-sonnet-4-6")
AGENT_TEMPERATURE = float(os.environ.get("AGENT_TEMPERATURE", "0.0"))
AGENT_MAX_TOKENS = int(os.environ.get("AGENT_MAX_TOKENS", "4096"))


def _mcp_subprocess_env() -> dict[str, str]:
    """Env vars to propagate into the spawned MCP subprocess. We don't pass
    the full os.environ — only the variables mcp_server.py actually reads,
    so the subprocess starts in a known state."""
    pass_through = ("STAGE3_BASE_URL", "SETPOINT_DICT_PATH", "MCP_HTTP_TIMEOUT")
    env = {k: os.environ[k] for k in pass_through if k in os.environ}
    # PATH is needed for the python interpreter to find shared libs etc.
    if "PATH" in os.environ:
        env["PATH"] = os.environ["PATH"]
    return env


async def build_agent() -> tuple[Any, MultiServerMCPClient]:
    """Spin up the MCP subprocess, load its tools, and wire a ReAct agent
    with MemorySaver checkpointing.

    Returns (compiled_agent, mcp_client). The caller owns lifecycle:
      - call `agent.ainvoke(...)` or `agent.astream(...)` with a config dict
        carrying {"configurable": {"thread_id": "..."}} for memory scoping
      - on shutdown, call `await mcp_client.__aexit__(None, None, None)` or
        the equivalent close hook to terminate the subprocess
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. langchain-anthropic requires it for "
            "claude-sonnet-4-6 access."
        )

    client = MultiServerMCPClient(
        {
            "refinery": {
                "command": MCP_SERVER_PYTHON,
                "args": [MCP_SERVER_PATH],
                "transport": "stdio",
                "env": _mcp_subprocess_env(),
            }
        }
    )
    tools = await client.get_tools()

    model = ChatAnthropic(
        model=MODEL_NAME,
        temperature=AGENT_TEMPERATURE,
        max_tokens=AGENT_MAX_TOKENS,
    )

    checkpointer = MemorySaver()

    agent = create_react_agent(
        model,
        tools,
        prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
        name="refinery-twin-agent",
    )
    return agent, client


def thread_config(thread_id: str) -> dict[str, Any]:
    """Build the LangGraph config dict for a given REPL session thread."""
    return {"configurable": {"thread_id": thread_id}}
