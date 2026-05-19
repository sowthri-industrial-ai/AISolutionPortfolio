# Project Charter — Refinery Twin (Omniverse + Isaac Sim)

**Status:** Locked. This document is binding. Changes require explicit
charter revision.
**Owner:** [your name]
**Started:** see git log of this file
**Target completion:** snapshot-ready by end of Phase 5

---

## 1. What this project is

A real working **NVIDIA Omniverse Kit application** for a refinery
Crude Distillation Unit, with live process data binding from a
Kafka-style event bus, and a set of **NVIDIA Isaac Sim scenarios**
covering safety and inspection use cases. Hosted on a cloud GPU,
demoed by the project owner via screen-share, with a saved instance
snapshot for replay.

The deliverable shape:

- All source code in well-organized GitHub repositories (public)
- A working instance on a cloud GPU, captured as a snapshot
- An operator runbook in the repo so the build knowledge isn't trapped on the server
- A short marketing video embedded in the repo README (recorded as a smoke test, not as the primary artifact)

This is a personal, controlled demo. It is **not** a public deployable.

---

## 2. Why this scope, why this shape

The owner is preparing for a senior NVIDIA Omniverse / Digital Twin
Architect role. The project must demonstrate, end to end:

- USD authoring at industrial scale, ISA-95-aligned
- Custom Omniverse Kit extension development
- Live data integration from process control (OPC UA-style)
- PhysX-based rigid body and articulation simulation (Isaac Sim)
- NVIDIA Flow volumetric simulation for hazard analysis
- Production-grade Python on Linux

The owner walks the interviewer through the running system. This format
favors interactivity over polish — a reviewer can pause, ask "what
happens if you change this," see the answer in real time. That's a
stronger artifact than a recorded video for this audience.

---

## 3. In scope (binding)

### 3.1 Geometric and metadata layer

- **One refinery unit:** Crude Distillation Unit at Ras Tanura (CDU1)
- **Five pieces of equipment:** atmospheric column, shell-and-tube exchanger, centrifugal pump, two storage tanks
- **Three-layer USD composition:** geometry, state, annotation
- **ISA-95 hierarchy** as the canonical asset path: `Aramco/RasTanura/CDU1/...`
- **OPC UA tag binding** as a custom API schema applied to equipment prims
- **10 process tags** spanning flow, temperature, pressure, level, analyzer types

### 3.2 Application layer (Omniverse Kit)

- A custom Kit extension `com.<owner>.cdutwin` that loads at app startup
- Extension panel with live tag table, scene controls, and disturbance trigger button
- Live binding from a sidecar data fabric service into USD attributes (Fabric write path)
- Disturbance scenario: furnace COT upset, propagating to overhead pressure and tray-5 temperature, visible in the viewport

### 3.3 Physics + sensor layer (Isaac Sim)

Two scenarios mandatory, one stretch:

- **Mandatory: Gas leak dispersion** at PSV-201 using NVIDIA Flow, configurable wind field, recorded concentration field
- **Mandatory: Inspection rover patrol** using PhysX articulations + ROS 2 bridge, route YAML driven, dwelling at instrument waypoints
- **Stretch: Valve actuator failure modes** using PhysX articulation, three named modes (healthy / stem-seizure / partial-stroke) with closure-time CSV output

### 3.4 Data layer (sidecar service)

- Process simulator producing realistic correlated CDU dynamics (the existing `live_demo.py` engine)
- In-memory event bus with Kafka-shaped semantics
- HTTP/SSE endpoint for the Kit extension to subscribe to
- 10 tags streaming at 2 Hz minimum

### 3.5 Deployment shape

- Cloud GPU instance on Lambda Labs (or equivalent: AWS g5, Azure NV)
- Ubuntu 22.04 LTS
- Containerized services where it improves reproducibility (data fabric, optional)
- Omniverse Kit + Isaac Sim run on the host, not in containers (this is the standard NVIDIA-recommended deployment)
- Saved snapshot at the end of Phase 5 so the demo is replayable

### 3.6 Documentation

- `README.md` per repo, with quickstart and architecture summary
- `docs/architecture.md` per repo, with deeper design rationale
- **`OPERATOR_RUNBOOK.md`** — the cumulative knowledge base. Every solved problem, every working command, every gotcha gets written here. This file is the project's most valuable durable artifact.
- 90-second screen recording of the running system, embedded in the headline repo

