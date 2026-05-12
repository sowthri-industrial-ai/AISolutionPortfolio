# Future UX Ideas — Richer Agent Visibility

Captured during Phase 3 live UI testing (May 11, 2026). Not committed
work; preserves design thinking for post-Phase-5 polish.

## Motivation

The current Chainlit UI renders each agent step inline in the conversation
(Planning → Calling shop → Reflecting → Done). This works for short runs
but has limitations:

- Chat scrolls as steps accumulate; the original goal scrolls out of view
  on longer runs (10+ steps).
- The conversation transcript and the agent's internal reasoning compete
  for the same visual real estate.
- Power users want to audit the full trace; casual users want a clean
  answer. The inline pattern serves neither well at scale.

## Three Visibility Patterns

### Pattern A — Inline expandable steps (current)

What we have. Each cl.Step renders inline with collapsible JSON.
Good for short demos, weak for longer runs.

### Pattern B — Side pane / agent activity panel

Two-column layout: conversation on left, dedicated agent-trace panel on
right. Industry-standard pattern — used by Claude.ai Research mode,
Cursor's agent, most polished agent products.

Side pane would contain:
- Live-updating timeline of every AgentEvent with timestamps and durations
- Expandable nodes for raw inputs/outputs (the JSON we already emit)
- Tool-call grouping (multiple calls to same tool collapse under one heading)
- Run-summary header that updates as work progresses
  (e.g., "3 shops queried, 4 items sourced, 1 unavailable, $12.50")
- "View prompt" links on planner/router/reflector steps that pop open
  the corresponding .md prompt file — proves the agent follows readable
  English rules, not magic
- Optional: thinking-stream view when model reasoning text is exposed
  separately from final answer

Why this is more "authentic":
- Main conversation stays clean — goal at top, answer at bottom,
  readable as a finished transcript
- The trace pane is evidence the answer was earned, not hallucinated
- Scales gracefully: 30-step runs are fine in a side pane, painful inline
- Serves both audiences (clean for casual, deep for curious) simultaneously

### Pattern C — Live system diagram

Graphical view of the agent architecture (planner, router, reflector,
tools as boxes) with arrows lighting up as data flows. Per-node metrics
(latency, tokens, cost). Maximum visual impact for executive demos.

Higher engineering effort. Langfuse's hosted UI renders a variant of
this for free once observability is wired (Phase 4 work).

## Implementation Paths for Pattern B

### Path 1 — Chainlit cl.Sidebar (lowest effort)

Write a ChainlitSidebarSink alongside the existing ChainlitSink. Stream
AgentEvents to Chainlit's built-in sidebar component. Keep inline steps
for the answer, sidebar for the trace. ~1 day of work. Limited styling
control — Chainlit's sidebar is functional, not polished.

### Path 2 — Custom React UI over WebSocket (medium effort)

Replace Chainlit entirely with a Next.js or Vite frontend. Python
backend (FastAPI + WebSockets) streams events to the frontend, which
renders the trace pane with full styling control. ~3-5 days.
Portfolio-grade result. Most polished agent products use this shape.

### Path 3 — Langfuse as a separate side pane (lowest effort, two windows)

Wire agent events to Langfuse Cloud (already in Phase 4 plan). For
demos, position Chainlit and Langfuse in side-by-side browser windows.
Zero new UI code. Downside: not a unified app — two windows, two URLs.

## Authenticity Content Rules (apply regardless of pattern)

- Show real LLM reasoning verbatim — don't paraphrase or polish what
  the planner/reflector wrote
- Show real latencies and costs (ms + tokens) per step
- Show failures and recoveries — partial fulfillment is more authentic
  than papered-over success
- Show the prompts — links from planner/router/reflector steps to the
  corresponding .md file

## When to Do This

NOT in Phase 3. NOT in Phase 4 (Phase 4 is observability + guardrails —
Langfuse + Content Safety + App Insights; wire those first; richer UX
comes after).

Earliest natural slot: post-Phase-5. After the portfolio site is live
and HelloAgenticAI's basic demo URL is shareable, this is the kind of
"v2 polish" that elevates a working demo into a flagship demo.

Possible Phase 6 framing: "Demo UX 2.0 — agent visibility upgrade across
the portfolio." Would apply to RefineryDigitalTwin and any future
project too, since the framework's AgentEventEmitter feeds any UI.

## Decision Heuristic

When picking a path post-Phase-5:
- Want fastest visible improvement → Path 3 (Langfuse, zero UI work)
- Want unified product feel with low effort → Path 1 (Chainlit sidebar)
- Want flagship portfolio piece → Path 2 (custom React, full control)
