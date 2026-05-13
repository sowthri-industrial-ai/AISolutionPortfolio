# Framework v2 backlog

Structural improvements to the `framework/` package surfaced during
phase work but **deferred** to a future framework refactor (call it v2)
so phases stay shippable without churning the framework's public API.

This is not a wishlist or a TODO list — every entry here is a real gap
with a concrete workaround in production code today, plus a sketch of
the v2 fix and what it unblocks.

Format per entry: **Surfaced in** (which phase noticed it) · **Severity**
(does it break anything today, or just smell?) · **Workaround in tree**
(file + technique) · **v2 fix sketch** · **What it unblocks**.

---

## Per-call Content Safety SDK transport retry policy

**Surfaced in:** Phase 4 Batch 2 design discussion.

**Severity:** Low — only relevant under sustained Content Safety
throttling, which we don't expect in the demo. Today's
``ContentSafetyClient`` behaviour (per-call ALLOW + warn on transient
SDK failure, instance stays armed for next call) is correct in
isolation.

**Workaround in tree:** None needed. Per-call failures fail open,
which is the deliberate safety/availability trade-off.

**v2 fix sketch:** Configure ``azure-core``'s transport-level retry
policy on the underlying ``azure.ai.contentsafety.aio.ContentSafetyClient``
— exponential backoff on 429/503 with 2-3 retries before falling
through to the ALLOW-and-warn path. ``ContentSafetyClient(retry_policy=
RetryPolicy(retry_total=3, ...))`` is the documented API. Adds
latency under throttle but reduces false-negative ALLOWs.

**What it unblocks:** Higher-fidelity guardrails under sustained load
(e.g. a public demo URL traffic spike). Today's fail-open is fine for
the portfolio demo; production usage of the framework would want this.

**Migration path:** ~5 lines in ``ContentSafetyClient._ensure_client``:
construct ``RetryPolicy`` from kwargs, pass to the SDK constructor. No
public-API change.

---

## Per-gate Content Safety threshold configuration

**Surfaced in:** Phase 4 Batch 3 design discussion.

**Severity:** Low — both gates currently use the same default
threshold (``Severity.MEDIUM``) and the demo doesn't need different
policies for input vs output.

**Workaround in tree:** Per-deployment can override via ``.is_blocked(
threshold=...)`` on the result, but that's a caller-side workaround,
not a framework-supported configuration.

**v2 fix sketch:** ``AgentBase.__init__`` gains
``content_safety_input_threshold: Severity = Severity.MEDIUM`` and
``content_safety_output_threshold: Severity = Severity.MEDIUM`` as
separate keyword-only params. ``_enforce_input_gate`` and
``_enforce_output_gate`` use the respective threshold when calling
``result.is_blocked()``. Backward compatible — defaults match today.

**What it unblocks:** Asymmetric policy. Useful when input policy
should be stricter than output policy (users can rephrase input;
the model's output is final and rephrase isn't an option). Or vice
versa for highly-regulated outputs.

**Migration path:** ~10 lines on ``AgentBase``, no caller changes
unless they want non-default thresholds. Add one test per non-default
threshold case in ``framework/agents/test_base.py``.

---

## Cross-service distributed tracing via *_START/*_COMPLETE span pairing

**Surfaced in:** Phase 4 Batch 4 design discussion (events-as-spans
decision in ``AppInsightsSink``).

**Severity:** Low — single-Container-App today; the agent doesn't
call external services that would benefit from distributed-trace
propagation.

**Workaround in tree:** None needed. ``AppInsightsSink`` and
``LangfuseSink`` both emit short-lived spans whose real duration is
in the ``duration_ms`` attribute — sufficient for the workbook's
latency charts.

**v2 fix sketch:** ``AppInsightsSink`` (and ``LangfuseSink``) keep
``Span`` objects alive across ``*_START`` and ``*_COMPLETE`` event
pairs, indexed by ``(session_id, node)``. Start spans on ``PLAN_START``
/ ``TOOL_CALL``, end them on ``PLAN_COMPLETE`` / ``TOOL_RESULT`` with
the AgentEvent's ``timestamp``. This lets the agent's plan / tool /
reflect spans participate in the distributed trace of the Container
App's incoming HTTP request, so App Insights' transaction view shows
the full request → agent → tool → response chain. Requires
``AgentEventEmitter`` to surface "start with parent context" + "end
by reference" semantics if we want trace context propagation
automatically. May also benefit from W3C Trace Context (``traceparent``
header) propagation if the agent starts calling external services
through identifiable RPC.

**What it unblocks:** Distributed-tracing UI in Azure Portal. Real
value when we have agents-calling-agents, or agents calling external
services through identifiable RPC. Also makes the App Insights
workbook's latency breakdown more accurate (span duration becomes
authoritative instead of an attribute readback).

