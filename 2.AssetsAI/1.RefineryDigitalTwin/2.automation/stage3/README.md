# Stage 3 — FastAPI REST API

Read-only HTTP access to live and historical DWSIM snapshots from the Stage 2
JSONL stream. Same data source as Stage 5 (Event Hubs producer) — both tail the
same `4.snapshots/stage2/stream_*.jsonl` files. No DWSIM connection, no cloud,
no database.

## Setup (one-time)

```bash
cd 2.automation/stage3
arch -x86_64 ../.venv-x86/bin/pip install fastapi 'uvicorn[standard]' pyyaml
```

## Run

```bash
# Recommended: with --reload for dev (auto-reload on file edits)
arch -x86_64 ../.venv-x86/bin/uvicorn api:app --host 0.0.0.0 --port 8080 --reload

# Or via Python directly:
arch -x86_64 ../.venv-x86/bin/python api.py
```

## Config (env vars, all optional)

| Var | Default | Purpose |
|---|---|---|
| `TAG_DICT_PATH` | `3.probes/phase0a/phase0a_tag_dictionary.json` | 1550-entry tag dictionary, loaded once at startup |
| `STAGE2_DIR` | `4.snapshots/stage2/` | Where to find `stream_*.jsonl` and `*.jsonl.gz` |
| `HOST` | `0.0.0.0` | Bind host (use `127.0.0.1` for localhost-only) |
| `PORT` | `8080` | Bind port |

## Endpoints

| Method | Path | Returns |
|---|---|---|
| `GET` | `/healthz` | `{status, stage2_active, latest_cycle, active_file}` |
| `GET` | `/snapshots/latest` | Most recent snapshot, full Stage 2 schema |
| `GET` | `/snapshots/range?since=ISO&until=ISO&limit=1000` | Historical snapshots in range (max 10 000) |
| `GET` | `/tags` | Full 1550-entry tag dictionary |
| `GET` | `/tags/{tag_id}` | Single tag dictionary entry (404 if missing) |
| `GET` | `/tags/{tag_id}/value` | Latest value for one tag |
| `GET` | `/tags/{tag_id}/history?since=ISO&until=ISO&limit=1000` | Time series for one tag |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/redoc` | ReDoc UI |
| `GET` | `/openapi.json` | OpenAPI 3.0 spec (JSON; YAML committed at `docs/api/openapi.yaml`) |

Historical endpoints decompress closed `*.jsonl.gz` on demand; hour-bucket
pruning skips files whose entire hour is outside the requested range.

## Error responses

| Status | Body | Cause |
|---|---|---|
| `404` | `{error: "tag_not_found", tag_id}` | Tag ID not in dictionary |
| `422` | `{error: "bad_timestamp", hint}` | Malformed ISO 8601 |
| `422` | `{error: "since_after_until"}` | Range bounds inverted |
| `503` | `{error: "streamer_not_running"}` | No active hour file (Stage 2 not running) |
| `503` | `{error: "no_snapshots_in_active_file"}` | Active file exists but has no parseable lines |

## Smoke tests

```bash
# Liveness
curl -s http://localhost:8080/healthz | jq

# Latest snapshot
curl -s http://localhost:8080/snapshots/latest | jq '{cycle, solved, tag_count}'

# Latest condenser duty (Phase 0a ground truth ~29755.28 kW)
curl -s http://localhost:8080/snapshots/latest \
  | jq '.tags["ES-CONDENSER_DUTY.EnergyFlow"]'

# Tag dictionary count (expect 1550)
curl -s http://localhost:8080/tags | jq 'length'

# One tag's dictionary entry
curl -s http://localhost:8080/tags/MS-OIL.OVERALL.PROP_MS_0 | jq

# One tag's latest value
curl -s http://localhost:8080/tags/MS-OIL.OVERALL.PROP_MS_0/value | jq

# Time series for one tag over the past day
SINCE=$(date -u -v-1d +"%Y-%m-%dT%H:%M:%SZ")
UNTIL=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
curl -s "http://localhost:8080/tags/MS-OIL.OVERALL.PROP_MS_0/history?since=${SINCE}&until=${UNTIL}&limit=100" \
  | jq '{count, first: .points[0], last: .points[-1]}'

# Range of snapshots (limit 10)
curl -s "http://localhost:8080/snapshots/range?since=${SINCE}&until=${UNTIL}&limit=10" \
  | jq '{count, truncated}'
```

## Regenerate OpenAPI spec

After any code change that affects endpoints, request params, or response
schemas, regenerate the committed YAML:

```bash
arch -x86_64 ../.venv-x86/bin/python export_openapi.py
git add ../../docs/api/openapi.yaml
git commit -m "docs(api): regenerate openapi spec"
```

The auto-regen is **not** wired into pre-commit on purpose — keeping it manual
prevents parallel Claude sessions from fighting over the file.

## Anti-goals (read-only, demo-only)

- No authentication / authorization (local-only; bind to `127.0.0.1` if you
  want strict localhost confinement)
- No HTTPS / TLS
- No setpoint write-back — Stage 3 only reads JSONL
- No streaming response (cap 10 000 snapshots/request)
- No persistent state — each request reads JSONL fresh
