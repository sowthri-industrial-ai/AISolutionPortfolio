#!/usr/bin/env python3
"""F3 close-out regression suite.

Covers the four areas requested for the F3 close-out:

  1. Stage 3 endpoint shape regression  — every route returns the
     expected status + response schema (TestClient, lifespan-loaded).
  2. Perturbation strategy dispatch     — WRITE_STRATEGIES table has all
     four strategy families and every perturbable catalog entry maps to
     a strategy.
  3. Advisory lifecycle                 — create -> list -> reject, and
     create -> approve (enqueues a perturbation), plus double-resolve 409.
  4. NON_PERTURBABLE_OVERRIDES enforcement for Recycle.MaximumIterations
     — rejected at both /setpoints write and /advisories create.

Runs under the F3 venv (Python 3.11) — Stage 3 is DWSIM-free and
streamer.py defers its `clr` imports, so both import cleanly here:

    cd 2.automation/f3
    .venv/bin/python -m pytest test_f3_regression.py -v

Environment is wired at module import time (api.State reads env vars at
class-definition time, so they MUST be set before `import api`). Tag /
setpoint dicts point at the worktree's Phase 0a fixtures; the
perturbation inbox and advisory store are redirected to a throwaway
tempdir so the suite never touches real runtime state.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# --------------------------------------------------------------------------
# Path + env wiring — MUST run before `import api`
# --------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent          # .../2.automation/f3
_AUTOMATION = _HERE.parent                        # .../2.automation
_PROJECT_ROOT = _AUTOMATION.parent                # .../1.RefineryDigitalTwin

_PHASE0A = _PROJECT_ROOT / "3.probes" / "phase0a"
_TAG_DICT = _PHASE0A / "phase0a_tag_dictionary.json"
_SETPOINT_DICT = _PHASE0A / "phase0a_setpoint_dictionary.json"
_STAGE2_DIR = _PROJECT_ROOT / "4.snapshots" / "stage2"

# Throwaway state — never the real inbox / advisory store.
_TMP = Path(tempfile.mkdtemp(prefix="f3_regression_"))
_INBOX = _TMP / "perturbations_inbox"
_ADVISORY_STORE = _TMP / "advisories.json"
_INBOX.mkdir(parents=True, exist_ok=True)

os.environ["TAG_DICT_PATH"] = str(_TAG_DICT)
os.environ["SETPOINT_DICT_PATH"] = str(_SETPOINT_DICT)
os.environ["STAGE2_DIR"] = str(_STAGE2_DIR)
os.environ["PERTURBATION_INBOX"] = str(_INBOX)
os.environ["ADVISORY_STORE_PATH"] = str(_ADVISORY_STORE)

# stage3 (api, perturbations, advisories) + stage2 (streamer) on path.
sys.path.insert(0, str(_AUTOMATION / "stage3"))
sys.path.insert(0, str(_AUTOMATION / "stage2"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import streamer  # noqa: E402  (WRITE_STRATEGIES; clr imports are deferred)
from api import app  # noqa: E402
from perturbations import SetpointCatalog, NON_PERTURBABLE_OVERRIDES  # noqa: E402


RECYCLE_SID = "RECYCLE-REC_012.MaximumIterations"


@pytest.fixture(scope="module")
def client():
    """TestClient with the lifespan run (loads tag dict, ontology,
    setpoint catalog, advisory store)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def catalog():
    return SetpointCatalog(_SETPOINT_DICT)


@pytest.fixture(scope="module")
def a_perturbable(catalog):
    """A perturbable entry with finite numeric bounds + a safe midpoint
    value. Chosen dynamically so the suite survives catalog changes."""
    for e in catalog.list_perturbable():
        b = e.get("bounds") or {}
        lo, hi = b.get("low"), b.get("high")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and hi > lo:
            return {"setpoint_id": e["setpoint_id"], "value": (lo + hi) / 2.0,
                    "low": lo, "high": hi}
    pytest.skip("no perturbable entry with finite numeric bounds in catalog")


# ==========================================================================
# Area 1 — Stage 3 endpoint shape regression
# ==========================================================================