**Migration path:** Bigger — requires rethinking ``EventSink`` to
support span lifecycle, not just point-in-time emit. Best done
alongside a broader v2 framework refactor.

---

## LangfuseSink: per-session memory cleanup + concurrent same-tool spans

**Surfaced in:** Phase 4 Batch 5 design (in-memory ``_traces`` /
``_open_spans`` dicts).

**Severity:** Low. Two related issues, both bounded:

* **Memory leak on un-COMPLETE'd sessions.** ``_traces`` grows per
  session and only drops entries on ``COMPLETE``. A session that
  crashes mid-run (no COMPLETE) leaks until process restart. For
  Chainlit-style short sessions this is harmless (container restarts
  daily; entries are tiny). For a long-running daemon, the dict
  could accumulate over months.
* **Concurrent same-tool span collision.** ``_open_spans`` is keyed
  by ``(session_id, f"tool:{node}")``. Two concurrent ``TOOL_CALL``s
  on the same node within one session would both write to the same
  key, losing the first span reference. Doesn't happen today (the
  agent loop is strictly sequential per session), but a future
  parallel-tool agent would hit this.

**Workaround in tree:** None needed for the demo. The bounded
lifetime (Chainlit chat sessions, sequential tool calls) makes both
issues theoretical for v1.

**v2 fix sketch:** TTL-based cleanup — keep a ``last_seen_at``
timestamp per session entry, sweep entries older than N minutes on
each emit (or via a periodic background task). For the span
collision, key ``_open_spans`` by ``(session_id, span_id_from_event)``
instead of ``(session_id, node)`` — requires AgentBase to assign a
unique span id at ``*_START`` time and carry it through to the
matching ``*_COMPLETE`` event. The Langfuse SDK already supports
arbitrary span ids; we'd need ``AgentEvent`` to carry one.

**What it unblocks:** Long-running daemon agents without sink memory
growth; parallel-tool agents that fan out to multiple shops at once.

**Migration path:** TTL cleanup is ~20 lines in ``LangfuseSink`` (and
the same pattern in ``AppInsightsSink`` once distributed tracing
lands, see entry above). Concurrent-tool keying is a wider change
that needs ``AgentEvent.span_id: str | None`` and AgentBase wiring.

---

## Surface Langfuse SDK auth failures synchronously at init

**Surfaced in:** Phase 4 Batch 8 — `LangfuseSink` reported "init succeeded" (no warning logs from our wrapper) but Langfuse Cloud rejected every subsequent trace POST with 401 (the KV-stored API keys had literal angle brackets wrapping the values, a user-side data-entry error). The failure was completely invisible to our wrapper because Langfuse Python SDK's 401 errors fire in a background thread (the SDK queues spans + flushes asynchronously) and don't propagate to our `try/except` around the constructor or per-emit code paths.

**Severity:** Medium — lazy-init's fail-open is the right policy at the framework level (agent must not crash on observability misconfiguration), but **"client construction succeeded" should imply "client can actually authenticate."** Today's contract violates that implication for Langfuse specifically. We discovered the auth failure only by clicking the trace URL in Chainlit and seeing "Trace not found" — which is exactly the kind of silent-failure-then-user-discovery loop the lazy-init pattern was supposed to prevent.

**Workaround in tree:** None today. Diagnose by:
1. Clicking the trace URL in Chainlit
2. Seeing "Trace not found"
3. Inspecting the KV-stored secrets manually to verify the values are well-formed
4. (Optional) Running a one-shot `langfuse.auth_check()` from a local Python REPL with the same keys

This is too many manual steps for a production demo URL. We need a startup-time signal.

**v2 fix sketch:** After `Langfuse(public_key=..., secret_key=..., host=...)` constructor returns, call `langfuse.auth_check()` synchronously inside `_ensure_client()` and before the lock is released. If it raises or returns `False`, mark the sink failed at init time so:

* The `is_armed` property correctly returns `False`.
* Chainlit's "🔗 View full trace in Langfuse" link is suppressed (currently it renders unconditionally if `LANGFUSE_HOST` is set, which is misleading when auth has failed).
* The container log contains a clear warning at startup, before any user clicks a broken link.

Verify the actual SDK method name — Langfuse v2.60.10 exposes a sync `auth_check()` (per the SDK signature we inspected during Batch 5); v3 may have renamed it. Pin the version check.

**Alternative (broader):** Surface SDK background-thread errors via a polling collector — hook into the Langfuse SDK's internal logger and re-emit any 401/403 at our wrapper's WARNING level. Same effect, more general (catches transient auth failures post-init too), but more intrusive.

