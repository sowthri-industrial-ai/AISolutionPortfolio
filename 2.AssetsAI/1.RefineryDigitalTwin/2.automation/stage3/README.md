# Stage 3 — FastAPI REST API

HTTP access to live and historical DWSIM snapshots from the Stage 2 JSONL
stream, plus the F2 ontology surface and the F3 perturbation + advisory
write paths. Same data source as Stage 5 (Event Hubs producer) — both tail
the same `4.snapshots/stage2/stream_*.jsonl` files. No DWSIM connection
inside Stage 3 itself; writes are queued to the Stage 2 streamer via an
atomic per-file inbox.

> **F3 close-out status (commits C3–C6):** perturbation infra + advisory
> queue + MCP server + LangGraph agent all landed and verified.
> Regression suite (`../f3/test_f3_regression.py`, 28 tests) green.
> OpenAPI spec regenerated (17 operations). Surface is now read **+
> bounded write** — the historical "read-only" framing below the F1
> section no longer holds; see the F3 section.

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
| `SETPOINT_DICT_PATH` | `3.probes/phase0a/phase0a_setpoint_dictionary.json` | F3 setpoint catalog (bounds + perturbable flags) |
| `PERTURBATION_INBOX` | `2.automation/stage2/perturbations_inbox/` | F3 per-file inbox Stage 2 drains each cycle |
| `ADVISORY_STORE_PATH` | `2.automation/stage3/advisories.json` | F3 advisory store (JSON, survives restart) |
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
| `GET` | `/ontology/schema` | F2 ontology JSON schema |
| `GET` | `/ontology/entities` | All ontology entities |
| `GET` | `/ontology/entities/{entity_id}` | One entity + inbound relationships + tag_ids |
| `GET` | `/ontology/tags/{tag_id}` | Ontology view of one tag |
| `GET` | `/ontology/resolve?term=...` | Fuzzy entity resolver (NL term → entities) |
| `POST` | `/setpoints/{setpoint_id}/value` | **F3** queue a bounded perturbation (see F3 section) |
| `POST` | `/advisories` | **F3** create a pending advisory |
| `GET` | `/advisories?state=pending\|approved\|rejected` | **F3** list advisories (newest-first) |
| `POST` | `/advisories/{advisory_id}/approve` | **F3** approve → enqueues perturbation |
| `POST` | `/advisories/{advisory_id}/reject` | **F3** reject → no perturbation |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/redoc` | ReDoc UI |
| `GET` | `/openapi.json` | OpenAPI 3.1 spec (JSON; YAML committed at `docs/api/openapi.yaml`, 17 operations) |

Historical endpoints decompress closed `*.jsonl.gz` on demand; hour-bucket
pruning skips files whose entire hour is outside the requested range.

## F3 — perturbation + advisory

Stage 3 owns the write surface; Stage 2 owns DWSIM. Writes never touch
DWSIM directly — they are validated, then queued to a per-file inbox that
the Stage 2 streamer drains at each solve-cycle boundary (atomic
tmp+rename in both directions, crash-safe).

**Validation gate** (`SetpointCatalog.validate_write`, F3 Q3 default b):

1. `404` if `setpoint_id` is unknown
2. `422` if the setpoint is non-perturbable — either Phase 0a never
   marked it perturbable, or it is in `NON_PERTURBABLE_OVERRIDES`
   (catalog-level filter for entries DWSIM resets internally each cycle;
   currently `Recycle.MaximumIterations` — the entry stays readable but
   rejects writes with the documented reason)
3. `422` if the value is out of `bounds.low / bounds.high`
4. `422` if the value is non-numeric (bool / string / null)

**Direct write:** `POST /setpoints/{id}/value {"value": N}` → `200` with
`request_id`; inspect `<inbox>/<request_id>.applied|.failed` after ~1
cycle.

**Advisory mode:** `POST /advisories` creates a `pending` advisory.
`approve` enqueues the perturbation via the same inbox protocol and
stamps `perturbation_request_id`; `reject` closes it with no write.
Both are idempotent-guarded — a second resolve returns `409`. The
advisory store is JSON-persisted and survives restart.

The MCP server (`../f3/mcp_server.py`) and LangGraph agent
(`../f3/agent.py`) consume exactly these endpoints — see `../f3/README.md`.

## Error responses

| Status | Body | Cause |
|---|---|---|
| `404` | `{error: "tag_not_found", tag_id}` | Tag ID not in dictionary |
| `404` | `{error: "setpoint_not_found", setpoint_id}` | F3: setpoint ID not in catalog |
| `404` | `{error: "advisory_not_found", advisory_id}` | F3: unknown advisory |
| `422` | `{error: "bad_timestamp", hint}` | Malformed ISO 8601 |
| `422` | `{error: "since_after_until"}` | Range bounds inverted |
| `422` | `{error: "validation_failed", reason, perturbable, bounds, ...}` | F3: non-perturbable / out-of-bounds / non-numeric write |
| `409` | `{error: "...", advisory_id}` | F3: advisory already approved or rejected |
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

> Note: `export_openapi.py` is documented above with the `.venv-x86`
> interpreter (matches the Stage 2/DWSIM toolchain). Stage 3 is
> DWSIM-free, so the F3 venv works too:
> `../f3/.venv/bin/python export_openapi.py`. Either produces the same
> spec.

## Regression suite

F3 close-out regression lives at `../f3/test_f3_regression.py` (28 tests,
runs under the F3 Python 3.11 venv — Stage 3 is DWSIM-free and
`streamer.py` defers its `clr` imports, so both import cleanly there):

```bash
cd ../f3
.venv/bin/python -m pytest test_f3_regression.py -v
```

Covers: endpoint shape regression (incl. F2 ontology + F3 routes),
perturbation strategy dispatch (all four families + every-perturbable-
has-a-strategy cross-reference), advisory lifecycle (create → list →
reject, create → approve → inbox enqueue, double-resolve 409), and
`NON_PERTURBABLE_OVERRIDES` enforcement for `Recycle.MaximumIterations`.
The suite redirects the inbox + advisory store to a tempdir so it never
touches real runtime state.

## Anti-goals (demo-only)

- No authentication / authorization (local-only; bind to `127.0.0.1` if you
  want strict localhost confinement)
- No HTTPS / TLS
- No streaming response (cap 10 000 snapshots/request)
- Read path holds no persistent state — each request reads JSONL fresh
  (the F3 advisory store is the one deliberate exception: JSON-persisted,
  survives restart)

> Historical note: the original Stage 3 anti-goals listed "no setpoint
> write-back". F3 (commits C1–C6) intentionally reverses that with a
> validated, bounded, operator-gated write surface. The read path is
> unchanged.
