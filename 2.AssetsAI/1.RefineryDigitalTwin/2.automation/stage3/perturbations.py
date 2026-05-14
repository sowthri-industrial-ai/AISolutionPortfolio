#!/usr/bin/env python3
"""Stage 3 — Perturbation infrastructure.

Bridges HTTP setpoint writes (Stage 3 process) to DWSIM property mutations
(Stage 2 process) via a per-file inbox queue. Stage 3 produces JSON
request files; Stage 2 consumes them at the start of each solve cycle
(see streamer.py `_drain_perturbation_inbox`).

Inbox protocol (filesystem as IPC):

    <inbox_dir>/<uuid>.json            ← pending (just-enqueued)
    <inbox_dir>/<uuid>.json.tmp        ← transient (atomic-rename source)
    <inbox_dir>/<uuid>.applied         ← Stage 2 consumed + wrote successfully
    <inbox_dir>/<uuid>.failed          ← Stage 2 tried but DWSIM raised / refused

All transitions are atomic via temp-file + os.rename. Crash-safe in either
direction (Stage 3 mid-enqueue or Stage 2 mid-archive).

Setpoint identification uses the same canonical scheme as tag_ids:
    <owner_prefix>-<NORMALIZED_OWNER_TAG>.<property_key>
e.g.   COL-DISTILLATION_COLUMN.RefluxRatio
       HC-THERMAL_OIL_HEATING.OutletTemperature
       RECYCLE-REC_012.MaximumIterations

Validation gate per the F3 Q3 default (b): perturbable-list membership
AND bounds check from Phase 0a's setpoint_dictionary.json.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Phase 0a Q1 normalization (verbatim): non-alphanumeric → '_', collapse
# runs, strip ends, uppercase.
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
_RUN_UNDER = re.compile(r"_+")

# owner_type → entity-id prefix. Matches the tag_dictionary's prefix
# mapping exactly so setpoint_ids share the namespace with tag_ids.
_OWNER_TYPE_PREFIX = {
    "DistillationColumn": "COL",
    "Heater":             "HC",
    "Pump":               "PMP",
    "Recycle":            "RECYCLE",
    "Tank":               "TANK",
    "MaterialStream":     "MS",
    "EnergyStream":       "ES",
}


def _normalize_tag(s: str) -> str:
    s = _NON_ALNUM.sub("_", s or "")
    return _RUN_UNDER.sub("_", s).strip("_").upper()


def make_setpoint_id(owner_type: str, owner_tag: str, property_key: str) -> str:
    prefix = _OWNER_TYPE_PREFIX.get(owner_type, "UNK")
    return f"{prefix}-{_normalize_tag(owner_tag)}.{property_key}"


# (owner_type, property_key) → reason. Catalog-level override for entries
# that *look* perturbable from the Phase 0a dictionary (numeric + bounds)
# but in practice cannot be perturbed at runtime — usually because DWSIM
# re-initialises them from configured state on each solve, so a write
# succeeds for one read and then reverts. Keep these in the read catalog
# (the tag still surfaces in /tags + /setpoints) but reject any write
# attempt with HTTP 422 and the documented reason.
#
# Add entries here when an empirical probe confirms write-then-revert and
# the reset is structural inside DWSIM (i.e. not fixable from our side).
NON_PERTURBABLE_OVERRIDES: dict[tuple[str, str], str] = {
    ("Recycle", "MaximumIterations"): (
        "DWSIM's Recycle block re-initialises MaximumIterations from its "
        "configured state at the start of every solve cycle. The reflection "
        "write persists for one read (verified at commit 8425d49: "
        "persisted_through_solve=true, immediate=60, post-solve=60), but "
        "subsequent cycles reset to the configured value (50). Treat as "
        "read-only at runtime. To raise the cap, edit the .dwxmz substrate "
        "directly and reload."
    ),
}


def utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class SetpointCatalog:
    """Loads setpoint_dictionary.json once at startup. Two roles:
      - `get(setpoint_id)`        → entry dict or None
      - `validate_write(...)`     → bounds-checked accept/reject decision

    Indices built at load:
      - `by_id`: setpoint_id → entry (with `setpoint_id` field added)
    """

    def __init__(self, dict_path: Path):
        self.dict_path = Path(dict_path)
        with open(self.dict_path) as f:
            entries = json.load(f)
        self.by_id: dict[str, dict] = {}
        for e in entries:
            sid = make_setpoint_id(e["owner_type"], e["owner_tag"], e["property_key"])
            entry = dict(e, setpoint_id=sid)
            override_key = (entry.get("owner_type"), entry.get("property_key"))
            override_reason = NON_PERTURBABLE_OVERRIDES.get(override_key)
            if override_reason is not None:
                # Flip perturbable → False and stamp the reason so downstream
                # consumers (validate_write, /setpoints listings, MCP tool
                # surfaces) can explain WHY this read-only entry is read-only.
                entry["perturbable"] = False
                entry["non_perturbable_reason"] = override_reason
            self.by_id[sid] = entry

    def get(self, setpoint_id: str) -> Optional[dict]:
        return self.by_id.get(setpoint_id)

    def list_perturbable(self) -> list[dict]:
        return [e for e in self.by_id.values() if e.get("perturbable") is True]

    def validate_write(
        self, setpoint_id: str, value: Any
    ) -> tuple[bool, Optional[str], Optional[dict]]:
        """Returns (ok, error_reason, entry). On success error_reason is None.
        On failure: entry is None if setpoint_id is unknown, else the entry."""
        entry = self.by_id.get(setpoint_id)
        if entry is None:
            return False, f"unknown setpoint_id: {setpoint_id!r}", None
        if not entry.get("perturbable"):
            override_reason = entry.get("non_perturbable_reason")
            if override_reason:
                return False, (
                    f"setpoint is not perturbable: {override_reason}"
                ), entry
            return False, (
                f"setpoint is not perturbable "
                f"(bounds_kind={entry.get('bounds_kind')!r})"
            ), entry
        # bool is a subclass of int — explicit reject to avoid silent coercion
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False, f"value must be numeric, got {type(value).__name__}", entry
        bounds = entry.get("bounds") or {}
        low = bounds.get("low")
        high = bounds.get("high")
        if low is not None and value < low:
            return False, f"value {value} below lower bound {low}", entry
        if high is not None and value > high:
            return False, f"value {value} above upper bound {high}", entry
        return True, None, entry


class InboxWriter:
    """Writes setpoint perturbation requests to the Stage 2 inbox directory
    as one JSON file per request. Atomic via temp-file + os.rename.

    Discovery: Stage 2 globs `<inbox_dir>/*.json` at cycle start.
    """

    def __init__(self, inbox_dir: Path):
        self.inbox_dir = Path(inbox_dir)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

    def enqueue(self, request: dict) -> str:
        """Write request to inbox atomically. Mutates request to add
        request_id + enqueued_at; returns request_id."""
        request_id = str(uuid.uuid4())
        request["request_id"] = request_id
        request.setdefault("enqueued_at", utc_iso())
        target = self.inbox_dir / f"{request_id}.json"
        tmp = self.inbox_dir / f"{request_id}.json.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(request, f, indent=2, ensure_ascii=False)
        os.rename(tmp, target)
        return request_id

    def status(self, request_id: str) -> Optional[dict]:
        """Look up current state of a request. Returns one of:
            None                                — not found
            {... , "status": "pending"}         — sitting in inbox
            {... , "status": "applied", ...}    — Stage 2 wrote successfully
            {... , "status": "failed", ...}     — Stage 2 refused / DWSIM raised
        """
        for suffix, status in (
            (".applied", "applied"),
            (".failed", "failed"),
            (".json", "pending"),
        ):
            p = self.inbox_dir / f"{request_id}{suffix}"
            if p.is_file():
                with open(p) as f:
                    data = json.load(f)
                data["status"] = status
                return data
        return None

    def list_recent(self, limit: int = 50) -> list[dict]:
        """Return up to `limit` recent entries (pending + applied + failed),
        newest-first by file mtime."""
        items: list[tuple[float, str, Path]] = []
        for p in self.inbox_dir.iterdir():
            if not p.is_file():
                continue
            if p.suffix == ".applied":
                status = "applied"
            elif p.suffix == ".failed":
                status = "failed"
            elif p.suffix == ".json" and not p.name.endswith(".json.tmp"):
                status = "pending"
            else:
                continue
            try:
                mt = p.stat().st_mtime
            except OSError:
                continue
            items.append((mt, status, p))
        items.sort(key=lambda t: t[0], reverse=True)
        out: list[dict] = []
        for _, status, p in items[:limit]:
            try:
                with open(p) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            data["status"] = status
            out.append(data)
        return out
