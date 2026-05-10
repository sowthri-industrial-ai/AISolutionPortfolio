#!/usr/bin/env python3
"""Stage 5 — Event Hubs producer for Refinery Digital Twin.

Tails the Stage 2 active hour file (`stream_<UTC_HOUR>.jsonl`), batches new
lines, and sends them to Azure Event Hubs. One Event Hub message body =
one JSONL line = one snapshot. No transformation; Eventstream parses JSON
downstream.

Setup (one-time):
    arch -x86_64 ../.venv-x86/bin/pip install azure-eventhub
    export EVENT_HUB_CONNECTION_STRING='Endpoint=sb://...;EntityPath=dwsim-snapshots'

Run (from 2.automation/stage5/):
    arch -x86_64 ../.venv-x86/bin/python producer.py

Connection string source: EVENT_HUB_CONNECTION_STRING env var only.
After `azd up` provisions the Event Hub, fetch the rule-level connection
string (which includes EntityPath) via:
    az eventhubs eventhub authorization-rule keys list \\
        --resource-group rg-refinerydigitaltwin-dev \\
        --namespace-name <evhns-...> \\
        --eventhub-name dwsim-snapshots \\
        --name producer-send \\
        --query primaryConnectionString -o tsv

Position file (`position.json` in this dir, gitignored): tracks
{ current_file, byte_offset } so restarts resume cleanly. Atomic write
(.tmp + os.rename) so a crash mid-write doesn't corrupt it.

Known Wave 1 edge case — rotation race. If Stage 2 gzips a closed-hour
file in the ~2s window between our reads, we skip the tail of that file
and start at byte 0 of the new hour file. Worst-case data loss: ~80 KB
of recent snapshots. Accepted for Wave 1; revisit if real gaps appear.

Resilience:
    - Send retries: exponential backoff 1, 2, 4, 8, 16, 30 s; whole chain = 1 failure.
    - 3 consecutive cycle failures → exit non-zero (operator restarts).
    - byte_offset advances ONLY after a successful send.
    - Malformed JSON line: log warning, skip, continue.
"""

import argparse
import json
import os
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STAGE2_DIR = (
    "/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
    "2.AssetsAI/1.RefineryDigitalTwin/4.snapshots/stage2"
)
_HERE = Path(__file__).parent.resolve()
DEFAULT_POSITION_FILE = str(_HERE / "position.json")
DEFAULT_LOG_FILE = str(_HERE / "producer.log")
DEFAULT_POLL_INTERVAL_S = 2.0
DEFAULT_MAX_BATCH_BYTES = 900_000  # ~900KB; Event Hubs hard cap is 1MB

# One retry chain runs through these sleeps. Whole chain = 1 cycle failure.
RETRY_BACKOFF_S = [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]
CONSECUTIVE_FAILURE_LIMIT = 3
EMPTY_POLL_LOG_INTERVAL = 30  # log "still waiting" every N empty polls