class TestEndpointShapes:
    def test_healthz(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert set(body) >= {"status", "stage2_active"}
        assert body["status"] == "ok"

    def test_snapshots_latest(self, client):
        r = client.get("/snapshots/latest")
        assert r.status_code == 200
        body = r.json()
        for k in ("timestamp", "cycle", "solved", "tags"):
            assert k in body, f"missing {k} in snapshot"
        assert isinstance(body["tags"], dict)

    def test_snapshots_range(self, client):
        # since/until are mandatory ISO 8601 params; the worktree fixture
        # snapshot file is stream_2026-05-10T09.jsonl.
        r = client.get("/snapshots/range", params={
            "since": "2026-05-10T00:00:00Z",
            "until": "2026-05-11T00:00:00Z",
            "limit": 5,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) >= {"count", "truncated", "snapshots"}
        assert isinstance(body["snapshots"], list)

    def test_snapshots_range_missing_params_422(self, client):
        # since/until are required — omitting them is a 422 (contract guard).
        assert client.get("/snapshots/range").status_code == 422

    def test_snapshots_range_bad_timestamp_422(self, client):
        r = client.get("/snapshots/range",
                       params={"since": "not-a-date", "until": "also-bad"})
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "bad_timestamp"

    def test_tags_list(self, client):
        r = client.get("/tags")
        assert r.status_code == 200
        tags = r.json()
        assert isinstance(tags, list) and len(tags) > 0
        sample = tags[0]
        for k in ("tag_id", "owner_tag", "owner_type", "property_key", "category"):
            assert k in sample, f"TagEntry missing {k}"

    def test_tag_get_value_history(self, client):
        tags = client.get("/tags").json()
        tag_id = tags[0]["tag_id"]
        r = client.get(f"/tags/{tag_id}")
        assert r.status_code == 200 and r.json()["tag_id"] == tag_id
        rv = client.get(f"/tags/{tag_id}/value")
        assert rv.status_code == 200
        assert set(rv.json()) >= {"tag_id", "timestamp", "cycle", "value"}
        rh = client.get(f"/tags/{tag_id}/history", params={
            "since": "2026-05-10T00:00:00Z",
            "until": "2026-05-11T00:00:00Z",
            "limit": 3,
        })
        assert rh.status_code == 200, rh.text
        assert set(rh.json()) >= {"tag_id", "count", "points"}

    def test_tag_unknown_404(self, client):
        assert client.get("/tags/NOPE-X.Y").status_code == 404

    def test_ontology_routes(self, client):
        assert client.get("/ontology/schema").status_code == 200
        ents = client.get("/ontology/entities")
        assert ents.status_code == 200 and isinstance(ents.json(), list)
        assert len(ents.json()) > 0
        eid = ents.json()[0]["id"]
        d = client.get(f"/ontology/entities/{eid}")
        assert d.status_code == 200
        assert "inbound_relationships" in d.json()
        res = client.get("/ontology/resolve", params={"term": "column"})
        assert res.status_code == 200
        assert set(res.json()) >= {"term", "count", "results"}

    def test_openapi_has_f3_routes(self, client):
        spec = client.get("/openapi.json").json()
        for p in ("/setpoints/{setpoint_id}/value", "/advisories",
                  "/advisories/{advisory_id}/approve",
                  "/advisories/{advisory_id}/reject"):
            assert p in spec["paths"], f"openapi missing {p}"

    def test_setpoint_write_valid_shape(self, client, a_perturbable):
        r = client.post(
            f"/setpoints/{a_perturbable['setpoint_id']}/value",
            json={"value": a_perturbable["value"], "requested_by": "regression"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("request_id", "setpoint_id", "queued_value", "status",
                  "enqueued_at"):
            assert k in body, f"SetpointWriteResponse missing {k}"
        assert body["status"] == "queued"

    def test_setpoint_write_unknown_404(self, client):
        r = client.post("/setpoints/NOPE-X.Y/value", json={"value": 1.0})
        assert r.status_code == 404

    def test_setpoint_write_out_of_bounds_422(self, client, a_perturbable):
        r = client.post(
            f"/setpoints/{a_perturbable['setpoint_id']}/value",
            json={"value": a_perturbable["high"] + abs(a_perturbable["high"]) + 1e6},
        )
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "validation_failed"


# ==========================================================================
# Area 2 — Perturbation strategy dispatch (all four strategies)
# ==========================================================================


class TestStrategyDispatch:
    EXPECTED_FAMILIES = {"reflection", "reflection_int", "calc_mode", "column_spec"}

    def test_all_four_strategy_families_present(self):
        families = {v[0] for v in streamer.WRITE_STRATEGIES.values()}
        missing = self.EXPECTED_FAMILIES - families
        assert not missing, f"strategy families absent from table: {missing}"

    @pytest.mark.parametrize(
        "key,expected_family",
        [
            (("Pump", "Efficiency"), "reflection"),
            (("Recycle", "MaximumIterations"), "reflection_int"),
            (("Heater", "OutletTemperature"), "calc_mode"),
            (("DistillationColumn", "RefluxRatio"), "column_spec"),
        ],
    )
    def test_representative_mappings(self, key, expected_family):
        assert key in streamer.WRITE_STRATEGIES, f"{key} absent from table"
        assert streamer.WRITE_STRATEGIES[key][0] == expected_family

    def test_every_perturbable_has_a_strategy(self, catalog):
        """Cross-reference: each perturbable catalog entry must have a
        WRITE_STRATEGIES entry, else a runtime write would fail with
        'no strategy'. This is the regression that protects the demo."""
        gaps = []
        for e in catalog.list_perturbable():
            key = (e["owner_type"], e["property_key"])
            if key not in streamer.WRITE_STRATEGIES:
                gaps.append(e["setpoint_id"])
        assert not gaps, f"perturbable setpoints with no write strategy: {gaps}"

    def test_calc_mode_params_are_ints(self):
        """calc_mode strategy params are the DWSIM CalcMode enum int —
        guard against a regression that drops the int param."""
        for key, val in streamer.WRITE_STRATEGIES.items():
            if val[0] == "calc_mode":
                assert isinstance(val[1], int), f"{key} calc_mode param not int: {val}"


# ==========================================================================
# Area 3 — Advisory lifecycle
# ==========================================================================


class TestAdvisoryLifecycle:
    def test_create_list_reject(self, client, a_perturbable):
        sid = a_perturbable["setpoint_id"]
        c = client.post("/advisories", json={
            "setpoint_id": sid,
            "target_value": a_perturbable["value"],
            "rationale": "regression: create->list->reject",
            "created_by": "regression",
        })
        assert c.status_code == 201, c.text
        adv = c.json()
        assert adv["state"] == "pending"
        aid = adv["advisory_id"]

        lst = client.get("/advisories")
        assert lst.status_code == 200
        assert any(a["advisory_id"] == aid for a in lst.json())

        flt = client.get("/advisories", params={"state": "pending"})
        assert any(a["advisory_id"] == aid for a in flt.json())

        rej = client.post(f"/advisories/{aid}/reject",
                          json={"rejected_by": "regression",
                                "reason": "not needed"})
        assert rej.status_code == 200, rej.text
        assert rej.json()["state"] == "rejected"

        # double-resolve -> 409
        again = client.post(f"/advisories/{aid}/reject", json={})
        assert again.status_code == 409

    def test_create_approve_enqueues_perturbation(self, client, a_perturbable):
        sid = a_perturbable["setpoint_id"]
        c = client.post("/advisories", json={
            "setpoint_id": sid,
            "target_value": a_perturbable["value"],
            "rationale": "regression: create->approve",
            "created_by": "regression",
        })
        assert c.status_code == 201, c.text
        aid = c.json()["advisory_id"]

        before = len(list(_INBOX.glob("*.json")))
        ap = client.post(f"/advisories/{aid}/approve",
                         json={"approved_by": "regression"})
        assert ap.status_code == 200, ap.text
        body = ap.json()
        assert body["state"] == "approved"
        assert body.get("perturbation_request_id"), "approve didn't set request id"

        after = len(list(_INBOX.glob("*.json")))
        assert after == before + 1, "approve did not enqueue an inbox file"

        again = client.post(f"/advisories/{aid}/approve", json={})
        assert again.status_code == 409

    def test_advisory_unknown_404(self, client):
        assert client.post("/advisories/nope/approve", json={}).status_code == 404
        assert client.post("/advisories/nope/reject", json={}).status_code == 404


# ==========================================================================
# Area 4 — NON_PERTURBABLE_OVERRIDES enforcement (Recycle.MaximumIterations)
# ==========================================================================


class TestNonPerturbableOverride:
    def test_override_registered(self):
        assert ("Recycle", "MaximumIterations") in NON_PERTURBABLE_OVERRIDES

    def test_catalog_marks_recycle_non_perturbable(self, catalog):
        e = catalog.get(RECYCLE_SID)
        assert e is not None, f"{RECYCLE_SID} should still be in the read catalog"
        assert e["perturbable"] is False
        assert e.get("non_perturbable_reason"), "reason not stamped on entry"

    def test_recycle_excluded_from_perturbable_list(self, catalog):
        ids = {e["setpoint_id"] for e in catalog.list_perturbable()}
        assert RECYCLE_SID not in ids

    def test_setpoint_write_rejected_422(self, client):
        r = client.post(f"/setpoints/{RECYCLE_SID}/value", json={"value": 60})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["error"] == "validation_failed"
        assert detail["perturbable"] is False
        assert "re-initialises" in detail["reason"] or "perturbable" in detail["reason"]

    def test_advisory_create_rejected_422(self, client):
        r = client.post("/advisories", json={
            "setpoint_id": RECYCLE_SID,
            "target_value": 60,
            "rationale": "should be rejected by override",
        })
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "validation_failed"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
