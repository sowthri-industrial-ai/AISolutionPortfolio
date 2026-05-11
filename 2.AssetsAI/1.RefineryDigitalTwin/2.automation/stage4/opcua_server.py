#!/usr/bin/env python3
"""Stage 4 — asyncua OPC-UA server over Stage 2 snapshots.

Serves the live + (per-tick latest) DWSIM tag set as OPC-UA Variable nodes on
opc.tcp://localhost:4840/refinery_twin/. Browsable by any OPC-UA client
(UaExpert, KEPServerEX, Ignition, asyncua's own Python client).

Tree built from `node_hierarchy.py` (committed separately). Subsystem split
under Refinery/ follows Phase 0a overrides:

    Refinery/
    ├── PetroleumSide/ (656 vars)
    │   ├── MaterialStreams/<owner>/[<phase>/][<MoleFraction|...>/]<leaf>
    │   ├── EnergyStreams/<owner>/<leaf>
    │   └── Columns/<owner>/[STAGE_N/]<leaf>
    ├── ThermalOilLoop/ (894 vars)
    │   ├── MaterialStreams/...
    │   ├── EnergyStreams/...
    │   └── Equipment/...   (Heater/Pump/Tank/Recycle, flat)
    └── StreamerHealth/
        ├── LastSnapshotCycle      (Int32)
        ├── LastSnapshotTimestamp  (String)
        └── Stage2Running          (Boolean)

Update strategy (per architect Q1): diff-and-write — only push values that
changed since the last cycle. Saves CPU + avoids spurious subscription wakes.

None values (per architect Q2): skip the write; node holds last-good value.
Status quality reflects intent at cycle level (see below).

Quality codes:
    - On startup, before any snapshot ingested: `BadNoCommunication`
    - On `solved=true`: written values land with `Good`
    - On `solved=false` or Stage 2 down: per-node status is NOT updated each
      tick (avoiding the 1550-write storm); clients should inspect
      `Refinery/StreamerHealth/Stage2Running` for system status

Setup (one-time):
    arch -x86_64 ../.venv-x86/bin/pip install asyncua

Run (from 2.automation/stage4/):
    arch -x86_64 ../.venv-x86/bin/python opcua_server.py

Env vars (defaults assume project layout):
    TAG_DICT_PATH        path to phase0a_tag_dictionary.json
    STAGE2_DIR           path to 4.snapshots/stage2/
    OPCUA_ENDPOINT       full opc.tcp:// URL (default opc.tcp://localhost:4840/refinery_twin/)
    POLL_INTERVAL_S      tick interval, default 5.0
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any, Optional

from asyncua import Server, ua

# Local import — same directory.
sys.path.insert(0, str(Path(__file__).parent.resolve()))
from node_hierarchy import NodeSpec, build_node_specs  # noqa: E402

# ----- Constants & config -----

DEFAULT_TAG_DICT = (
    "/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
    "2.AssetsAI/1.RefineryDigitalTwin/3.probes/phase0a/phase0a_tag_dictionary.json"
)
DEFAULT_STAGE2_DIR = (
    "/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
    "2.AssetsAI/1.RefineryDigitalTwin/4.snapshots/stage2"
)
DEFAULT_ENDPOINT = "opc.tcp://localhost:4840/refinery_twin/"
NAMESPACE_URI = "urn:RefineryDigitalTwin"
APP_URI = "urn:RefineryDigitalTwin:server"
PRODUCT_URI = "urn:RefineryDigitalTwin:dwsim_petroleum_distillation"
DEFAULT_POLL_INTERVAL_S = 5.0

UA_TYPE_MAP = {
    "Double": ua.VariantType.Double,
    "Int32": ua.VariantType.Int32,
    "Boolean": ua.VariantType.Boolean,
    "String": ua.VariantType.String,
}

DEFAULTS_BY_TYPE: dict[ua.VariantType, Any] = {
    ua.VariantType.Double: 0.0,
    ua.VariantType.Int32: 0,
    ua.VariantType.Boolean: False,
    ua.VariantType.String: "",
}


class Stage4Server:
    def __init__(
        self,
        tag_dict_path: str,
        stage2_dir: str,
        endpoint: str,
        poll_interval_s: float,
    ):
        self.tag_dict_path = Path(tag_dict_path).expanduser()
        self.stage2_dir = Path(stage2_dir).expanduser()
        self.endpoint = endpoint
        self.poll_interval_s = float(poll_interval_s)
        self.shutdown = False
        self.specs: list[NodeSpec] = []
        self.node_map: dict[str, Any] = {}       # tag_id → asyncua Node
        self.node_types: dict[str, ua.VariantType] = {}  # tag_id → VariantType
        self.last_values: dict[str, Any] = {}    # tag_id → last-written Python value
        self.health_nodes: dict[str, Any] = {}
        self.server: Optional[Server] = None
        self.ns_idx: Optional[int] = None
        self.refinery_root: Optional[Any] = None
        self.cumulative_writes = 0
        self.log = logging.getLogger("stage4")

    # ---- Setup ----

    async def setup(self) -> None:
        if not self.tag_dict_path.is_file():
            raise RuntimeError(f"tag dict not found: {self.tag_dict_path}")
        with open(self.tag_dict_path) as f:
            entries = json.load(f)
        self.specs = build_node_specs(entries)
        self.log.info(
            f"loaded {len(entries)} tag entries → {len(self.specs)} node specs"
        )

        self.server = Server()
        await self.server.init()
        self.server.set_endpoint(self.endpoint)
        self.server.set_server_name("Refinery Digital Twin")
        self.server.set_application_uri(APP_URI)
        # Anonymous + no security — demo mode. Hardening is post-A2.
        self.server.set_security_policy([ua.SecurityPolicyType.NoSecurity])

        self.ns_idx = await self.server.register_namespace(NAMESPACE_URI)
        self.log.info(f"namespace {NAMESPACE_URI} → ns_idx={self.ns_idx}")

        objects = self.server.get_objects_node()
        self.refinery_root = await objects.add_folder(self.ns_idx, "Refinery")

        await self._build_variable_nodes()
        await self._build_health_nodes()

        self.log.info(
            f"hierarchy built: {len(self.node_map)} variables, "
            f"3 health nodes; ready to serve"
        )

    async def _build_variable_nodes(self) -> None:
        """Walk specs, creating folders on demand + leaf Variable nodes."""
        folder_cache: dict[tuple[str, ...], Any] = {(): self.refinery_root}
        for spec in self.specs:
            try:
                parent = await self._ensure_folder(folder_cache, spec.folder_path)
                ua_type = UA_TYPE_MAP.get(spec.ua_type, ua.VariantType.Double)
                init_val = DEFAULTS_BY_TYPE.get(ua_type, 0.0)
                node = await parent.add_variable(
                    self.ns_idx, spec.leaf_name, init_val, ua_type
                )
                # Initial status: BadNoCommunication — no snapshot ingested yet.
                await self._write_with_status(
                    node, init_val, ua.StatusCode(ua.StatusCodes.BadNoCommunication)
                )
                self.node_map[spec.tag_id] = node
                self.node_types[spec.tag_id] = ua_type
            except Exception as e:
                self.log.warning(f"failed to create node for {spec.tag_id}: {e}")

    async def _ensure_folder(
        self, cache: dict[tuple[str, ...], Any], path: tuple[str, ...]
    ) -> Any:
        """Walk path segments, creating folders on demand. Returns the deepest folder."""
        parent = cache[()]
        acc: tuple[str, ...] = ()
        for seg in path:
            acc = acc + (seg,)
            cached = cache.get(acc)
            if cached is not None:
                parent = cached
                continue
            child = await parent.add_folder(self.ns_idx, seg)
            cache[acc] = child
            parent = child
        return parent

    async def _build_health_nodes(self) -> None:
        health = await self.refinery_root.add_folder(self.ns_idx, "StreamerHealth")
        self.health_nodes["LastSnapshotCycle"] = await health.add_variable(
            self.ns_idx, "LastSnapshotCycle", -1, ua.VariantType.Int32
        )
        self.health_nodes["LastSnapshotTimestamp"] = await health.add_variable(
            self.ns_idx, "LastSnapshotTimestamp", "", ua.VariantType.String
        )
        self.health_nodes["Stage2Running"] = await health.add_variable(
            self.ns_idx, "Stage2Running", False, ua.VariantType.Boolean
        )

    # ---- Tail-reading helpers (re-implemented per "don't import from prior stages") ----

    def find_active_jsonl(self) -> Optional[Path]:
        candidates = sorted(self.stage2_dir.glob("stream_*.jsonl"))
        return candidates[-1] if candidates else None

    @staticmethod
    def read_last_snapshot(path: Path) -> Optional[dict]:
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return None
        if not data:
            return None
        for raw in reversed(data.split(b"\n")):
            line = raw.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return None

    # ---- Cycle / writes ----

    async def _write_with_status(
        self, node: Any, value: Any, status: ua.StatusCode
    ) -> None:
        """Write value + explicit StatusCode in a single Value-attribute update."""
        dv = ua.DataValue(ua.Variant(value))
        dv.StatusCode_ = status
        await node.write_attribute(ua.AttributeIds.Value, dv)

    async def _safe_write_value(self, node: Any, value: Any) -> None:
        try:
            await node.write_value(value)
        except Exception as e:
            self.log.debug(f"safe_write_value failed: {e}")

    def _coerce(self, raw: Any, ua_type: ua.VariantType) -> Optional[Any]:
        """Coerce a Python value to fit a node's declared UA type."""
        if raw is None:
            return None
        try:
            if ua_type == ua.VariantType.Double:
                return float(raw)
            if ua_type == ua.VariantType.Int32:
                # Python bools are ints; preserve int semantics
                return int(raw)
            if ua_type == ua.VariantType.Boolean:
                return bool(raw)
            if ua_type == ua.VariantType.String:
                return str(raw)
        except (TypeError, ValueError):
            return None
        return raw

    async def update_cycle(self) -> dict:
        """One tick: find active jsonl, ingest latest snapshot, diff-write tags."""
        stats = {"written": 0, "unchanged": 0, "none": 0, "no_node": 0, "errors": 0}
        active = self.find_active_jsonl()
        if active is None:
            await self._safe_write_value(self.health_nodes["Stage2Running"], False)
            stats["stage2_down"] = True
            return stats

        await self._safe_write_value(self.health_nodes["Stage2Running"], True)

        snap = self.read_last_snapshot(active)
        if snap is None:
            return stats

        await self._safe_write_value(
            self.health_nodes["LastSnapshotCycle"], int(snap.get("cycle", -1))
        )
        await self._safe_write_value(
            self.health_nodes["LastSnapshotTimestamp"], str(snap.get("timestamp", ""))
        )

        solved = bool(snap.get("solved", False))
        status = ua.StatusCode(
            ua.StatusCodes.Good
            if solved
            else ua.StatusCodes.UncertainLastUsableValue
        )

        for tag_id, raw in snap.get("tags", {}).items():
            node = self.node_map.get(tag_id)
            if node is None:
                stats["no_node"] += 1
                continue
            if raw is None:
                # Q2 default: skip write, leave at last-good value.
                stats["none"] += 1
                continue
            last = self.last_values.get(tag_id)
            if raw == last:
                stats["unchanged"] += 1
                continue
            coerced = self._coerce(raw, self.node_types.get(tag_id, ua.VariantType.Double))
            if coerced is None:
                stats["errors"] += 1
                continue
            try:
                await self._write_with_status(node, coerced, status)
                self.last_values[tag_id] = raw
                stats["written"] += 1
            except Exception as e:
                self.log.debug(f"write {tag_id}={raw!r} failed: {e}")
                stats["errors"] += 1

        self.cumulative_writes += stats["written"]
        return stats

    # ---- Main loop ----

    async def run(self) -> None:
        await self.setup()
        self.log.info(f"server starting on {self.endpoint}")
        async with self.server:
            self.log.info("server running; update loop active")
            loop = asyncio.get_event_loop()
            while not self.shutdown:
                cycle_start = loop.time()
                try:
                    stats = await self.update_cycle()
                    self.log.info(
                        "cycle "
                        f"written={stats['written']} unchanged={stats['unchanged']} "
                        f"none={stats['none']} no_node={stats['no_node']} "
                        f"errors={stats['errors']} cumulative={self.cumulative_writes}"
                    )
                except Exception as e:
                    self.log.warning(f"update_cycle failed: {e}; continuing")
                # Sleep for remainder of poll interval, sliced for shutdown responsiveness.
                deadline = cycle_start + self.poll_interval_s
                while not self.shutdown and loop.time() < deadline:
                    await asyncio.sleep(min(0.5, max(0.0, deadline - loop.time())))
        self.log.info(
            f"server stopped after {self.cumulative_writes} cumulative writes"
        )


async def amain() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )

    server = Stage4Server(
        tag_dict_path=os.environ.get("TAG_DICT_PATH", DEFAULT_TAG_DICT),
        stage2_dir=os.environ.get("STAGE2_DIR", DEFAULT_STAGE2_DIR),
        endpoint=os.environ.get("OPCUA_ENDPOINT", DEFAULT_ENDPOINT),
        poll_interval_s=float(
            os.environ.get("POLL_INTERVAL_S", str(DEFAULT_POLL_INTERVAL_S))
        ),
    )

    def _sig(signum: int) -> None:
        server.log.info(f"received signal {signum}; shutdown after current cycle")
        server.shutdown = True

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _sig, sig)

    await server.run()


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        sys.exit(0)