def utc_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Producer:
    def __init__(self, stage2_dir, position_file, log_file, poll_interval_s, max_batch_bytes):
        self.stage2_dir = Path(stage2_dir).expanduser()
        self.position_file = Path(position_file).expanduser()
        self.log_file = Path(log_file).expanduser()
        self.poll_interval_s = float(poll_interval_s)
        self.max_batch_bytes = int(max_batch_bytes)
        self.shutdown = False
        self.position = {"current_file": None, "byte_offset": 0}
        self.log_fp = None
        self.client = None
        self.consecutive_failures = 0
        self.cumulative_lines_sent = 0
        self.empty_poll_count = 0

    def log(self, msg, level="INFO"):
        line = f"[{utc_iso()}] [{level}] {msg}"
        print(line, flush=True)
        if self.log_fp:
            self.log_fp.write(line + "\n")
            self.log_fp.flush()

    # Position file ----------------------------------------------------------

    def load_position(self):
        if not self.position_file.is_file():
            self.log(f"position file not found at {self.position_file}; initializing fresh")
            return
        try:
            with open(self.position_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.position["current_file"] = data.get("current_file")
            self.position["byte_offset"] = int(data.get("byte_offset", 0))
            self.log(f"position loaded: file={self.position['current_file']!r}, "
                     f"offset={self.position['byte_offset']}")
        except Exception as e:
            self.log(f"WARN: position file unreadable ({e}); resetting", level="WARN")
            self.position = {"current_file": None, "byte_offset": 0}

    def save_position(self):
        tmp = self.position_file.with_suffix(self.position_file.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.position, f)
        os.rename(tmp, self.position_file)

    # Tail-reading -----------------------------------------------------------

    def find_active_jsonl(self):
        """Return newest stream_*.jsonl (NOT .gz) by filename sort, or None.
        Filenames are stream_YYYY-MM-DDTHH.jsonl, so alphabetical = chronological."""
        candidates = sorted(self.stage2_dir.glob("stream_*.jsonl"))
        return str(candidates[-1]) if candidates else None

    def read_new_data(self, active_file):
        """Read from current byte_offset to EOF. Returns (complete_lines, bytes_consumed).
        Trailing partial line (no \\n) is deferred — its bytes are NOT counted in
        consumed, so next poll reads from there."""
        with open(active_file, "rb") as f:
            f.seek(self.position["byte_offset"])
            buf = f.read()
        if not buf:
            return [], 0
        lines = buf.split(b"\n")
        if buf.endswith(b"\n"):
            complete = lines[:-1]  # last entry empty after final \n
            consumed = len(buf)
        else:
            complete = lines[:-1]  # last entry is the partial line we defer
            consumed = len(buf) - len(lines[-1])
        return complete, consumed

    # Send -------------------------------------------------------------------

    def _send_batch_with_retry(self, batch):
        """Send one batch with exponential backoff. Final attempt after last sleep.
        Raises RuntimeError if all attempts fail."""
        last_err = None
        attempts = len(RETRY_BACKOFF_S) + 1
        for i, wait in enumerate(RETRY_BACKOFF_S + [0.0]):
            try:
                self.client.send_batch(batch)
                if i > 0:
                    self.log(f"send recovered on attempt {i + 1}/{attempts}")
                return
            except Exception as e:
                last_err = e
                if i < len(RETRY_BACKOFF_S):
                    self.log(f"send attempt {i + 1}/{attempts} failed "
                             f"({type(e).__name__}: {e}); sleeping {wait}s",
                             level="WARN")
                    time.sleep(wait)
        raise RuntimeError(f"send_batch exhausted retries: "
                           f"{type(last_err).__name__}: {last_err}")

    def send_lines(self, lines):
        """Batch and send lines. Returns count of lines actually sent."""
        from azure.eventhub import EventData
        sent = 0
        batch = self.client.create_batch(max_size_in_bytes=self.max_batch_bytes)
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError as e:
                self.log(f"WARN: skipping malformed JSON line: {e}", level="WARN")
                continue
            try:
                batch.add(EventData(line))
            except ValueError:
                # Single-line batch full — send and start a new one.
                self._send_batch_with_retry(batch)
                sent += len(batch)
                batch = self.client.create_batch(max_size_in_bytes=self.max_batch_bytes)
                batch.add(EventData(line))
        if len(batch) > 0:
            self._send_batch_with_retry(batch)
            sent += len(batch)
        return sent

    # Loop -------------------------------------------------------------------

    def cycle(self):
        active = self.find_active_jsonl()
        if active is None:
            self.empty_poll_count += 1
            if self.empty_poll_count % EMPTY_POLL_LOG_INTERVAL == 0:
                self.log(f"no stream_*.jsonl in {self.stage2_dir}; waiting "
                         f"(poll #{self.empty_poll_count})")
            return

        if active != self.position["current_file"]:
            self.log(f"active file change: {self.position['current_file']!r} -> "
                     f"{active!r}; starting at byte 0")
            self.position["current_file"] = active
            self.position["byte_offset"] = 0

        complete_lines, consumed_bytes = self.read_new_data(active)
        if not complete_lines:
            self.empty_poll_count += 1
            return
        self.empty_poll_count = 0

        sent = self.send_lines(complete_lines)
        # Advance offset ONLY after successful send.
        self.position["byte_offset"] += consumed_bytes
        self.save_position()
        self.cumulative_lines_sent += sent
        self.log(f"sent={sent}/{len(complete_lines)} lines "
                 f"file={Path(active).name} offset={self.position['byte_offset']} "
                 f"cumulative={self.cumulative_lines_sent}")

    def bootstrap(self):
        self.stage2_dir.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_fp = open(str(self.log_file), "a", encoding="utf-8")
        self.log("=" * 70)
        self.log(f"Producer starting PID={os.getpid()} poll_interval={self.poll_interval_s}s "
                 f"max_batch_bytes={self.max_batch_bytes}")
        self.log(f"  stage2_dir={self.stage2_dir}")
        self.log(f"  position_file={self.position_file}")

        conn = os.environ.get("EVENT_HUB_CONNECTION_STRING")
        if not conn:
            self.log("FATAL: EVENT_HUB_CONNECTION_STRING env var not set", level="FATAL")
            sys.exit(1)

        try:
            from azure.eventhub import EventHubProducerClient
        except ImportError:
            self.log("FATAL: azure-eventhub SDK not installed. Run:", level="FATAL")
            self.log("  arch -x86_64 ../.venv-x86/bin/pip install azure-eventhub",
                     level="FATAL")
            sys.exit(1)

        # producer-send rule is hub-scoped, so the connection string includes
        # EntityPath. SDK auto-detects the eventhub name from it.
        try:
            self.client = EventHubProducerClient.from_connection_string(conn)
            self.log("EventHubProducerClient created from connection string")
        except Exception as e:
            self.log(f"FATAL: client construction failed: {type(e).__name__}: {e}",
                     level="FATAL")
            sys.exit(2)

        self.load_position()

    def run(self):
        self.bootstrap()
        start_ts = time.time()
        try:
            while not self.shutdown:
                cycle_start = time.time()
                try:
                    self.cycle()
                    self.consecutive_failures = 0
                except Exception as e:
                    self.consecutive_failures += 1
                    self.log(f"cycle failed (consecutive={self.consecutive_failures}): "
                             f"{type(e).__name__}: {e}", level="ERROR")
                    if self.consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                        self.log(f"FATAL: {self.consecutive_failures} consecutive cycle "
                                 f"failures; exiting non-zero", level="FATAL")
                        sys.exit(2)

                deadline = cycle_start + self.poll_interval_s
                while not self.shutdown and time.time() < deadline:
                    time.sleep(min(0.5, max(0.0, deadline - time.time())))
        except SystemExit:
            raise
        except Exception as e:
            self.log(f"FATAL unhandled: {type(e).__name__}: {e}", level="FATAL")
            self.log(traceback.format_exc(), level="FATAL")
            sys.exit(3)
        finally:
            duration = time.time() - start_ts
            try:
                if self.client is not None:
                    self.client.close()
            except Exception:
                pass
            try:
                self.save_position()
            except Exception as e:
                self.log(f"WARN: final save_position failed: {e}", level="WARN")
            self.log(f"Producer stopped after {duration:.1f}s, "
                     f"{self.cumulative_lines_sent} lines sent")
            if self.log_fp:
                self.log_fp.flush()
                self.log_fp.close()


def main():
    p = argparse.ArgumentParser(description="Stage 5 Event Hubs producer")
    p.add_argument("--stage2-dir", default=DEFAULT_STAGE2_DIR,
                   help="Directory containing Stage 2 stream_*.jsonl files")
    p.add_argument("--position-file", default=DEFAULT_POSITION_FILE)
    p.add_argument("--log-file", default=DEFAULT_LOG_FILE)
    p.add_argument("--poll-interval-s", type=float, default=DEFAULT_POLL_INTERVAL_S,
                   help="Seconds between tail polls (default 2)")
    p.add_argument("--max-batch-bytes", type=int, default=DEFAULT_MAX_BATCH_BYTES,
                   help="Max Event Hubs batch size in bytes (default 900000)")
    args = p.parse_args()

    prod = Producer(args.stage2_dir, args.position_file, args.log_file,
                    args.poll_interval_s, args.max_batch_bytes)

    def _sig(signum, _frame):
        prod.log(f"received signal {signum}; shutdown after current cycle")
        prod.shutdown = True

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    prod.run()
    sys.exit(0)


if __name__ == "__main__":
    main()
