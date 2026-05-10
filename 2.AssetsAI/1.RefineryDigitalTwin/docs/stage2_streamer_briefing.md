# Stage 2 Briefing — JSONL Streamer with Hourly Rotation

**Project:** Refinery Digital Twin · Feature 4 streaming foundation (production-style)
**Issued by:** Architect chat
**Implementer:** Claude Code
**Operator:** Sowthri
**Status:** Phase 1 foundation closed → this briefing
**Branch:** `phase-2-streaming` (per portfolio convention)
**Estimated effort:** ~1.5 hr Claude Code + ~30 min operator (verify rotation + retention)

---

## Goal

Harden the local streamer into a production-style streaming pipeline. Replace per-cycle JSON files with a single append-only JSONL stream that rotates hourly and retains the last 24 hours. Keep the cycle interval at 30 s (matching Stage 1) for solve-time headroom. This is the *base* the future cloud-side ingestion (Feature 1 Eventstream + Eventhouse) will tail and consume.

Stage 2 does NOT add cloud, REST, OPC-UA, or setpoint write-back. Local-only, JSONL-only.

## Why this matters

After Stage 2 lands, the streamer behaves like a real industrial historian's local cache: one growing log file per hour, predictable disk usage, standard tooling support (`tail -f`, `jq`, log shippers, `pandas.read_json(lines=True)`). Downstream consumers — Stage 5 Event Hubs producer, Feature 1 Fabric ingestion — read JSONL natively. Cycle cadence stays at 30 s, same as Stage 1, preserving solve headroom and bounding disk growth.

## Inputs

| | Default | |
|---|---|---|
| Substrate path | (locked, hardcoded — same as Stage 1) | |
| Tag dictionary | `~/Documents/AISolutionPortfolio/2.AssetsAI/1.RefineryDigitalTwin/3.probes/phase0a/phase0a_tag_dictionary.json` | drives extraction |
| Output directory | `~/Documents/AISolutionPortfolio/2.AssetsAI/1.RefineryDigitalTwin/4.snapshots/stage2/` | created if missing |
| Cycle interval | 30 s | `--interval` flag, default 30 |
| Retention days | 1 | `--retention-days` flag, default 1 |
| Compression on rotation | gzip | always on; not configurable in Stage 2 |

## Required reading before code

1. `docs/DWSIM_KNOWLEDGE_BASE.md` — bug classes still apply
2. `docs/STREAMING_PLAN.md` — Part C, especially the multi-stage progression
3. `2.automation/stage1/streamer.py` — Stage 1 implementation; reuse extraction/solve logic
4. `docs/phase0a_findings.md` — override rules already in tag dictionary
5. This briefing — the contract

If anything contradicts the KB, the KB wins. Stop and flag.

## Toolchain

Same x86 venv as Phase 0a / Stage 1. Script lives at `2.automation/stage2/streamer.py`, run from there:

```
arch -x86_64 ../.venv-x86/bin/python streamer.py
```

No new dependencies. `gzip` and `pathlib` are stdlib.

## Project layout context

```
~/Documents/AISolutionPortfolio/2.AssetsAI/1.RefineryDigitalTwin/
├── docs/                            reference docs
├── 2.automation/
│   ├── .venv-x86/                   x86 Python venv (verified)
│   ├── phase0a/                     probe.py + post-processor (read-only)
│   ├── stage1/                      streamer.py (read-only — reference for extraction logic)
│   └── stage2/                      where you put the new streamer.py
├── 3.probes/phase0a/                Phase 0a artifacts (read-only inputs)
├── 4.snapshots/
│   ├── stage1/                      Stage 1 outputs (preserved as artifacts)
│   └── stage2/                      Stage 2 outputs (new)
├── infra/                           Bicep + azd from Phase 1 (do not touch)
└── .github/workflows/deploy.yml     Phase 1 (do not touch)
```

## Behavior

### 1. Bootstrap (same as Stage 1)
- DWSIM DLL refs; construct `Automation3()`
- Python-side log capture (KB §3 update)
- Load `phase0a_tag_dictionary.json`; sanity-check `len == 1550`
- Open `streamer.log` (append mode); write run config header

