# Roadmap

This is the week-by-week view of the project. It complements the
charter (which is structural) with a temporal view (when things
happen, what depends on what).

This roadmap will be wrong by Week 2. That's expected — we revise it
at every phase boundary based on what we actually learned. The shape
stays; the dates flex.

---

## Week 1 — Phase 0: Foundation

**Theme:** Get the cloud GPU working with Omniverse Kit booting headlessly.

**Days 1-2: Lambda Labs + system prep**

- Provision Lambda Labs A6000, SSH-accessible
- Install system dependencies: Vulkan loader/ICD, X server stack (Xvfb, x11vnc, novnc, websockify), build tools, Python 3.10+
- Install Docker (for the data fabric in Phase 3)
- Set up SSH config locally with the instance as a named host for fast reconnect
- Initialize OPERATOR_RUNBOOK.md with everything done so far

**Days 3-4: Omniverse Kit App Template**

- Clone kit-app-template
- `./repo.sh template new` to create a base editor app
- `./repo.sh build` — first build is 15-30 min, mostly downloads
- Boot via `./repo.sh launch` under Xvfb
- Verify Kit log shows clean startup, no fatal errors

**Day 5: VNC + visual verification**

- Configure x11vnc against the Xvfb display
- Tunnel VNC through SSH to local Mac
- See Kit window in Safari/Chrome on Mac
- Take screenshot of Kit running headlessly on cloud GPU
- Phase 0 snapshot taken
- **End of Phase 0 — gate review with architect.**

---

## Week 2 — Phase 1: CDU scene in Kit

**Theme:** Make the asset library output render with RTX in Kit.

**Days 6-7: Asset library on the cloud instance**

- Clone `refinery-usd-asset-library` repo
- Create venv, install usd-core + deps
- Run the build, produce `out/cdu1/CDU1.usda` (we know this works — it ran in Phase 1.2 of the original backlog on the Mac)
- Tour the resulting USD with Kit's content browser

**Days 8-9: Stage loading + RTX**

- Open `CDU1.usda` in the Kit base-editor
- Verify all 51 prims load
- Confirm RTX path tracing renders the geometry
- Switch between RTX-Real-Time and RTX-Interactive (Path Tracing) modes
- Save camera bookmarks: wide, AtmColumn close, equipment row
- Apply at least one MDL material (e.g., brushed steel) to the column shell

**Day 10: Polish + snapshot**

- Document any quirks in OPERATOR_RUNBOOK
- Phase 1 snapshot taken
- **End of Phase 1 — gate review.**

---

## Week 3 — Phase 2: Custom extension

**Theme:** The CDU twin extension loads as a real, registered, usable Kit extension.

**Days 11-12: Extension scaffolding from existing repo**

- Copy `cdu-digital-twin/exts/com.yourname.cdutwin/` from existing portfolio to cloud instance
- Adjust `extension.toml` for current Kit version
- Configure Kit's extension search path to include the dev folder
- Restart Kit, verify extension appears in Extensions panel
- Toggle ON; resolve any namespace package errors

**Days 13-15: Panel UI**

- Verify `omni.ui` panel renders with current Kit
- All buttons exist, click handlers wired (no live data yet — just logging)
- Tag table widget renders an empty state cleanly
- Window menu → Refinery → CDU Twin Panel works

**Days 16-17: Polish + dependencies**

- Identify which Python packages need to be installed into Kit's bundled Python (aiohttp at minimum, possibly httpx as alternative)
- Document the install procedure in OPERATOR_RUNBOOK
- Test Kit shutdown and restart with extension enabled — must survive cleanly
- Phase 2 snapshot taken
- **End of Phase 2 — gate review.**

---

## Week 4 — Phase 3: Live data binding

**Theme:** Data fabric runs as sidecar; extension subscribes; values flow into USD; disturbance demoable.

**Days 18-19: Data fabric as systemd service**

- Move `live_dashboard.py` and `live_demo.py` from working-demo to the new `refinery-data-fabric` repo
- Write systemd unit file for the fabric service
- Configure service to restart on failure
- Verify `curl http://localhost:8765/stream` returns SSE events at 2 Hz
- Add `python -m refinery_data_fabric` entrypoint as a CLI

**Days 20-22: Extension subscription**

- Modify `live_binding.py` in the extension to subscribe to the SSE stream
- On Connect: open SSE connection, parse events, populate tag table
- On Disconnect: close cleanly
- Per event: walk USD stage to find prim by ISA-95 path, write `cdu:liveValue` custom attribute
- Verify in Kit's USD inspector that values are landing on prims

**Days 23-24: Disturbance + HUD**

- Wire the panel's "Trigger Disturbance" button to a fabric API endpoint that fires the simulator's furnace upset
- Verify PT-201 and TT-205 visibly drift in panel and on prim attributes
- (Stretch within phase) Add a viewport HUD showing current AtmColumn pressure as a 3D label
- Phase 3 snapshot taken — **headline demo complete**
- **End of Phase 3 — gate review.**

---

## Weeks 5-6 — Phase 4: Isaac Sim scenarios

**Theme:** Isaac Sim works alongside Kit; gas leak and rover scenarios run; valve is stretch.

**Days 25-27: Isaac Sim install**

