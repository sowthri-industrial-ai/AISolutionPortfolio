# Stage 4 — OPC-UA Server (asyncua)

Industrial-protocol exposure of the 1550 DWSIM tag set as OPC-UA Variable nodes
on `opc.tcp://localhost:4840/refinery_twin/`. Browsable by any OPC-UA client
(UaExpert, KEPServerEX, Ignition, asyncua's own Python client).

Same data source as Stage 3 and Stage 5: the Stage 2 streamer's hour-bucket
JSONL files. No DWSIM connection, no cloud — read-only tail of local snapshots.

## Setup (one-time)

```bash
cd 2.automation/stage4
arch -x86_64 ../.venv-x86/bin/pip install asyncua
```

## Run

```bash
arch -x86_64 ../.venv-x86/bin/python opcua_server.py
```

The server runs in the foreground; Ctrl-C for graceful shutdown.

Two files in this directory:

- `node_hierarchy.py` — pure tag-dict → tree transformation library
  (asyncua-free, importable, standalone testable). Run it directly to see the
  hierarchy stats:
  ```bash
  arch -x86_64 ../.venv-x86/bin/python node_hierarchy.py
  ```
- `opcua_server.py` — the asyncua server. Imports `build_node_specs` from the
  hierarchy library and wires the tree into asyncua Variable nodes.

## Config (env vars, all optional)

| Var | Default | Purpose |
|---|---|---|
| `TAG_DICT_PATH` | `3.probes/phase0a/phase0a_tag_dictionary.json` | 1550-entry tag dictionary |
| `STAGE2_DIR` | `4.snapshots/stage2/` | Where to find `stream_*.jsonl` |
| `OPCUA_ENDPOINT` | `opc.tcp://localhost:4840/refinery_twin/` | Server bind URL |
| `POLL_INTERVAL_S` | `5.0` | Tag-update poll interval (sec) |

## Hierarchy (briefing-aligned)

```
Refinery/
├── PetroleumSide/            656 vars
│   ├── MaterialStreams/      (Oil, Light Product, Intermediate, Heavy, etc.)
│   ├── EnergyStreams/        (Condenser Duty, Reboiler Duty, ...)
│   └── Columns/              (Distillation Column → STAGE_0...STAGE_11)
├── ThermalOilLoop/           894 vars
│   ├── MaterialStreams/      (Therminol VP1, MSTR_010, ...)
│   ├── EnergyStreams/        (Heating Duty, ESTR_017, ...)
│   └── Equipment/            (Heater + Pump + Tank + Recycle, flat)
└── StreamerHealth/
    ├── LastSnapshotCycle      (Int32)
    ├── LastSnapshotTimestamp  (String)
    └── Stage2Running          (Boolean)
```

Subsystem split follows Phase 0a architect overrides (Storage Tank → thermal_oil,
Reboiler Duty energy stream → petroleum).

Full tree shape walk:

```bash
arch -x86_64 ../.venv-x86/bin/python node_hierarchy.py
```

Sample browse paths in `docs/api/opcua_browse_paths.md`.

## Quality codes

| State | StatusCode | When |
|---|---|---|
| `BadNoCommunication` | initial | Server just started, no snapshot ingested yet |
| `Good` | per tick | Latest snapshot has `solved: true`; written values land Good |
| `UncertainLastUsableValue` | per tick | Latest snapshot has `solved: false`; written values get Uncertain |
| (unchanged) | between cycles | Diff-and-write means unchanged values keep their last StatusCode |

Clients should inspect `Refinery/StreamerHealth/Stage2Running` for overall
system status — it's updated every tick.

## Update strategy

Per architect Q1 (A2 design review):
- **Diff-and-write only**: each tick compares the new snapshot's values to
  in-memory `last_values` map; writes only changed tags. Steady-state
  snapshots barely change between cycles → most ticks write 0-2 nodes.
- This saves CPU and avoids spurious OPC-UA subscription wake-ups, while
  preserving the briefing's <5% CPU AC for 10 subscribed clients.

Per architect Q2:
- **None values are skipped**: when a tag's value is `null` in the snapshot
  (uncommon, ~10 tags such as `DeltaP` on the Storage Tank), we leave the
  OPC-UA node at its last-good value. Tag count stays at 1550; per-tick stats
  log `none=N` so you can see how many were skipped.

## Smoke tests

### 1. Tiny asyncua Python client

A 30-line client that connects, browses, reads, and subscribes:

```bash
arch -x86_64 ../.venv-x86/bin/python - <<'EOF'
import asyncio
from asyncua import Client, ua

ENDPOINT = "opc.tcp://localhost:4840/refinery_twin/"

class Sub:
    def datachange_notification(self, node, val, data):
        print(f"  notify: {node} = {val}")

async def main():
    async with Client(ENDPOINT) as client:
        objs = client.get_objects_node()
        refinery = await objs.get_child("2:Refinery")
        print("Top-level children of Refinery:")
        for child in await refinery.get_children():
            bn = await child.read_browse_name()
            print(f"  {bn.Name}")

        # Read a known tag value
        cond_duty = await client.nodes.root.get_child(
            ["0:Objects", "2:Refinery", "2:PetroleumSide", "2:EnergyStreams",
             "2:ES-CONDENSER_DUTY", "2:EnergyFlow"]
        )
        val = await cond_duty.read_value()
        print(f"\nES-CONDENSER_DUTY.EnergyFlow = {val} (expected ~29755 kW)")

        # Subscribe to one node for 35 s (one full Stage 2 cycle should fire)
        sub = await client.create_subscription(1000, Sub())
        await sub.subscribe_data_change(cond_duty)
        print("\nsubscribed; waiting 35 s for change notification...")
        await asyncio.sleep(35)
        await sub.delete()

asyncio.run(main())
EOF
```

Expected: prints the four top-level children (PetroleumSide, ThermalOilLoop,
StreamerHealth, and Server-standard ones), reads condenser duty ~29755 kW
(Phase 0a ground truth), and prints at least one subscription notification
when the next solve cycle lands.

### 2. UaExpert (GUI verification)

1. Open UaExpert (free download from unified-automation.com).
2. **Add Server** → "Discovery": paste `opc.tcp://localhost:4840/refinery_twin/`,
   pick the resulting endpoint, security policy "None — None".
3. **Connect** (anonymous).
4. In the Address Space pane, expand `Objects → Refinery`.
5. Drag any leaf (e.g., `Refinery/PetroleumSide/EnergyStreams/ES-CONDENSER_DUTY/EnergyFlow`)
   into the Data Access view. Value updates as Stage 2 ingests new snapshots.
6. To verify subscriptions: nothing extra — UaExpert auto-subscribes when you
   drag a node in. Watch the value increment whenever Stage 2 produces a new
   solve cycle (~30 s).

Server status checks:
- `Server/ServerStatus/State` should report `Running`
- `Refinery/StreamerHealth/Stage2Running` reports `true` while Stage 2 is active
- `Refinery/StreamerHealth/LastSnapshotCycle` increments every ~30 s

## Out-of-scope

- **No setpoint write-back** — read-only OPC-UA layer (write-back is post-demo,
  needs DWSIM session reuse and a different architecture)
- **No authentication / authorization** — anonymous binding, demo only
- **No TLS / OPC-UA security mode** — `NoSecurity` only. Hardening is
  post-demo: configure SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
  generate server cert, issue client certs.
- **No persistence** — server reads JSONL on each tick; no separate DB
- **No multi-server registry** — single server, single endpoint, single host

## Architecture note

`node_hierarchy.py` is deliberately asyncua-free so the tree-shape logic can be
reviewed and refactored in isolation. The OPC-UA server module imports
`build_node_specs` and wires the resulting `NodeSpec` list into asyncua Variable
nodes. If the tree shape needs adjustment, edit `node_hierarchy.py` only;
`opcua_server.py` stays untouched.