### 2. Initial solve verification (same as Stage 1)
- `LoadFlowsheet(substrate_path)` → `CalculateFlowsheet4(sim)` → assert `sim.Solved`
- Log initial solve duration

### 3. Open or create current hour's JSONL file (new in Stage 2)
- Compute `current_hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0)`
- Filename: `stream_{current_hour.strftime("%Y-%m-%dT%H")}.jsonl` (e.g., `stream_2026-05-10T03.jsonl`)
- Open in append mode (`"a"`) so restarts append rather than truncate
- Track `current_file_handle` and `current_hour` in module state

### 4. Retention sweep at startup (new)
- List files in output directory matching `stream_*.jsonl` and `stream_*.jsonl.gz`
- Parse hour from filename; compute age vs `now - retention_days`
- Delete any older than retention window
- Log: `Retention sweep: kept N files, deleted M files older than T hours`

### 5. Main loop (until Ctrl-C)

```
while not shutdown:
    t0 = time()
    try:
        sim_auto.CalculateFlowsheet4(sim)
        snapshot = build_snapshot(sim, tag_dict, cycle, t0)
    except Exception as e:
        snapshot = build_failure_snapshot(cycle, e)
        consecutive_failures += 1
    else:
        consecutive_failures = 0

    # Rotate if we've crossed an hour boundary
    new_hour = utcnow().replace(minute=0, second=0, microsecond=0)
    if new_hour != current_hour:
        rotate_file(current_file_handle, current_hour)  # close, gzip the closed file
        current_hour = new_hour
        current_file_handle = open(file_for_hour(new_hour), "a")
        retention_sweep()  # also run on rotation

    # Append snapshot as one JSONL line
    current_file_handle.write(json.dumps(snapshot, separators=(",",":")) + "\n")
    current_file_handle.flush()  # ensure tail -f sees it immediately

    log_cycle(cycle, snapshot)

    if consecutive_failures >= 3:
        log_fatal("3 consecutive cycle failures — exiting")
        sys.exit(2)

    sleep(max(0, interval - (time() - t0)))
    cycle += 1
```

### 6. Rotation behavior (new)
On hour boundary crossing:
- Close current file handle
- Spawn (or inline-do) a gzip on the closed `.jsonl` → produces `.jsonl.gz`, deletes the original `.jsonl`
- Open new file handle for the new hour (same naming convention)
- Run retention sweep (delete files older than retention window)
- Log: `Rotated to {new_filename}, archived {old_filename}.gz, retention sweep: kept N`

### 7. Graceful shutdown (same pattern as Stage 1)
- Trap SIGINT and SIGTERM; set `shutdown = True`
- Finish current cycle if mid-solve
- Close current file handle (do NOT gzip the in-flight hour — leave it as `.jsonl` since restarts append to it)
- Final log line: `Streamer stopped after N cycles ({duration}), {errors} errors`
- Exit 0

## Snapshot schema (unchanged from Stage 1)

Flat JSON, one snapshot per line in JSONL:

```json
{"timestamp":"2026-05-10T03:08:00.000Z","cycle":142,"solved":true,"solve_time_s":3.84,"cycle_duration_s":4.12,"tag_count":1550,"errors":[],"tags":{"MS-OIL.OVERALL.PROP_MS_0":350.0,"MS-OIL.OVERALL.PROP_MS_1":101325.0,"...":"..."}}
```

Important: use compact JSON (`separators=(",",":"), no indent`) so each line is one snapshot, no embedded newlines. Pretty-printing breaks JSONL.