---

## 4. Non-goals (binding)

The following are explicitly out of scope. Any proposal to add them
mid-project must be rejected. They are deferred to a hypothetical
future Phase 7+ that we are not committing to.

- ❌ **No public URL or live streaming** to arbitrary visitors. No WebRTC, no Kit Streaming, no Omniverse Streaming Client setup, no nginx reverse-proxy that exposes the Kit viewport.
- ❌ **No reviewer-runs-it-themselves Tier 2** deployment. No Terraform, no Ansible playbooks for third parties, no "lift and start" from a fresh AWS account.
- ❌ **No Plant Simulation gRPC integration.** The proto file in the existing repo stays as architectural design only. No Tecnomatix license, no COM interop, no Windows VM in the cloud.
- ❌ **No Kafka cluster.** The in-memory bus is the data fabric for this project. Kafka migration is Phase 7+.
- ❌ **No additional refinery units.** No FCC, no hydrocracker, no reformer. Just the CDU.
- ❌ **No additional fault scenarios** beyond the furnace upset (operator twin) and the three Isaac Sim scenarios.
- ❌ **No CI/CD pipeline.** Manual build, manual deploy, manual snapshot.
- ❌ **No alarms, CMMS, logbook, vibration, CEMS** integration. Process tags only.
- ❌ **No web UI** beyond the existing browser dashboard from the working-demo.
- ❌ **No third Isaac Sim scenario** (valve actuator) as critical path. It's a stretch goal at the end of Phase 4 only.
- ❌ **No new architectural ideas mid-project.** Scope creep dies here. Anything new goes into the parking lot.

---

## 5. Architectural principles (binding)

These are the load-bearing principles. Every design decision must
trace back to one of these. If a proposed change violates a principle,
the change loses.

1. **Real software, not scaffolding pretending to be implementation.** Every line of code that exists, runs. Every claim in the README, demonstrable. Every architecture diagram, accurate. No structurally-correct-but-never-executed placeholders.

2. **Working software at the end of every phase.** Phase N+1 makes Phase N's thing better; it does not replace it with a different thing. We do not have a "Phase 7 where it all comes together."

3. **Verify on a fresh instance at every phase boundary.** Tear down the cloud instance, spin up a fresh one, follow the runbook, see it work. This catches "works on my machine" drift, which is how these projects fail to actually deploy.

4. **Configuration over code, YAML contracts.** Anything tunable lives in YAML so the source code stays stable. The mapping of OPC UA tags to USD prims is YAML. Wind speed and direction is YAML. Furnace COT setpoint is YAML.

5. **Three-layer USD composition.** Geometry, state, annotation. Geometry doesn't change. State changes per second. Annotation changes per HAZOP cycle. Different cadences = different layers.

6. **ISA-95 hierarchy as the join key.** Every prim has an ISA-95 path. Every tag maps to an ISA-95 path. This is the bridge between the operator's mental model and the USD scene graph.

7. **Spec-driven, planner-executor split.** The architect (web Claude) plans and produces specs. The executor (Claude Code) implements against specs. The owner is the bridge and decision-maker. The brief is master.

8. **The runbook is mandatory, not optional.** Every solved problem, every working command, every gotcha gets written into `OPERATOR_RUNBOOK.md` immediately, not "later." If it's not in the runbook, it didn't happen.

---

## 6. Target architecture (cloud-side)

```
┌──────────────────────────────────────────────────────────────────┐
│                  Lambda Labs A6000 instance                       │
│                                                                   │
│  ┌──────────────────────┐      ┌──────────────────────────┐      │
│  │  data fabric service │      │  Omniverse Kit App       │      │
│  │  (host, systemd)     │      │  (host, native)          │      │
│  │  - process simulator │      │  - CDU1.usda loaded      │      │
│  │  - in-mem bus        │◄────►│  - cdutwin extension     │      │
│  │  - HTTP/SSE :8765    │ SSE  │    - panel UI            │      │
│  │                      │      │    - live_binding loop   │      │
│  └──────────────────────┘      │    - Fabric writes       │      │
│                                └──────────┬───────────────┘      │
│                                           │                       │
│                                           │ shared USD stage      │
│                                           ▼                       │
│                                ┌──────────────────────┐           │
│                                │  Isaac Sim scenarios │           │
│                                │  - gas dispersion    │           │
│                                │  - inspection rover  │           │
│                                └──────────────────────┘           │
│                                                                   │
│  ┌──────────────────────┐      ┌──────────────────────────┐      │
│  │  Xvfb virtual disp.  │◄────►│  TigerVNC / noVNC :6080  │      │
│  └──────────────────────┘      └──────────────────────────┘      │
│                                           ▲                       │
└───────────────────────────────────────────┼───────────────────────┘
                                            │ SSH tunnel :6080
                                            │
                            ┌───────────────┴────────────┐
                            │  Owner's Mac, Safari        │
                            │  https://localhost:6080     │
                            │  (screen-share to Zoom)     │
                            └────────────────────────────┘
```

