# Stage 1 Briefing — Local JSON Streamer

**Project:** Refinery Digital Twin · Feature 4 streaming foundation
**Issued by:** Architect chat
**Implementer:** Claude Code
**Operator:** Sowthri
**Status:** Phase 0a closed → this briefing
**Estimated effort:** 1.5 hr implementer + 30 min operator (1-hour stability run)

---

## Goal

A long-running Python process that loads the locked DWSIM substrate once, solves every 30 seconds, and writes a JSON snapshot per cycle to disk. This is the data source that every downstream feature (Fabric, twin, agents, web UI) consumes.

Stage 1 is the **minimum viable streamer**: local file sink only. No API, no cloud, no setpoint write-back, no fancy schema. Get the loop bulletproof on disk before adding anything else.

## Substrate

Same as Phase 0a — locked, do not modify.

`/Applications/DWSIM.app/Contents/MonoBundle/samples/Petroleum Distillation with Reboiler Heating Fluid.dwxmz`

## Inputs (CLI args, sensible defaults)

| | Default | |
|---|---|---|
| Substrate path | (locked, hardcoded) | |
| Tag dictionary | `~/Documents/AISolutionPortfolio/2.AssetsAI/1.RefineryDigitalTwin/3.probes/phase0a/phase0a_tag_dictionary.json` | drives extraction |
| Output directory | `~/Documents/AISolutionPortfolio/2.AssetsAI/1.RefineryDigitalTwin/4.snapshots/stage1/` | created if missing |
| Cycle interval | 30 s | `--interval` flag |

## Required reading before code

1. `DWSIM_KNOWLEDGE_BASE.md` — bug classes and patterns still apply
2. `STREAMING_PLAN.md` Part C — streaming architecture, engineering decisions
3. `phase0a_findings.md` — the override rules baked into the tag dictionary
4. `phase0a_inventory.json` — reference for "what extraction pattern each `owner_type` needs"
5. This briefing — the contract

If anything contradicts the KB, the KB wins. Stop and flag.

## Toolchain

Same venv as Phase 0a. Script lives at `2.automation/stage1/streamer.py`, run from there:

```
arch -x86_64 ../.venv-x86/bin/python streamer.py
```

## Behavior

### 1. Bootstrap (once, at startup)
- Add DWSIM DLL references; construct `Automation3()`
- Register Python-side log capture (KB §3 update — `MessageListener` API not exposed on macOS 9.0.5; capture stdout/stderr)
- Load `phase0a_tag_dictionary.json` into memory
- Sanity check: `len(tags) == 1550`. If mismatched, the substrate or dictionary has drifted — fail-fast with a clear error; do not proceed
- Open `streamer.log` (append mode); write run config header

### 2. Initial solve (verify substrate still works)
- `LoadFlowsheet(substrate_path)`
- `CalculateFlowsheet4(sim)`
- Assert `sim.Solved == True`; on failure, dump error and exit non-zero
- Record initial solve duration; flag if > 10 s

### 3. Main loop (until Ctrl-C)

```
while not shutdown:
    t0 = time()
    try:
        solve_errors = sim_auto.CalculateFlowsheet4(sim)
        snapshot = build_snapshot(sim, tag_dict, cycle, t0)
    except Exception as e:
        snapshot = build_failure_snapshot(cycle, e)
        consecutive_failures += 1
    else:
        consecutive_failures = 0

    write_snapshot(snapshot, output_dir)
    log_cycle(cycle, snapshot)

    if consecutive_failures >= 3:
        log_fatal("3 consecutive cycle failures — exiting")
        sys.exit(2)

    sleep(max(0, interval - (time() - t0)))
    cycle += 1
```

### 4. Snapshot extraction

For each entry in the tag dictionary, dispatch by `owner_type`:

- `MaterialStream` + numeric prop → `obj.GetPropertyValue(property_key)` (probe-proven)
- `MaterialStream` + composition tag → walk `obj.Phases[<phase_idx>].Compounds[<compound>].MoleFraction` / `.MassFraction`
- `Column` + `STAGE-N.<prop>` → `obj.Stages[N].<prop>` (T, P, V, L, etc.)
- `Column` + global prop (`RefluxRatio`, `CondenserDuty`, etc.) → reflect via property name
- `EnergyStream` → `obj.EnergyFlow`
- `Heater` / `Pump` / `Tank` / `RecycleBlock` → reflect to the property name in the dictionary entry

The dictionary's `owner_tag`, `owner_type`, `phase`, and `property_key` fields tell you everything you need. Use `phase0a_inventory.json` as the reference for ambiguous cases — it has the full per-object property map from the probe run.

### 5. Snapshot emission
- Path: `<output_dir>/snap_<UTC_ISO>.json` (e.g. `snap_2026-05-09T19-30-00Z.json`)
- UTC timestamps in filenames are collision-free; no refuse-if-exists needed for snapshots
- Atomic write: write to `snap_<...>.json.tmp`, then `os.rename()` to final name. Prevents partial-snapshot reads if a downstream consumer is polling

### 6. Cycle logging (one line per cycle)
Append to `streamer.log`:

```
<UTC_ISO>  cycle=<N>  solved=<true|false>  duration=<s>s  tags=<N>  errors=<count>
```

Plus a stdout echo for live tailing.

### 7. Graceful shutdown
- Trap `SIGINT` and `SIGTERM`
- Set `shutdown = True`; finish the current cycle if mid-solve
- Final log line: `Streamer stopped after <N> cycles (<duration>), <errors> errors`
- Flush, exit 0

## Snapshot schema (flat, simple)

```json
{
  "timestamp": "2026-05-09T19:30:00.000Z",
  "cycle": 142,
  "solved": true,
  "solve_time_s": 3.84,
  "cycle_duration_s": 4.12,
  "tag_count": 1550,
  "errors": [],
  "tags": {
    "MS-OIL.OVERALL.PROP_MS_0": 350.0,
    "MS-OIL.OVERALL.PROP_MS_1": 101325.0,
    "...": "..."
  }
}
```

Streaming Plan Part C had a nested schema (streams/columns/energy_streams). For Stage 1, **flat is simpler** — easier to diff between cycles, easier to ingest, downstream consumers can re-nest by parsing the `tag_id` structure if they need hierarchy.

On a failed cycle:

```json
{
  "timestamp": "...",
  "cycle": 143,
  "solved": false,
  "solve_time_s": null,
  "cycle_duration_s": 0.18,
  "tag_count": 0,
  "errors": ["<exception class>: <message>"],
  "tags": {}
}
```

## Outputs summary

| File | Pattern | Frequency |
|---|---|---|
| Snapshots | `snap_<UTC_ISO>.json` | Per cycle |
| Streamer log | `streamer.log` | Append mode, life of process |
| Console | stdout summary lines | Real-time |

## Acceptance criteria

- [ ] Initial solve succeeds; tag count == 1550 (sanity gate)
- [ ] Streamer runs for ≥ 1 hour without crashing → ≥ 110 snapshots produced
- [ ] Every snapshot is valid JSON, schema-consistent, loadable with `json.load()`
- [ ] Solve time stable (3–5 s per cycle); flag if drifts > 8 s
- [ ] Memory growth < 500 MB after 1 hour
- [ ] Ctrl-C produces a clean shutdown line and zero-error exit
- [ ] Snapshot tag count == 1550 on the success path
- [ ] On forced cycle failure (e.g. unplug the substrate file mid-run as a stress test), streamer emits `solved: false` snapshots and continues — does not crash
- [ ] `streamer.py` is one file, ≤ 350 lines

## Anti-goals

- ✗ No setpoint write-back (Stage 6)
- ✗ No REST API (Stage 3)
- ✗ No OPC-UA (Stage 4)
- ✗ No Azure / Event Hubs (Stage 5)
- ✗ No multi-process or threading (DWSIM Automation3 is not thread-safe)
- ✗ No reloading the substrate per cycle (defeats in-memory caching)
- ✗ No streaming mid-solve (locks .NET runtime)
- ✗ No modification of the substrate
- ✗ No changes to Phase 0a artifacts

## Methodology rules (universal)

- Sanity-gate at startup (tag count, initial solve)
- Don't crash on cycle errors — emit `solved: false`, continue
- 3 consecutive cycle failures → exit non-zero (structural problem)
- Atomic snapshot writes (`.tmp` + rename)
- Probe before assuming any new API surface (Phase 0a covered the relevant surface; new ones shouldn't be needed)
- Sync solve, no async during DWSIM calls

## Out of scope

- Stages 2–6
- F1–F5
- Web UI, dashboard, agent integration
- Substrate modification

## Definition of done

1. `streamer.py` exists at `2.automation/stage1/streamer.py`
2. 1-hour run produces ≥ 110 valid snapshots
3. Operator opens 3 sample snapshots, confirms ~1550 tags each with values matching expected substrate state (Oil temperature ~350 K, condenser duty ~29.76 MW, etc.)
4. Operator runs streamer, watches log, Ctrl-Cs, observes clean shutdown
5. Operator approves; architect issues next briefing (most likely Stage 2 — JSONL + retention, or jump directly to F1 Fabric ingestion depending on demo timeline)

## Hand-off note for Claude Code

The probe was the hard part. Stage 1 is mechanical: take the extraction patterns proven in Phase 0a, wrap them in a 30-second loop, write JSON. Most of this briefing is constraint and contract — the actual code is small.

`probe.py` got autoformatter-mangled per the Phase 0a closeout — don't try to import from it. Re-implement the extraction logic directly in `streamer.py`, driven by the tag_dictionary entries. Use `phase0a_inventory.json` as the reference for "how do I extract a value of `owner_type=X` and `phase=Y`."

The override rules from Phase 0a (Storage Tank → thermal_oil, Reboiler Duty → petroleum, `perturbable: false` on non-numeric) are already baked into the tag dictionary. The streamer just reads those values; it does not re-apply rules.

Refuse-if-exists does NOT apply to per-cycle snapshots — they're UTC-timestamped and collision-free. The streamer log appends across runs; rotate manually if it ever exceeds 100 MB (not expected for Stage 1).

End of briefing.
