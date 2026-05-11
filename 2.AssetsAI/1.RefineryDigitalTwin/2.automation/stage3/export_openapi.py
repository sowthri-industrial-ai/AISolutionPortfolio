#!/usr/bin/env python3
"""Export api.py's OpenAPI 3.0 spec to docs/api/openapi.yaml.

Run after any change that affects endpoints, request/response schemas,
or models:

    arch -x86_64 ../.venv-x86/bin/python export_openapi.py
    git add ../../docs/api/openapi.yaml
    git commit -m "docs(api): regenerate openapi spec"

No pre-commit hook fires this — keeping it manual so parallel Claude
sessions don't fight over auto-regenerated YAML.
"""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "PyYAML not installed in venv. Run:\n"
        "  arch -x86_64 ../.venv-x86/bin/pip install pyyaml\n"
    )
    sys.exit(1)

# Make `from api import app` work when run from this script's directory.
sys.path.insert(0, str(Path(__file__).parent.resolve()))
from api import app  # noqa: E402

# Resolve docs/api/openapi.yaml relative to this script (stage3/) → project root.
script_dir = Path(__file__).parent.resolve()
project_root = script_dir.parent.parent  # 2.automation/stage3/ → project root
out_path = project_root / "docs" / "api" / "openapi.yaml"
out_path.parent.mkdir(parents=True, exist_ok=True)

schema = app.openapi()
with open(out_path, "w", encoding="utf-8") as f:
    yaml.safe_dump(schema, f, sort_keys=False, allow_unicode=True)

print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