On a failed cycle, same shape with `solved: false, tags: {}` (per Stage 1's degraded-green semantics).

## Outputs

| File | Pattern | Frequency |
|---|---|---|
| Active hour file | `stream_<YYYY-MM-DD>T<HH>.jsonl` | One per UTC hour, growing |
| Rotated/archived | `stream_<YYYY-MM-DD>T<HH>.jsonl.gz` | Created on rotation, deleted on retention sweep |
| Streamer log | `streamer.log` | Append mode, life of process |
| Console | stdout summary lines | Real-time |

Disk footprint at steady state (30 s cadence, 1-day retention):
- 1 active uncompressed file: up to ~10 MB
- 23 compressed prior hours: ~2-3 MB each → ~40-70 MB total
- Total: ~50-80 MB

## Acceptance criteria

- [ ] `streamer.py` exists at `2.automation/stage2/streamer.py`
- [ ] Initial solve passes; tag count == 1550
- [ ] Cycle interval defaults to 30 s; configurable via `--interval`
- [ ] Snapshots append to current hour's `.jsonl`, one per line, valid JSON
- [ ] `tail -f` on the active file shows new snapshots arriving every ~30 s
- [ ] At hour boundary, current file closes, gets gzipped to `.jsonl.gz`, new file opens
- [ ] Files older than 24 h get deleted on retention sweep (verify by manually setting an old mtime and running)
- [ ] On forced cycle failure (e.g., temporarily yank substrate file), streamer emits `solved: false` line and continues
- [ ] Ctrl-C produces clean shutdown line; final hour's file remains as `.jsonl` (not gzipped) so restart appends correctly
- [ ] Restart after Ctrl-C in same hour appends to existing file (no new file, no overwrite)
- [ ] Memory growth < 500 MB after 1-hour run
- [ ] `streamer.py` is one file, ≤ 450 lines (Stage 1 budget was 350; Stage 2 has rotation + retention so 450 is reasonable)

## Anti-goals

- ✗ No setpoint write-back (Stage 6)
- ✗ No REST API (Stage 3)
- ✗ No OPC-UA (Stage 4)
- ✗ No Azure / Event Hubs (Stage 5)
- ✗ No multi-process or threading
- ✗ No reloading the substrate per cycle
- ✗ No streaming mid-solve
- ✗ No modification of the substrate, Phase 0a artifacts, Stage 1 artifacts, or Phase 1 infra
- ✗ No schema changes (must match Stage 1's snapshot schema exactly)

## Methodology rules

- Atomic line writes (write + flush) so `tail -f` is reliable
- Don't crash on cycle errors — emit `solved: false`, continue
- 3 consecutive cycle failures → exit non-zero
- Probe before assuming new APIs (none expected)
- Sync solve, no threading

## Out of scope

- Stages 3-6
- Features 1-5
- Substrate modification, Phase 0a, Stage 1, or Phase 1 changes

## Definition of done

1. `streamer.py` exists at `2.automation/stage2/streamer.py`
2. 1-hour smoke run produces ~120 lines in one `.jsonl` file (no rotation expected within 1 hour unless run crosses an hour boundary)
3. 25-hour stress run (or simulated by manipulating mtimes): rotation happens at every hour boundary, retention deletes files older than 24 h, only ~24-25 files visible at any time
4. Operator runs `tail -f` on the active file during a smoke run, observes lines arriving every ~30 s
5. Operator runs a sample query: `cat stream_*.jsonl | jq -s 'length'` returns the expected snapshot count; `cat stream_*.jsonl | jq '.tags."ES-CONDENSER_DUTY.EnergyFlow"'` returns a stream of duty values
6. Operator approves; architect issues next briefing (Feature 1 Fabric ingestion)

## Hand-off note for Claude Code

Stage 1's `streamer.py` is your reference for extraction logic, bootstrap, and the per-cycle snapshot build. Don't import from it (different stage subdirectory; cleaner to re-implement). Copy the extraction patterns and adapt to JSONL append + rotation.

The new pieces in Stage 2 vs Stage 1:
1. JSONL append (one line per snapshot, compact JSON, flush after each line)
2. Hourly rotation by UTC hour boundary
3. Gzip on rotation (in-flight hour stays uncompressed; closed hours get `.gz`)
4. Retention sweep at startup and on rotation (delete files older than retention window)

Cycle interval stays at 30 s (same as Stage 1). Everything else carries over: bootstrap, initial solve gate, per-cycle solve+extract, error handling with degraded-green semantics, signal handling, log lines.

If `tail -f` doesn't show lines in real time, the issue is buffering — make sure to `flush()` after each write. Don't add `os.fsync()` (overkill for this use case).

Branch: `phase-2-streaming`. Create from current `phase-1-foundation` after Phase 1 is verified and merged. Conventional commits.

End of briefing.
