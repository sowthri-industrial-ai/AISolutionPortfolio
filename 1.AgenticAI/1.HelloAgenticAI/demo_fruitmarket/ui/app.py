"""Chainlit entrypoint for the fruit-market demo.

Run locally:

.. code-block:: bash

    uv run chainlit run demo_fruitmarket/ui/app.py --host 0.0.0.0 --port 8000

Per :doc:`../../CLAUDE.md` "First-time / post-teardown developer setup":
the dev principal needs Cosmos and AOAI data-plane grants. AZURE_*
endpoint env vars are auto-loaded from ``azd env get-values`` if not
already set.

Each chat session creates a fresh :class:`FruitMarketContext`, runs the
agent, and closes both LLM and Cosmos handles cleanly via the async
context manager. Per-session agent instances are intentional:
:class:`FruitMarketAgent` stashes goal/plan on instance state for the
reflector, which is safe per-session but unsafe across sessions
(documented framework limitation; backlog item for v2).
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import chainlit as cl

from demo_fruitmarket.graph import build_fruit_market_context_from_endpoints
from demo_fruitmarket.ui.chainlit_sink import ChainlitSink

logger = logging.getLogger(__name__)


# ---------- env loading (mirrors tests/integration/conftest.py) ----------


def _load_azd_env_into_os_environ() -> None:
    """If AZURE_OPENAI_ENDPOINT isn't set, try `azd env get-values`."""
    if os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_COSMOS_ENDPOINT"):
        return
    # demo_fruitmarket/ui/app.py → ../../infra
    infra_dir = Path(__file__).resolve().parent.parent.parent / "infra"
    if not infra_dir.exists():
        return
    try:
        result = subprocess.run(
            ["azd", "env", "get-values"],
            cwd=str(infra_dir),
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, _, raw = line.partition("=")
        os.environ.setdefault(key.strip(), raw.strip().strip('"'))


_load_azd_env_into_os_environ()


_GREETING = (
    "Hi — I'm a **fruit-market shopping agent**. Tell me what you'd like "
    "to buy and I'll source it across our six shops, showing every step.\n\n"
    "Try one of these:\n"
    "- *Buy a tropical fruit basket under $20 — include pineapple, mango, "
    "and dragon fruit*\n"
    "- *Pick up some apples and pears for a fruit salad*\n"
    "- *Build me a berry mix: strawberries, blueberries, and raspberries*\n"
    "- *Find peaches and cherries, prefer local*\n"
    "- *I need 5 dragon fruit*"
)


@cl.on_chat_start  # type: ignore[untyped-decorator]  # chainlit's decorators are Any-typed
async def on_chat_start() -> None:
    aoai = os.getenv("AZURE_OPENAI_ENDPOINT")
    cosmos = os.getenv("AZURE_COSMOS_ENDPOINT")
    if not aoai or not cosmos:
        await cl.Message(
            content=(
                "❌ **Missing required environment variables.**\n\n"
                "AZURE_OPENAI_ENDPOINT and/or AZURE_COSMOS_ENDPOINT are not "
                "set, and `azd env get-values` couldn't find them either. "
                "Run Phase 1's `azd up` (or source the env file from `azd "
                "env get-values`) and reload."
            ),
        ).send()
        return
    await cl.Message(content=_GREETING).send()


@cl.on_message  # type: ignore[untyped-decorator]  # chainlit's decorators are Any-typed
async def on_message(message: cl.Message) -> None:
    aoai = os.getenv("AZURE_OPENAI_ENDPOINT")
    cosmos = os.getenv("AZURE_COSMOS_ENDPOINT")
    if not aoai or not cosmos:
        await cl.Message(
            content="❌ Cannot run agent: missing AZURE_OPENAI_ENDPOINT / AZURE_COSMOS_ENDPOINT.",
        ).send()
        return

    # Optional Phase 4 wiring — both env vars set by Bicep batch 7 (KV
    # secret-ref for LANGFUSE_HOST). When absent, the sink simply
    # doesn't render the "View full trace in Langfuse" link.
    langfuse_host = os.getenv("LANGFUSE_HOST")
    sink = ChainlitSink(langfuse_host=langfuse_host)
    session_id = f"chainlit-{uuid4().hex[:12]}"

    try:
        async with build_fruit_market_context_from_endpoints(
            aoai_endpoint=aoai,
            cosmos_endpoint=cosmos,
            extra_sinks=[sink],
        ) as ctx:
            try:
                await ctx.agent.run(message.content, session_id=session_id)
            except Exception as exc:
                # Agent loop blew up mid-flight (planner returned malformed JSON,
                # tool raised, AOAI auth lapsed, etc.) — show the user which
                # step failed and why, then return cleanly.
                logger.exception("Agent run failed for session %s", session_id)
                await sink.mark_failed(exc)
                return
            # Final answer surfacing happens inside ChainlitSink._on_complete:
            # COMPLETE emits the step AND a top-level cl.Message with the answer.
    except Exception as exc:
        # Catastrophic — couldn't even build the context (DefaultAzureCredential
        # failure, network at startup, etc.). Surface clearly.
        logger.exception("Failed to build agent context for session %s", session_id)
        await cl.Message(
            content=(
                f"❌ **Failed to start the agent.** "
                f"`{type(exc).__name__}: {exc}`\n\n"
                "This usually means Azure auth couldn't initialize — check "
                "`az login` and the dev-principal RBAC grants in CLAUDE.md."
            ),
        ).send()
