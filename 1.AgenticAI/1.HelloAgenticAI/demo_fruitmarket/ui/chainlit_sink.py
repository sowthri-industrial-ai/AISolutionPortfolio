""":class:`ChainlitSink` — renders :class:`AgentEvent` as Chainlit steps.

Lives in the demo (not in :mod:`framework.observability`) because it
imports Chainlit. The framework stays UI-agnostic; verticals provide
their own UI sink. The refinery vertical might use a different sink
(dashboard over WebSockets, Streamlit, etc.) and the framework's
event-emitter contract is unchanged.

Per-event-type UI rendering — what the user actually sees:

* ``PLAN_START`` — Step ``"Planning…"`` (type ``llm``, spinner).
  Shows the user goal as the step's input.
* ``PLAN_COMPLETE`` — same step, renamed to ``"Planned"``, with the
  full plan JSON (items, budget, preferences, reasoning) as output —
  collapsed by default.
* ``TOOL_CALL`` — Step ``"Calling <shop>…"`` (type ``tool``, spinner)
  with the basket JSON as input.
* ``TOOL_RESULT`` — same step, renamed to a one-line summary like
  ``"tropical_paradise: 2 bought, 1 OOS, 1 rationed"`` — full
  ShopResponse JSON as output, collapsed.
* ``REFLECT`` — Step ``"Reflecting → Continue"`` or
  ``"Reflecting → Done"`` (type ``llm``) with the reflector verdict
  JSON as output.
* ``COMPLETE`` — Step ``"Done — N iteration(s)"`` (type ``run``) with
  the final answer text as output. Plus a top-level :class:`cl.Message`
  with the same answer — that's the agent's "voice" reply, separate
  from the step trail.

Error surfacing:

* If any LLM call inside ``_plan`` / ``_route`` / ``_reflect`` raises
  (malformed JSON beyond retries, AOAI auth lapse, etc.) → the currently-
  open step is marked ``is_error=True`` with the exception class + message
  in its output, all other open steps are also marked errored, and a
  top-level :class:`cl.Message` is posted with the failure summary
  (``"❌ <ErrorClass>: <message>"``). User sees WHICH step failed and why.
* If a shop tool's ``call()`` raises → same treatment via
  :meth:`mark_failed`. The TOOL_CALL step (open at the time of failure)
  shows the error.
* If the loop hits ``max_iterations`` without the reflector saying
  ``done=True`` → not an error, the framework's ``_reflect_node`` force-
  sets ``complete=True`` and the COMPLETE event fires normally. The final
  answer may be a fallback string ("Task completed after N tool call(s)…")
  rather than a polished reflector-written one. This is visible to the
  user as a less-polished final answer; not flagged as an error.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from framework.guardrails.content_safety import ContentSafetyError
from framework.observability.events import AgentEvent, AgentEventType

logger = logging.getLogger(__name__)


# Step keys used to pair START/COMPLETE events. Tool steps are also keyed
# by the shop name so multiple tool calls per session don't collide.
_PLAN_KEY = "plan"


def _tool_key(shop: str) -> str:
    return f"tool:{shop}"


class ChainlitSink:
    """Translates agent events into Chainlit steps + a final message.

    Parameters
    ----------
    chainlit_module:
        Override for the imported ``chainlit`` package — lets tests inject
        a stand-in module without installing Chainlit's runtime. Defaults
        to ``import chainlit``.
    langfuse_host:
        Langfuse Cloud host URL (e.g. ``https://cloud.langfuse.com``). When
        supplied, the COMPLETE handler appends a "🔗 View full trace in
        Langfuse" link to the agent's reply, pointing at
        ``{host}/trace/{session_id}``. The Langfuse trace id IS the session
        id (1:1 mapping established in :mod:`framework.observability.langfuse`),
        so the link is constructed locally — no round-trip to Langfuse to
        resolve a trace URL. Pass ``None`` (default) to suppress the link.
    """

    def __init__(
        self,
        *,
        chainlit_module: Any = None,
        langfuse_host: str | None = None,
    ) -> None:
        if chainlit_module is None:
            import chainlit as cl  # imported here so tests don't need chainlit

            chainlit_module = cl
        self._cl = chainlit_module
        self._langfuse_host = langfuse_host.rstrip("/") if langfuse_host else None
        # In-flight steps awaiting their COMPLETE/RESULT counterpart.
        self._open_steps: dict[str, Any] = {}

    # ----- EventSink protocol -----

    async def emit(self, event: AgentEvent) -> None:
        try:
            await self._dispatch(event)
        except Exception:
            # Sink errors must not break the agent loop. The graph factory
            # already passes swallow_sink_errors=True; this is belt-and-
            # braces for any UI-side exception (e.g. WebSocket dropped).
            logger.exception("ChainlitSink failed handling %s", event.type.value)

    async def _dispatch(self, event: AgentEvent) -> None:
        match event.type:
            case AgentEventType.PLAN_START:
                await self._on_plan_start(event)
            case AgentEventType.PLAN_COMPLETE:
                await self._on_plan_complete(event)
            case AgentEventType.TOOL_CALL:
                await self._on_tool_call(event)
            case AgentEventType.TOOL_RESULT:
                await self._on_tool_result(event)
            case AgentEventType.REFLECT:
                await self._on_reflect(event)
            case AgentEventType.COMPLETE:
                await self._on_complete(event)

    # ----- per-event handlers -----

    async def _on_plan_start(self, event: AgentEvent) -> None:
        goal = event.payload.get("goal", "")
        step = self._cl.Step(name="Planning…", type="llm")
        step.input = str(goal)
        await step.send()
        self._open_steps[_PLAN_KEY] = step

    async def _on_plan_complete(self, event: AgentEvent) -> None:
        plan_payload = event.payload.get("plan", {})
        step = self._open_steps.pop(_PLAN_KEY, None)
        if step is None:
            step = self._cl.Step(name="Planned", type="llm")
            await step.send()
        else:
            step.name = "Planned"
        step.output = _pretty_json(plan_payload)
        step.language = "json"
        await step.update()

    async def _on_tool_call(self, event: AgentEvent) -> None:
        shop = event.node or "unknown_shop"
        args = event.payload.get("args", {})
        step = self._cl.Step(name=f"Calling {shop}…", type="tool")
        step.input = _pretty_json(args)
        await step.send()
        self._open_steps[_tool_key(shop)] = step

    async def _on_tool_result(self, event: AgentEvent) -> None:
        shop = event.node or "unknown_shop"
        result = event.payload.get("result", {})
        step = self._open_steps.pop(_tool_key(shop), None)
        summary = self._tool_result_summary(shop, result)
        if step is None:
            step = self._cl.Step(name=summary, type="tool")
            await step.send()
        else:
            step.name = summary
        step.output = _pretty_json(result)
        step.language = "json"
        await step.update()

    async def _on_reflect(self, event: AgentEvent) -> None:
        done = bool(event.payload.get("done"))
        verdict = "Done" if done else "Continue"
        step = self._cl.Step(name=f"Reflecting → {verdict}", type="llm")
        step.output = _pretty_json(event.payload)
        step.language = "json"
        await step.send()
        await step.update()

    async def _on_complete(self, event: AgentEvent) -> None:
        final_answer = event.payload.get("final_answer", "(no answer produced)")
        iterations = event.payload.get("iterations")
        step_name = "Done"
        if isinstance(iterations, int) and iterations > 0:
            step_name = f"Done — {iterations} iteration(s)"
        step = self._cl.Step(name=step_name, type="run")
        step.output = str(final_answer)
        await step.send()
        await step.update()
        # The final answer surfaces as the agent's top-level message.
        # When Langfuse is configured, append a "View full trace" link
        # below the answer (separate message so the agent's answer stays
        # clean and copy-pasteable). The link is constructed locally
        # from session_id — the trace id IS the session id, no round-
        # trip to Langfuse needed.
        await self._cl.Message(content=str(final_answer)).send()
        if self._langfuse_host is not None:
            trace_url = f"{self._langfuse_host}/trace/{event.session_id}"
            await self._cl.Message(
                content=f"🔗 [View full trace in Langfuse]({trace_url})",
            ).send()

    # ----- error surfacing (called by app.py on agent.run() exception) -----

    async def mark_failed(self, error: BaseException) -> None:
        """Mark any open steps as errored and post a top-level error message.

        Called by the Chainlit app's exception handler when the agent loop
        raises. User sees:

        * the failed step name + ``is_error=True`` + the exception class +
          message in its output (so they can see WHICH step failed and why);
        * a top-level :class:`cl.Message` with the user-facing error text.

        Special case for :class:`ContentSafetyError`: the input gate fires
        BEFORE PLAN_START, so ``_open_steps`` is empty and a raw
        ``"❌ ContentSafetyError: ..."`` reads as a crash rather than a
        policy decision. Detect the type and render a friendly message
        with the flagged categories + severity, matching the same
        register as the output-gate redaction notice from
        :mod:`framework.agents.base`.
        """
        if isinstance(error, ContentSafetyError):
            await self._render_content_safety_block(error)
            return

        error_label = f"{type(error).__name__}: {error}"
        for key, step in list(self._open_steps.items()):
            try:
                step.is_error = True
                step.name = (
                    f"FAILED: {step.name}" if not step.name.startswith("FAILED:") else step.name
                )
                step.output = error_label
                await step.update()
            except Exception:
                logger.exception("ChainlitSink could not mark open step %s as failed", key)
        self._open_steps.clear()
        try:
            await self._cl.Message(content=f"❌ **{error_label}**").send()
        except Exception:
            logger.exception("ChainlitSink could not post the top-level error message")

    async def _render_content_safety_block(self, error: ContentSafetyError) -> None:
        """Friendly UI for a Content-Safety-blocked input.

        The block fires before PLAN_START so there are no open steps to
        mark; the user just sees a single ``cl.Message`` explaining what
        was flagged and how to recover. Wording stays in the same
        register as the output-gate redaction notice (agent-voice,
        actionable) so the input + output gate UX is consistent.
        """
        cats = ", ".join(c.value for c in error.blocking_categories) or "<unknown>"
        message = (
            f"⚠️ I can't process that — your message was flagged by safety "
            f"filters. Categories: **{cats}** (severity={error.severity.name}). "
            "Please rephrase and try again."
        )
        # Self-contained — no open steps to mark (input gate fires before
        # PLAN_START). If a future caller raises ContentSafetyError mid-
        # run (output gate doesn't raise, but a custom subclass might),
        # we still clear any open steps defensively.
        for key, step in list(self._open_steps.items()):
            try:
                step.is_error = True
                step.output = f"Content Safety block: {cats} ({error.severity.name})"
                await step.update()
            except Exception:
                logger.exception(
                    "ChainlitSink could not mark open step %s as Content-Safety-blocked", key
                )
        self._open_steps.clear()
        try:
            await self._cl.Message(content=message).send()
        except Exception:
            logger.exception("ChainlitSink could not post the Content-Safety-block message")

    # ----- helpers -----

    @staticmethod
    def _tool_result_summary(shop: str, result: dict[str, Any]) -> str:
        """Build a concise step-name summary for a tool result."""
        purchased = result.get("purchased", []) if isinstance(result, dict) else []
        oos = result.get("out_of_stock", []) if isinstance(result, dict) else []
        rationed = result.get("rationed", []) if isinstance(result, dict) else []
        bought_qty = sum(
            int(line.get("quantity", 0)) for line in purchased if isinstance(line, dict)
        )
        parts: list[str] = []
        if bought_qty:
            parts.append(f"{bought_qty} bought")
        if oos:
            parts.append(f"{len(oos)} OOS")
        if rationed:
            parts.append(f"{len(rationed)} rationed")
        if not parts:
            parts.append("no items")
        return f"{shop}: {', '.join(parts)}"


def _pretty_json(value: Any) -> str:
    """JSON-serialize ``value`` for step bodies, falling back to ``str()``."""
    try:
        return json.dumps(value, indent=2, default=str)
    except (TypeError, ValueError):
        return str(value)