- Download Isaac Sim 4.x for Linux from NVIDIA developer portal (requires NGC auth)
- Install natively on the same instance as Kit (separate Python environment)
- Verify standalone smoke test: launch Isaac Sim, load a sample scene
- Document how to switch between Kit-twin-app and Isaac-Sim workflows in OPERATOR_RUNBOOK

**Days 28-32: Gas leak dispersion**

- Move `gas_leak_dispersion.py` from existing `refinery-flow-safety-twin` to new `refinery-isaac-scenarios` repo
- Replace placeholder Flow API calls with real `omni.flowusd` calls
- Author a `usd_layouts/ras_tanura_cdu1_outdoor.usda` that sublayers the asset library output and adds Flow simulation domain
- Configure emitter at `/Aramco/RasTanura/CDU1/AtmColumn/PSV-201`
- Tune Flow parameters: emission rate, temperature, advection wind
- Run for 60 simulated seconds, verify plume renders, CSV is written
- Document parameter calibration limits in `docs/scenarios.md`

**Days 33-37: Inspection rover**

- Move `inspection_rover.py` to new repo
- Source a rover USD: easiest path is the bundled Carter robot from Isaac Sim assets
- Compose with the CDU outdoor stage (rover at piperack origin)
- Replace placeholder articulation with real Articulation wrapper
- Wire ROS 2 bridge: `/odom`, `/scan`, `/camera/*` topics published
- Implement waypoint follower using either teleport-to-waypoint (simple) or Nav2 (real)
- Run the YAML route from existing repo, verify dwells happen, summary file is written

**Days 38-40: Valve stretch + Phase 4 close**

- (If time permits) Move `valve_actuator_physics.py`, replace closed-form ODE with PhysX articulation
- Phase 4 snapshot taken
- **End of Phase 4 — gate review.**

---

## Week 7 — Phase 5: Polish, snapshot, repos

**Theme:** Ship it.

**Days 41-43: Repos**

- Create five GitHub repos (or refactor existing portfolio into them)
- Push final code, verified to match what runs on the cloud instance
- READMEs accurate, architecture diagrams render correctly
- Each repo has its own quickstart that points at the operator runbook for full deployment

**Days 44-45: Recording + final snapshot**

- Record 90-second video using `ffmpeg -f x11grab` on the cloud instance
- Edit lightly (cuts, no narration; narration is live in interview)
- Embed in `refinery-twin` meta repo README
- Final snapshot taken — interview-ready
- Test snapshot restore: spin up fresh instance from snapshot, verify demo works end-to-end

**Days 46-47: Buffer + interview prep**

- Resolve any issues from the snapshot restore test
- Rehearse the demo five times; record each
- Prepare answers to likely questions (we'll write these together)
- **Project complete.**

---

## Phase gates — what they are, why they exist

At the end of each phase, work stops. We do three things:

1. **Verify the DoD checklist for that phase.** Every box ticked, with evidence.
2. **Test on a fresh instance.** Tear down what's running, spin up a fresh A6000, follow the runbook, see the phase's deliverable work end-to-end. This catches "works on my machine" drift, which is the most common failure mode.
3. **Architect review.** I review what got built, the runbook update, the decisions made. Anything ambiguous gets cleared up before Phase N+1 starts.

Skipping a phase gate is the single highest-risk thing in this project. A drifted Phase 2 ruins Phase 3, which ruins Phase 4. Catch it at the gate or pay 10x to fix it later.

---

## Risk register

Top risks, ranked by likelihood × impact:

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Vulkan/driver mismatch breaks Kit on first install | Medium | High | Try a Lambda image known to work with current Kit; if not, switch to AWS g5 with Deep Learning AMI |
| Isaac Sim Python environment conflicts with Kit | High | Medium | Run them as separate workflows, not in the same process. Document switch-between in runbook |
| Flow extension API changed in current Kit version | Medium | Medium | Pin Kit version; if API drift, fall back to PhysX particles for the gas leak |
| ROS 2 setup on Ubuntu 22.04 fights with Isaac Sim's bundled ROS | Medium | Medium | Use Isaac Sim's bundled ROS bridge, do not try to install system ROS 2 |
| Snapshot launch from cold takes >10 min | Low | Medium | Profile, optimize boot scripts; pre-warm kit shaders |
| Owner burnout in Week 4-5 | Medium | High | Sundays off enforced; daily check-ins flag exhaustion |
| NGC account or Lambda access blocked | Low | Critical | Have AWS g5 fallback plan documented before starting |

---

## Decision points coming up

These are decisions we deliberately defer to the moment we have evidence to make them well:

- **End of Phase 0:** Is Kit version X compatible with the existing extension scaffold from the original portfolio? Decision: keep the scaffold or rewrite for current Kit.
- **End of Phase 2:** Should the data fabric be containerized (Docker) for the systemd unit, or run as a venv-based service? Decision: depends on how Kit's bundled Python plays with our Python.
- **Mid Phase 4:** Is Isaac Sim 4.x stable enough on Ubuntu 22.04 for our use case, or do we need to switch to Ubuntu 20.04? Decision: validated by smoke test on day 25-26.
- **End of Phase 4:** Is the valve actuator scenario worth the time, or should that time go to polish and rehearsal? Decision: depends on Phase 4 progress to date.

---

**Roadmap end.**
