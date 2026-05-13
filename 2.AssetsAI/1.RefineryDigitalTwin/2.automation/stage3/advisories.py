#!/usr/bin/env python3
"""Stage 3 — Advisory queue + lifecycle.

Agent (via MCP) calls `recommend_action(setpoint_id, target_value, rationale)`
to create a pending advisory. Operator reviews via the REPL or HTTP, then
approves (which enqueues a perturbation into Stage 2's inbox via the same
InboxWriter used by direct setpoint writes) or rejects.

State persistence (Q2 default — single JSON file, atomic per-mutation
write). Loaded once on startup; survives Stage 3 restart. Right scale
for tens of advisories.

Validation: advisory creation goes through the same SetpointCatalog gate
as direct POST /setpoints/{id}/value (perturbable-list membership + bounds
check). Stops the agent from queuing recommendations the operator can
never approve.

States: pending → approved | rejected (both terminal). Never auto-expire
(Q4 default — operator manages the queue).
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Optional

from perturbations import SetpointCatalog, InboxWriter, utc_iso


class AdvisoryStore:
    """JSON-backed advisory queue. All mutations write through to disk
    atomically (tmp+rename)."""

    def __init__(
        self,
        store_path: Path,
        catalog: SetpointCatalog,
        inbox_writer: InboxWriter,
    ):
        self.store_path = Path(store_path)
        self.catalog = catalog
        self.inbox_writer = inbox_writer
        self.advisories: dict[str, dict] = {}
        self._load()

    # ---- Persistence ----

    def _load(self) -> None:
        if not self.store_path.is_file():
            self.advisories = {}
            return
        try:
            with open(self.store_path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.advisories = data
            else:
                # Old shape would be a list; coerce to keyed dict.
                self.advisories = {a["advisory_id"]: a for a in data}
        except (json.JSONDecodeError, OSError) as e:
            print(
                f"[stage3] WARN: advisories file unreadable ({e}); starting fresh",
                flush=True,
            )
            self.advisories = {}

    def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.advisories, f, indent=2, ensure_ascii=False)
        os.rename(tmp, self.store_path)

    # ---- Public API ----

    def create(
        self,
        setpoint_id: str,
        target_value: float,
        rationale: str,
        created_by: str,
    ) -> tuple[Optional[dict], Optional[str], Optional[dict]]:
        """Create a pending advisory. Validates the setpoint write would be
        accepted by Stage 3's perturbation gate; returns the validation
        error reason if not.

        Returns (advisory, error_reason, setpoint_entry). On success
        error_reason is None and setpoint_entry is the validated entry.
        On failure: advisory is None; entry is None iff setpoint_id was
        unknown (caller uses this to distinguish 404 from 422).
        """
        ok, err, entry = self.catalog.validate_write(setpoint_id, target_value)
        if not ok:
            return None, err, entry
        advisory_id = str(uuid.uuid4())
        advisory = {
            "advisory_id": advisory_id,
            "setpoint_id": setpoint_id,
            "target_value": target_value,
            "rationale": rationale,
            "state": "pending",
            "created_at": utc_iso(),
            "created_by": created_by,
            "approved_at": None,
            "approved_by": None,
            "rejected_at": None,
            "rejected_by": None,
            "rejected_reason": None,
            "perturbation_request_id": None,
        }
        self.advisories[advisory_id] = advisory
        self._save()
        return advisory, None, entry

    def get(self, advisory_id: str) -> Optional[dict]:
        return self.advisories.get(advisory_id)

    def list(self, state: Optional[str] = None) -> list[dict]:
        items = list(self.advisories.values())
        if state:
            items = [a for a in items if a.get("state") == state]
        # Newest-first by created_at.
        items.sort(key=lambda a: a.get("created_at", ""), reverse=True)
        return items

    def approve(
        self, advisory_id: str, approved_by: str = "operator"
    ) -> tuple[Optional[dict], Optional[str], Optional[int]]:
        """Approve a pending advisory: enqueue perturbation, mark
        approved, persist.

        Returns (advisory, error_reason, suggested_http_status):
            (adv, None, None)              success
            (None, "advisory_not_found",  404)
            (None, "already in state X",  409)
            (None, "validation_failed: X", 422)  if catalog has changed
        """
        adv = self.advisories.get(advisory_id)
        if adv is None:
            return None, "advisory_not_found", 404
        if adv["state"] != "pending":
            return None, f"advisory already in state {adv['state']!r}", 409
        # Re-validate at approve time — catalog could have changed if
        # setpoint_dictionary.json got reloaded (rare, but cheap to guard).
        ok, err, entry = self.catalog.validate_write(
            adv["setpoint_id"], adv["target_value"]
        )
        if not ok or entry is None:
            return None, f"validation_failed: {err}", 422
        req = {
            "setpoint_id": adv["setpoint_id"],
            "owner_tag": entry["owner_tag"],
            "owner_type": entry["owner_type"],
            "property_key": entry["property_key"],
            "value": adv["target_value"],
            "requested_by": f"advisory:{advisory_id}",
        }
        request_id = self.inbox_writer.enqueue(req)
        adv["state"] = "approved"
        adv["approved_at"] = utc_iso()
        adv["approved_by"] = approved_by
        adv["perturbation_request_id"] = request_id
        self._save()
        return adv, None, None

    def reject(
        self,
        advisory_id: str,
        rejected_by: str = "operator",
        reason: Optional[str] = None,
    ) -> tuple[Optional[dict], Optional[str], Optional[int]]:
        """Reject a pending advisory; no perturbation enqueued. Returns
        the same shape as approve()."""
        adv = self.advisories.get(advisory_id)
        if adv is None:
            return None, "advisory_not_found", 404
        if adv["state"] != "pending":
            return None, f"advisory already in state {adv['state']!r}", 409
        adv["state"] = "rejected"
        adv["rejected_at"] = utc_iso()
        adv["rejected_by"] = rejected_by
        adv["rejected_reason"] = reason
        self._save()
        return adv, None, None

    def pending_count(self) -> int:
        return sum(1 for a in self.advisories.values() if a.get("state") == "pending")