Key decisions encoded above:

- Kit and Isaac Sim run **natively on the host**, not in containers. This is NVIDIA's recommended pattern; containerizing them adds a second integration burden without buying anything for a personal demo.
- Data fabric runs as a **systemd service on the same host**. Zero network hops between fabric and Kit extension. Could be containerized later if Kafka migration happens; not now.
- VNC is the bridge to the owner's Mac. **No public exposure** — VNC is only reachable through an SSH tunnel.
- Snapshot is taken at the end of Phase 5. From snapshot, instance launch to demo-ready is target ~5 minutes.

---

## 7. Repo structure

**Monorepo, inside an existing portfolio umbrella.**

All work lives at:

```
github.com/sowthri-industrial-ai/SolutionPortfolio
└── AISolutions/
    └── refinery-twin/              ← OUR PROJECT ROOT
        ├── README.md                ← project landing page, video at top
        ├── docs/
        │   ├── OPERATOR_RUNBOOK.md  ← durable knowledge artifact
        │   ├── architecture.md
        │   └── media/               ← screenshots, video files
        ├── asset-library/           ← parametric USD builders
        ├── data-fabric/             ← process simulator + event bus + SSE
        ├── kit-extension/           ← the Omniverse Kit extension
        │   └── exts/com.sowthri.cdutwin/
        └── isaac-scenarios/         ← gas leak, rover, valve
```

**Decision rationale (logged 2026-04-29):** initially the charter
specified five separate repos to mirror NVIDIA's sample distribution
pattern. After review, monorepo was selected because:

- This is a personal demo, not a public sample distribution. Five repos
  optimizes for thousands of consumers; we have one consumer (the
  interviewer), driven by the owner.
- The `SolutionPortfolio` repo is the owner's existing portfolio
  umbrella. Putting refinery-twin inside it preserves portfolio
  narrative continuity.
- Single-repo workflow is simpler: one `git pull`, one `git push`, one
  branch, no coordinating across repos.
- `git filter-repo` makes future extraction (e.g. publishing the asset
  library as a standalone reusable repo) tractable if it ever becomes
  desirable. Easier than merging five repos back together would be.

**Owner GitHub identity:** `sowthri-industrial-ai` (org). Org account
is the canonical professional identity for these projects.

**Kit extension Python namespace:** `com.sowthri.cdutwin`. Drops the
`-industrial-ai` suffix because Python package identifiers cannot
contain hyphens.

**Authentication:** HTTPS with Personal Access Token, stored in
macOS keychain via `osxkeychain` git credential helper. Same pattern
on the cloud instance via `cache` or `store` credential helper. **No
SSH keys for git on this project** (SSH is used for the Lambda
instance only).

**Visibility:** Public from day one. The `SolutionPortfolio` repo is
already public. Anything sensitive (NGC API keys, instance IPs, SSH
keys, cloud account credentials) **never** enters git — see
`GIT_WORKFLOW.md` for the strict not-in-git list.

---

## 8. Phases and definition of done per phase

### Phase 0 — Foundation

**Goal:** Cloud instance running, Omniverse Kit boots headlessly, owner sees Kit window in Mac browser via VNC.

**DoD:**
- [ ] Lambda Labs A6000 instance launched, SSH-accessible
- [ ] System dependencies installed (Vulkan, X server, VNC stack)
- [ ] Omniverse Kit App Template cloned, builds clean
- [ ] Kit boots via Xvfb without errors in log
- [ ] VNC reachable from Mac via SSH tunnel; Kit window visible in browser
- [ ] OPERATOR_RUNBOOK.md initialized with working install commands
- [ ] Snapshot taken (Phase 0 baseline)

