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

*This file lives at `docs/framework-v2-backlog.md`. Add new entries above
this line, oldest at the bottom.*
