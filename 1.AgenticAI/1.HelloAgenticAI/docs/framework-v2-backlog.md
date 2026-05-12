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