**Estimated duration:** 3-5 days.
**Critical risks:** Vulkan driver mismatch; Kit version vs Lambda image incompatibility.

### Phase 1 — CDU scene in Kit

**Goal:** The asset library output renders in Kit with RTX. Scene navigates cleanly. No live data yet.

**DoD:**
- [ ] `refinery-usd-asset-library` running on cloud instance, produces 51-prim CDU1.usda
- [ ] CDU1.usda opens in Kit viewport, RTX path-traced
- [ ] Camera bookmarks: wide-shot, AtmColumn close, equipment row
- [ ] Materials: at minimum a metal MDL on the column shell, default elsewhere
- [ ] No errors in Kit log when stage is loaded
- [ ] Architecture and runbook updated
- [ ] Phase 1 snapshot taken

**Estimated duration:** 4-5 days.

### Phase 2 — Custom extension loads

**Goal:** `com.<owner>.cdutwin` extension is real, registered, panel opens, no live data yet.

**DoD:**
- [ ] Extension folder structure correct, `extension.toml` valid
- [ ] Kit's extension search path includes the dev folder
- [ ] Extension appears in Extensions panel, toggles ON without errors
- [ ] "CDU Twin Panel" entry under Window menu
- [ ] Panel opens, layout renders correctly
- [ ] All buttons (Connect, Disconnect, Trigger Disturbance) wired with logging
- [ ] Tag table widget renders an empty state
- [ ] OPERATOR_RUNBOOK.md updated with extension registration steps
- [ ] Phase 2 snapshot taken

**Estimated duration:** 5-7 days.
**Critical risks:** Python namespace package layout; pip install into Kit's bundled Python; aiohttp / aiokafka dependency resolution.

### Phase 3 — Live data binding

**Goal:** Data fabric runs as sidecar; extension subscribes; values flow into USD attributes; disturbance moment is demoable.

**DoD:**
- [ ] `refinery-data-fabric` runs as a systemd unit on the cloud instance, restarts on failure
- [ ] HTTP/SSE endpoint reachable on `localhost:8765`
- [ ] Extension's `live_binding.py` subscribes to SSE on Connect
- [ ] Tag table populates within 2 seconds of Connect
- [ ] Each tag value appears as `cdu:liveValue` custom attribute on the corresponding USD prim
- [ ] Disturbance button triggers the simulator's furnace upset; PT-201 and TT-205 visibly drift in the panel and on the prim attributes
- [ ] HUD overlay in viewport shows current value next to AtmColumn (stretch within phase)
- [ ] OPERATOR_RUNBOOK.md updated
- [ ] Phase 3 snapshot taken — **this is the headline demo state**

**Estimated duration:** 5-7 days.

### Phase 4 — Isaac Sim scenarios

**Goal:** Isaac Sim installed alongside Kit, gas leak and rover scenarios genuinely run, valve scenario is stretch.

**DoD:**
- [ ] Isaac Sim 4.x installed natively on the cloud instance
- [ ] Compatible with Kit version from Phase 0-3 (or documented why two separate workflows)
- [ ] **Gas leak dispersion**: Flow emitter at PSV-201 prim, configurable wind, plume renders in viewport, concentration CSV written
- [ ] **Inspection rover**: PhysX articulated rover loads, follows YAML route, dwells at waypoints, ROS 2 topics published
- [ ] (Stretch) **Valve actuator**: PhysX 1-DOF articulation, three failure modes, CSV output
- [ ] Each scenario has a `run_*.sh` wrapper for fast launch from the runbook
- [ ] OPERATOR_RUNBOOK.md updated
- [ ] Phase 4 snapshot taken

**Estimated duration:** 10-14 days.
**Critical risks:** Isaac Sim Python environment vs Kit Python environment; Flow extension version compatibility; ROS 2 setup on Ubuntu 22.04.

### Phase 5 — Polish, snapshot, runbook, repos

**Goal:** Everything pushed to GitHub. Snapshot saved. Runbook complete. Marketing video recorded.

