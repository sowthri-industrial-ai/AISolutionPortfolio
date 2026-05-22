"""Run the canonical fruit-market eval cases against live Azure resources.

Phase 5c Batch 5 — the CI consumer of the data-plane RBAC granted to the
OIDC service principal in Batch 4. Loads the cases from
``demo_fruitmarket/eval/cases.json``, constructs the real
:class:`FruitMarketAgent` via
:func:`build_fruit_market_context_from_endpoints`, runs them through
:class:`framework.eval.harness.EvalHarness`, writes a markdown summary
(``eval-results.md`` in CWD, picked up by the workflow's PR-comment step),
and exits non-zero if pass rate is below the PROJECT_PLAN.md Phase 5
acceptance threshold (90%).

Run locally::

    cd 1.AgenticAI/1.HelloAgenticAI
    uv run python scripts/run_evals.py

In CI: ``.github/workflows/evals.yml`` invokes this same entrypoint per PR.

Import strategy — this script lives in the HelloAgenticAI lane's
``scripts/`` directory but imports the lane's packages (:mod:`framework`,
:mod:`demo_fruitmarket`). ``uv sync`` installs both as importable packages
(``[tool.hatch.build.targets.wheel] packages = ["framework",
"demo_fruitmarket"]`` in ``pyproject.toml``), so the imports resolve from
the venv regardless of cwd. The runner is invoked by file path
(``uv run python scripts/run_evals.py``) — no ``-m``, no PYTHONPATH
munging, no ``__init__.py`` in ``scripts/``. ``cases.json`` is located
relative to the installed :mod:`demo_fruitmarket` package, so it is found
no matter where the runner is invoked from.

Endpoint URIs are read from environment variables and are NON-secret:

* ``AZURE_OPENAI_ENDPOINT``   — required (chat + judge)
* ``AZURE_COSMOS_ENDPOINT``   — required (memory + trace persistence)
* ``AZURE_CONTENT_SAFETY_ENDPOINT`` — optional. If unset, the agent runs
  without an input gate (Phase 4 fail-open semantics) and the
  ``guardrail-block-*`` case in ``cases.json`` will FAIL — the
  guardrail-block expectation requires Content Safety to be wired.

Authentication is :class:`azure.identity.aio.DefaultAzureCredential`:
federated identity in CI (set up by ``azure/login``), ``az login``
locally. The SP must hold the 5 data-plane roles from Phase 5c Batch 4
(see ``docs/setup-oidc.md`` "Phase 5c — eval data-plane grant (AUTHORIZED)").
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import demo_fruitmarket
from demo_fruitmarket.graph import build_fruit_market_context_from_endpoints
from framework.eval.harness import EvalCase, EvalHarness, EvalResult

PASS_THRESHOLD = 0.90  # PROJECT_PLAN.md Phase 5 acceptance criterion

# cases.json is data inside the demo_fruitmarket package — locate it via the
# installed package's path rather than a relative traversal from scripts/.
# `__file__` on a module object is typed `str | None`; a regular package
# always has it set — the assert narrows the type for mypy and records why.
_pkg_file = demo_fruitmarket.__file__
assert _pkg_file is not None
_CASES_PATH = Path(_pkg_file).resolve().parent / "eval" / "cases.json"
_RESULTS_MD_PATH = Path("eval-results.md")


def _require_env(name: str) -> str:
    """Return env var ``name`` or exit 2 with a clear error."""
    value = os.environ.get(name, "").strip()
    if not value:
        sys.stderr.write(
            f"error: required env var {name} is not set. "
            "In CI this comes from a GitHub repo Variable; "
            "locally from `azd env get-values`.\n"
        )
        sys.exit(2)
    return value


def _truncate(text: str, limit: int = 120) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _render_results_markdown(
    results: list[EvalResult],
    pass_rate: float,
    threshold: float,
) -> str:
    passed_count = sum(1 for r in results if r.passed)
    total = len(results)
    status_emoji = "✅" if pass_rate >= threshold else "❌"
    status_word = "PASS" if pass_rate >= threshold else "FAIL"
    lines = [
        f"## {status_emoji} {status_word} — Phase 5c evals: "
        f"{pass_rate:.0%} pass rate ({passed_count}/{total})",
        "",
        f"Threshold: ≥ {threshold:.0%} (PROJECT_PLAN.md Phase 5 acceptance).",
        "",
        "| Case | Mode | Result | Duration | Reasoning |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        if r.passed:
            marker = "✅ pass"
        elif r.error is not None:
            marker = "⚠️ error"
        else:
            marker = "❌ fail"
        if r.error is not None:
            reasoning = f"`{_truncate(r.error)}`"
        else:
            reasoning = _truncate(r.reasoning or "—")
        lines.append(
            f"| `{r.case_name}` | `{r.scoring_mode.value}` "
            f"| {marker} | {r.duration_ms} ms | {reasoning} |"
        )
    lines.append("")
    lines.append(
        "Sources: `demo_fruitmarket/eval/cases.json` · "
        "`framework/eval/harness.py` (scoring) · ADR-0006 (privilege design)."
    )
    return "\n".join(lines) + "\n"


async def _main() -> int:
    aoai_endpoint = _require_env("AZURE_OPENAI_ENDPOINT")
    cosmos_endpoint = _require_env("AZURE_COSMOS_ENDPOINT")
    # CONTENT_SAFETY / APPI / KV endpoints are intentionally optional —
    # build_fruit_market_context_from_endpoints fails open. The
    # guardrail-block case only fires end-to-end when
    # AZURE_CONTENT_SAFETY_ENDPOINT is set; without it, that one case
    # will fail (no input gate to block the prompt).

    cases: list[EvalCase] = EvalHarness.load_cases(_CASES_PATH)

    async with build_fruit_market_context_from_endpoints(
        aoai_endpoint=aoai_endpoint,
        cosmos_endpoint=cosmos_endpoint,
    ) as ctx:
        # ctx.llm reused as the LLM-judge client — same AOAI auth + deployments.
        harness = EvalHarness(agent=ctx.agent, llm_judge=ctx.llm)
        results = await harness.run_cases(cases)

    pass_rate = EvalHarness.pass_rate(results)
    markdown = _render_results_markdown(results, pass_rate, PASS_THRESHOLD)
    _RESULTS_MD_PATH.write_text(markdown, encoding="utf-8")
    print(markdown)

    if pass_rate < PASS_THRESHOLD:
        sys.stderr.write(
            f"\nFAIL: pass rate {pass_rate:.1%} below the " f"{PASS_THRESHOLD:.0%} threshold.\n"
        )
        return 1
    return 0


def main() -> None:
    """Console entrypoint — ``uv run python scripts/run_evals.py``."""
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
