"""F3 agent CLI REPL.

One REPL session = one thread_id (UUID4 generated at start). Conversation
continuity within the session is checkpointed by MemorySaver in-process —
nothing persists across CLI invocations. Each new REPL gets a fresh thread.

Lifecycle:
    1. Generate thread_id
    2. Pre-flight check_health to confirm Stage 3 is reachable
    3. Loop: read user input -> agent.astream -> render events -> repeat
    4. On 'exit'/'quit'/Ctrl-D/Ctrl-C-on-prompt: close MCP subprocess + exit

Usage:
    .venv/bin/python cli.py

Required env:
    ANTHROPIC_API_KEY    Claude Sonnet 4.6 API key

Optional env:
    STAGE3_BASE_URL      default http://localhost:8080
    AGENT_MODEL          default claude-sonnet-4-6
    AGENT_TEMPERATURE    default 0.0
    AGENT_MAX_TOKENS     default 4096
    SETPOINT_DICT_PATH   passed through to mcp_server.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent import build_agent, thread_config


BANNER = """\
═══════════════════════════════════════════════════════════════════════════
 F3 Refinery Digital Twin — Agent CLI
═══════════════════════════════════════════════════════════════════════════
 Model     : {model}
 Stage 3   : {stage3}
 Thread    : {thread_id}
 Posture   : cautious (advisory mode default)

 Commands  : exit | quit | Ctrl-D       end session
             Ctrl-C                     interrupt current response
═══════════════════════════════════════════════════════════════════════════
"""


def _short(v: Any, n: int = 140) -> str:
    s = str(v).replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _render_update(update: dict[str, Any]) -> None:
    """Render one streamed update from agent.astream(..., stream_mode='updates').

    Updates look like:
        {"agent": {"messages": [AIMessage(...)]}}
        {"tools": {"messages": [ToolMessage(...)]}}
    """
    for node_name, payload in update.items():
        for msg in payload.get("messages", []):
            # Tool call requested by the model
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    name = tc.get("name", "?")
                    args = tc.get("args", {})
                    print(f"  -> tool: {name}({_short(args)})", flush=True)
                # Any prose alongside the tool call
                if isinstance(msg.content, str) and msg.content.strip():
                    print(f"\n{msg.content.strip()}\n", flush=True)
            # Tool result
            elif isinstance(msg, ToolMessage):
                print(f"  <- {msg.name}: {_short(msg.content)}", flush=True)
            # Final assistant text (no tool calls)
            elif isinstance(msg, AIMessage) and msg.content:
                text = msg.content if isinstance(msg.content, str) else str(msg.content)
                if text.strip():
                    print(f"\n{text.strip()}\n", flush=True)


async def _preflight(agent, config) -> bool:
    """Run check_health once at startup so connection problems surface
    immediately rather than on the first user turn. Returns True on success
    so the REPL knows whether to proceed."""
    print("[preflight] check_health ... ", end="", flush=True)
    try:
        result = await agent.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content="Run check_health and print the raw JSON result. "
                        "Do not interpret it; just call the tool and echo back."
                    )
                ]
            },
            config=config,
        )
        # Last message should be the agent's summary
        last = result["messages"][-1] if result.get("messages") else None
        if last and getattr(last, "content", None):
            snippet = _short(last.content, 200)
            print(f"ok\n  {snippet}", flush=True)
            return True
        print("ok (no content)", flush=True)
        return True
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}", flush=True)
        return False


async def repl() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ERROR: ANTHROPIC_API_KEY not set. Cannot start agent.",
            file=sys.stderr,
        )
        sys.exit(2)

    thread_id = str(uuid.uuid4())
    print(
        BANNER.format(
            model=os.environ.get("AGENT_MODEL", "claude-sonnet-4-6"),
            stage3=os.environ.get("STAGE3_BASE_URL", "http://localhost:8080"),
            thread_id=thread_id,
        ),
        flush=True,
    )

    agent, client = await build_agent()
    config = thread_config(thread_id)

    try:
        ok = await _preflight(agent, config)
        if not ok:
            print(
                "\n[hint] Stage 3 must be running on STAGE3_BASE_URL before the\n"
                "       agent can read live values. Start it with:\n"
                "         cd ../stage3 && arch -x86_64 ../.venv-x86/bin/uvicorn \\\n"
                "             api:app --port 8080\n"
                "       Then re-run this CLI.\n",
                flush=True,
            )

        while True:
            try:
                user_text = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[session ended]", flush=True)
                break

            if not user_text:
                continue
            if user_text.lower() in ("exit", "quit"):
                print("[session ended]", flush=True)
                break

            try:
                async for update in agent.astream(
                    {"messages": [HumanMessage(content=user_text)]},
                    config=config,
                    stream_mode="updates",
                ):
                    _render_update(update)
            except KeyboardInterrupt:
                print(
                    "\n[interrupted — session continues; thread state preserved]",
                    flush=True,
                )
                continue
            except Exception as e:
                print(
                    f"\n[error] {type(e).__name__}: {e}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
    finally:
        # Best-effort cleanup of the MCP subprocess. Different
        # langchain-mcp-adapters versions expose different close hooks; try
        # the documented ones and let the process exit reap whatever's left.
        for closer in ("aclose", "close", "__aexit__"):
            fn = getattr(client, closer, None)
            if fn is None:
                continue
            try:
                if closer == "__aexit__":
                    await fn(None, None, None)
                else:
                    result = fn()
                    if asyncio.iscoroutine(result):
                        await result
                break
            except Exception:
                continue


if __name__ == "__main__":
    try:
        asyncio.run(repl())
    except KeyboardInterrupt:
        pass