**DoD:**
- [ ] All five repos pushed to GitHub, public
- [ ] Each repo's README accurate; architecture diagrams render in GitHub Markdown
- [ ] OPERATOR_RUNBOOK.md is end-to-end: from "fresh Lambda instance" to "demo running" in numbered steps
- [ ] 90-second screen recording captures: Kit boot, scene loaded, extension Connect, live values updating, disturbance moment, gas leak scenario, rover scenario
- [ ] Recording embedded in `refinery-twin` meta repo README
- [ ] Final snapshot taken — interview-ready state
- [ ] Cost-control plan in place: instance terminated; snapshot fee tracked

**Estimated duration:** 3-5 days.

---

## 9. Success criteria

The project is complete when **all** of the following are true:

1. From a saved snapshot, a fresh A6000 instance can launch and reach demo-ready state in under 10 minutes (one shell script, no manual debugging).
2. The screen-shared demo runs reliably for 15 minutes without crash, glitch, or fallback.
3. An interviewer can ask "what happens if you change [X]" and the owner can demonstrate the change live, by editing YAML and re-running, within 2 minutes.
4. All five GitHub repos exist, are public, have working READMEs, and the code in them is the code that ran on the cloud instance — not architectural scaffolding.
5. The OPERATOR_RUNBOOK.md is detailed enough that a competent stranger could rebuild the demo from scratch on a new account.

If any of these are not true, the project is not complete. We do not move past Phase 5 until they are.

---

## 10. Cost and time budget

**Cloud GPU:** ~$200-400 over the project lifetime.
- Active development: ~150 hours × $0.80/hr A6000 = $120
- Phase boundary fresh-instance verification: ~20 hours × $0.80 = $16
- Buffer for retries, debugging: ~50 hours × $0.80 = $40
- Snapshot storage during project: ~$15/month × 2 months = $30
- Snapshot storage post-project (insurance): ~$15/month ongoing

**Wall-clock time:** 3-5 weeks at full-time intensity (40+ hrs/week).

**Owner time:** ~150-200 hours total. Roughly:
- Phase 0: 20 hours
- Phase 1: 25 hours
- Phase 2: 35 hours
- Phase 3: 30 hours
- Phase 4: 50-70 hours (largest variance)
- Phase 5: 15-20 hours

Sustainability: at least one full day off per week. No exceptions.
This project is a marathon, not a sprint.

---

## 11. Decision log (append-only)

This section captures binding decisions made during the project. New
decisions append; old decisions are never silently revised.

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-29 | Charter locked. Personal-demo scope, snapshot-driven, no public URL. | Owner reviewed all alternatives and chose this. |
| 2026-04-29 | Lambda Labs A6000 as cloud target. | Cheapest combination of price and time-to-first-bash. AWS g5/Azure NV are fallbacks. |
| 2026-04-29 | Kit and Isaac Sim run natively on host, not in containers. | NVIDIA-recommended deployment for development. Containerization adds burden without value here. |
| 2026-04-29 | Five repos, multi-repo layout. Meta repo is `refinery-twin`. | Mirrors NVIDIA's own samples organization. |
| 2026-04-29 | OPERATOR_RUNBOOK is mandatory and continuous. | Durable knowledge artifact. Charter principle 8. |
| 2026-04-29 | **REVISED**: Monorepo, not five separate repos. Lives inside `sowthri-industrial-ai/SolutionPortfolio` at `AISolutions/refinery-twin/`. Supersedes the row above. | Personal demo with one consumer (interviewer); monorepo is simpler workflow and preserves owner's portfolio narrative continuity. |
| 2026-04-29 | Git auth via HTTPS + Personal Access Token (no SSH for git). | Owner preference. Token stored in keychain (Mac) and credential cache (cloud). |
| 2026-04-29 | Kit extension Python namespace: `com.sowthri.cdutwin`. | Hyphens illegal in Python package names; `-industrial-ai` suffix dropped. |
| 2026-04-29 | Repos public from day one. | Owner preference for transparency and recruiter-readability. Sensitive material kept strictly out of git per `GIT_WORKFLOW.md`. |

---

## 12. Working agreement summary (full version in `CLAUDE_CODE_AGREEMENT.md`)

- The architect (web Claude) writes specs. The executor (Claude Code) implements.
- The owner approves all phase transitions explicitly.
- The brief (this document) is master. Configs derive from it. Code derives from configs.
- No silent scope changes. Anything new goes into the Phase 7+ parking lot.
- No phase begins until previous phase is verified on a fresh instance.

---

**Charter end.**