**What it unblocks:** Bad credentials surface at deploy/restart time, not at "user clicked the trace link and got Trace-not-found". Halves the diagnose-loop for the most common Langfuse configuration mistake (typo, copy-paste error, stale rotation).

**Migration path:** ~5 lines in `LangfuseSink._ensure_client()`. Plus 1 new test for the auth-check-fails-at-init path (mock the SDK's `auth_check()` to return `False`, verify `_init_failed` becomes `True`, verify the same `events will be silently dropped` warning fires). Plus a Chainlit-side update to gate the trace link on `langfuse_sink.is_armed` instead of just `langfuse_host` being set — but that requires plumbing the sink reference into the Chainlit app, which is a slightly bigger touch.

---

## Cost-trend workbook chart + token usage emission

**Surfaced in:** Phase 4 Batch 7 — workbook deliverable scope.

**Severity:** Low — not load-bearing for the "observable agent"
framing; the four charts that shipped in Batch 7 (events-per-minute,
plan-to-complete latency p50/p95, top schema-validation failures,
top guardrail blocks) cover the operational questions a portfolio
demo viewer would actually ask.

**Workaround in tree:** The workbook section for cost trend is in
place as a placeholder markdown item (see
``infra/workbooks/agent-observability.workbook.json``, ``name:
cost-trend-placeholder``). The shape is ready to receive the data
source once it ships; no further workbook-layout work needed.

**v2 fix sketch:**

* ~10 lines in :mod:`framework.llm.azure_openai` to track
  ``_last_usage`` as a property after each ``.parse()`` /
  ``.create()`` call, exposing
  ``{prompt_tokens, completion_tokens, total_tokens}``.
* ~20 lines in :mod:`framework.agents.base` to add a
  ``_get_last_llm_usage()`` hook method (default returns ``None``)
  called from the three emit sites (``_plan_node``, ``_tool_node``,
  ``_reflect_node``) and conditionally merged into the event payload
  under ``payload.usage``.
* ~3 lines in :class:`FruitMarketAgent` to override the hook and
  return ``self._llm.last_usage``.
* ~5-7 new tests covering: hook returning usage, hook returning
  None, usage merged into the right event types, absent-usage case
  (back-compat for subclasses that don't override).
* Workbook KQL: a token-sum-per-session timechart joining
  ``payload.usage.total_tokens`` across the events for each session,
  binned by hour. ~10 lines of KQL replacing the placeholder
  markdown item.
* One re-provision pass to land the updated workbook JSON
  (Bicep itself unchanged — ``loadTextContent`` picks up the new
  file).

**What it unblocks:** Real cost visibility for demo runs. Useful
when actual usage numbers become a question (e.g., "how much did
the demo run yesterday cost?", "which prompt is burning the most
tokens?", "is the gpt-4o vs gpt-4o-mini split delivering the
expected cost ratio?"). Also feeds Phase 5's eval-scoring needs
(token-cost-per-correct-answer is a useful metric).

**Migration path:** ~45-60 min of cross-cutting plumbing + one
workbook re-deploy. Best landed alongside Phase 5's eval harness —
which independently needs per-event token counts for scoring, so
the underlying wiring is shared and the integration cost amortises
across two deliverables.

---

## Cherry variant SKU not always picked by planner

**Surfaced in:** Phase 3 live smoke test on the deployed URL — *"Find
peaches and cherries, prefer local"* caused the planner to emit a bare
`cherry` SKU instead of `cherry_bing` or `cherry_rainier`.
`stone_fruit_stand` returned OOS for the unknown SKU, single iteration,
half-fulfilled basket.

**Severity:** Medium — directly affects a documented demo prompt (#4 in
README). Same bug class as the pear fix already landed in Phase 3; the
existing variant-selection rule in `planner.md` is not strong enough to
prevent the planner from picking the bare base name when variants exist.

**Workaround in tree:** None — manually use a variant-suffixed form in
the prompt (e.g. `cherry_bing` instead of `cherries`) to avoid.

**v2 fix sketch:** Strengthen `planner.md`'s variant rule from passive
("use snake_case + variant suffix") to directive: *"when a user says a
plural/generic name like cherries, apples, pears, mangoes, oranges,
ALWAYS pick one specific variant from the available SKU list — never
emit a bare base name when variants exist."* Add one example per variant
base. Extend `test_sku_alignment.py` with a regex check for the
directive phrasing so future prompt edits don't silently weaken it.

**What it unblocks:** All five documented demo prompts working reliably
on first try, every time. Reduces "it works for me on the seventh
re-roll" feel that erodes confidence in agent demos.

**Migration path:** Prompt edit + test extension + new image deploy via
`azd deploy`. ~30 min.

---

## Planner needs an out-of-scope / negation policy

**Surfaced in:** Phase 3 live smoke test — *"I don't want fruits"*

**Severity:** Medium — agent terminates gracefully but produces a
confusingly synthetic basket (hallucinated `no_fruit` SKU) and an
awkward "not available" answer for an input that's actually
out-of-scope. Important for a public portfolio demo where anyone can
type anything.

**Workaround in tree:** None — current `planner.md` treats every input
as a valid shopping goal, with no escape hatch for off-topic / negated /
adversarial inputs.

**v2 fix sketch:** Add an explicit policy to `planner.md`:

- If the goal is not a shopping request (e.g. *"tell me a joke"*, *"I
  don't want X"*, *"what's the weather"*), emit a special
  `FruitMarketPlan` with `items=[]` and
  `reasoning="<why this is out of scope>"`.
- The reflector treats empty-items plans as immediately done with a
  polite refusal answer (e.g. *"I'm a fruit-market agent — I can help
  you source fruit but that's not something I can do."*).
- For ambiguous-but-on-topic inputs (*"something sweet"*, *"fruits for
  a party"*), planner emits a normal plan but flags assumptions in the
  `reasoning` field, which the answer surfaces.

**What it unblocks:** Demo robustness against adversarial or off-topic
inputs without papering over them. Important for a public portfolio
demo where anyone can type anything.

**Migration path:** `planner.md` edit + empty-items handling in the
reflector + 2-3 unit tests for the refusal flow + new image deploy.
~1-2 hours.

---

## 1. `AgentBase._reflect` should receive `goal` and `plan`, not just `history`

**Surfaced in:** Phase 3 (FruitMarketAgent's reflector needed both the
original natural-language goal and the structured plan to write a useful
final answer; `_reflect` was given only `history`).

**Severity:** medium. Works today via per-instance state stashing, but
the workaround is **unsafe for concurrent runs of the same agent
instance**. Phase 3's Chainlit app sidesteps the unsafety by creating a
new agent per chat session — so it's safe in practice for v1, but a
landmine for any future caller that reuses an agent instance across
runs (e.g. a long-running daemon, a batch eval that parallel-runs the
same agent over many prompts).

**Workaround in tree:** `demo_fruitmarket/agent.py` — `_plan` stashes
the goal + plan on `self._current_goal` / `self._current_plan`;
`_reflect` reads them. Documented at the top of the module.

**v2 fix sketch:** extend `AgentBase._reflect_node` (in
`framework/agents/base.py`) to pass the relevant slices of `AgentState`
to `_reflect`:

```python
async def _reflect(
    self,
    *,
    goal: str,
    plan: Any,
    history: list[HistoryEntry],
) -> ReflectionDecision:
    ...
```

Mechanically: `_reflect_node` already has `state["goal"]` and
`state["plan"]` in scope; just pass them. Same change applies to
`_route` (which currently gets `plan` but not `goal` — Phase 3's router
also benefits from seeing the original prompt).

**What it unblocks:** safe concurrent runs of the same agent instance
(daemons, parallel eval); cleaner subclass code (no instance-state
ceremony); removes the entire "documented framework limitation" call-out
in `demo_fruitmarket/agent.py`.

**Migration path:** add the new keyword-only parameters with sensible
defaults so existing subclasses keep compiling, then deprecate the
zero-context form in v2.1.

---

## Real /health route for Chainlit container probes

**Surfaced in:** Phase 3

**Severity:** Low — works today via TCP probes, but liveness != readiness.
A wedged Python process that's still holding the port open looks healthy
to TCP probes but can't actually serve users.

**Workaround in tree:** `infra/modules/container-app.bicep` — probes use
`tcpSocket` on port 8000 instead of `httpGet /health`.

**v2 fix sketch:** Register a FastAPI route alongside Chainlit's server
(Chainlit exposes `app.server.fastapi`) that returns 200 only if it can:
(a) get a token via `DefaultAzureCredential` for both AOAI and Cosmos
scopes, (b) ping AOAI deployments list, (c) ping Cosmos account read.
Switch `container-app.bicep` probes back to `httpGet /health`. Probably
30 lines of code + a Bicep flip.

**What it unblocks:** Real liveness AND readiness signal. Catches
credential expiry, network partitions, AOAI/Cosmos downtime — not just
process death.

**Migration path:** Add `/health` route → deploy + verify it returns 200
from inside the container's network → flip Bicep probes back to
`httpGet` → next `azd up`. Safe rollback (TCP probes work either way).

---

*This file lives at `docs/framework-v2-backlog.md`. Add new entries above
this line, oldest at the bottom.*
