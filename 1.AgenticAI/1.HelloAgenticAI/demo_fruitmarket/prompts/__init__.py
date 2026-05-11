"""Loader for the four .md prompt files driving the FruitMarketAgent.

Prompts are .md text files (not Python) so a reviewer can read the agent's
"personality" without digging through Python — the agent's character is
literally readable in `prompts/*.md`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent

_VALID_PROMPT_NAMES: frozenset[str] = frozenset({"planner", "router", "reflector", "terminator"})


@lru_cache(maxsize=8)
def load_prompt(name: str) -> str:
    """Load and cache a prompt by name.

    ``name`` must be one of: ``planner``, ``router``, ``reflector``,
    ``terminator``. Returns the file's text content with leading / trailing
    whitespace stripped.
    """
    if name not in _VALID_PROMPT_NAMES:
        raise ValueError(f"unknown prompt {name!r}; expected one of {sorted(_VALID_PROMPT_NAMES)}")
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt file missing: {path}")
    return path.read_text(encoding="utf-8").strip()


__all__ = ["load_prompt"]
