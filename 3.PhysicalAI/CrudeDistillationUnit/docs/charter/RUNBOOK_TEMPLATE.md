# Operator Runbook — Refinery Twin

This runbook is the cumulative record of every working command, every
solved problem, every gotcha discovered during the project. It exists
so the build knowledge doesn't live only on a server we'll someday
terminate.

**Charter principle 8: if it's not in the runbook, it didn't happen.**

The point of this document is that a competent stranger could rebuild
the demo from scratch by following it. That standard is not "thorough
notes for me" — it's "step-by-step instructions that work for someone
who is not me."

---

## How to use this document

- **Append, never delete.** When something changes, add a new entry with the date. Don't erase history.
- **Commands as code blocks.** Not prose. A future-you needs to copy-paste, not interpret.
- **Outcomes after every command.** "What I expected" + "what actually happened" + "what fixed it if different."
- **Document at the time of discovery, not at the end of the day.** Memory degrades fast.

---

## My environment

- **Owner GitHub handle:** [fill in]
- **Local working directory:** ~/Documents/AISolutions/2.refinery-twin-prep
- **Local Python:** 3.11.3 in `.venv`
- **Lambda Labs account email:** [fill in]
- **NGC account email:** [fill in]
- **NGC API key:** stored in password manager as "NGC API Key"

---

## Cloud instance details

(updated as instance is rebuilt across the project)

| Date provisioned | Region | Instance type | Public IP | Driver version | Notes |
|---|---|---|---|---|---|
| | | gpu_1x_a6000 | | | |

---

## Snapshots

(every phase boundary creates one)

| Date | Phase | Snapshot ID | Size (GB) | Boot-from-snapshot tested? | Notes |
|---|---|---|---|---|---|
| | | | | | |

---

## Cost log

(track spend over the project)

| Date | Activity | Hours | Cost (USD) | Cumulative |
|---|---|---|---|---|
| | | | | |

---

## Phase 0 — Foundation

### Story 0.1 — Pre-flight on Mac

(in progress / done)

**Date completed:** [YYYY-MM-DD]

**What was done:**
- (list)

**Working commands:**
```bash
# (paste the commands that worked)
```

**Issues encountered & resolution:**
- (none / details)

---

### Story 0.2 — Lambda Labs instance launched

**Date completed:** [YYYY-MM-DD]

**What was done:**
- (list)

**Working commands:**
```bash
ssh ubuntu@<ip>
nvidia-smi
tmux new -s refinery
```

**Output of nvidia-smi:**
```
(paste relevant lines here, especially driver version)
```

**Issues encountered & resolution:**
- (none / details)

---

### Story 0.3 — System dependencies installed

**Date completed:** [YYYY-MM-DD]

**Apt packages installed (one-line invocation):**
```bash
sudo apt-get install -y \
    libvulkan1 mesa-vulkan-drivers vulkan-tools \
    xvfb x11vnc novnc websockify \
    ...
```

**Docker install steps:**
```bash
# (the Ubuntu official Docker apt repo install)
```

**Issues encountered & resolution:**
- (none / details)

---

### Story 0.4 — Vulkan + GPU verified

**Date completed:** [YYYY-MM-DD]

**Working command:**
```bash
vulkaninfo --summary
```

**Output:**
```
(relevant lines: Vulkan version, A6000 listed as device)
```

**Issues encountered & resolution:**
- (none / details)

---

### Story 0.5 — Kit App Template built

**Date completed:** [YYYY-MM-DD]

**What was done:**
- Cloned `kit-app-template` from NVIDIA-Omniverse GitHub
- Generated app via `./repo.sh template new`, type "Kit Base Editor", name `cdu_twin_app`
- Built via `./repo.sh build`

**Build duration:** [hours:minutes]

**Built artifact location:**
```
~/omniverse/kit-app-template/_build/linux-x86_64/release/
```

**Issues encountered & resolution:**
- (none / details)

---

### Story 0.6 — Xvfb + Kit headless boot

**Date completed:** [YYYY-MM-DD]

**Working command sequence:**
```bash
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
cd ~/omniverse/kit-app-template
./repo.sh launch
```

**Kit boot log (notable lines):**
```
(quote a few lines that confirm clean boot)
```

**Issues encountered & resolution:**
- (none / details)

---

### Story 0.7 — VNC accessible from Mac

**Date completed:** [YYYY-MM-DD]

**Cloud-side commands:**
```bash
x11vnc -display :99 -forever -shared -rfbport 5900 &
websockify --web /usr/share/novnc 6080 localhost:5900 &
```

**Mac-side commands (separate terminal):**
```bash
ssh -L 6080:localhost:6080 ubuntu@<ip>
# leave open
# in browser: http://localhost:6080/vnc.html
```

**Screenshot evidence:** [link / file path]

**Issues encountered & resolution:**
- (none / details)

---

### Story 0.8 — Phase 0 snapshot

**Date completed:** [YYYY-MM-DD]

**Snapshot ID:** [fill in]

**Boot-from-snapshot test:** [pass / fail, date tested]

**Issues encountered & resolution:**
- (none / details)

---

## Phase 1 — CDU scene in Kit

(stories filled in after Phase 0 gate review)

---

## Phase 2 — Custom extension

(filled in after Phase 1 gate review)

---

## Phase 3 — Live data binding

(filled in after Phase 2 gate review)

---

## Phase 4 — Isaac Sim scenarios

(filled in after Phase 3 gate review)

---

## Phase 5 — Polish, snapshot, repos

(filled in after Phase 4 gate review)

---

## Glossary

For when you come back to this in 6 months and forget what something means.

| Term | Meaning in this project |
|---|---|
| Kit | NVIDIA Omniverse Kit, the framework. Our app is built on it. |
| NGC | NVIDIA GPU Cloud, the container registry for Omniverse / Isaac Sim images |
| RTX | Ray Tracing eXtensions; here, NVIDIA's path-traced rendering modes in Kit |
| USD | Universal Scene Description, Pixar's 3D scene format. Our refinery scene format. |
| ISA-95 | International standard for enterprise-control system integration. Our naming convention. |
| OPC UA | Open Platform Communications Unified Architecture. Industrial protocol standard. |
| Fabric | Kit's runtime data layer for fast scene-graph updates (vs file-backed USD writes) |
| Flow | NVIDIA's volumetric fluid simulator; we use it for gas dispersion |
| PhysX | NVIDIA's rigid-body and articulation physics; we use it for rover and valves |
| Articulation | A jointed rigid-body chain in PhysX (e.g., a robot arm or a valve actuator) |

---

## Common failure modes (filled in as encountered)

(empty for now)

| Symptom | Root cause | Fix |
|---|---|---|

---

## Decision log (cross-references PROJECT_CHARTER §11)

(empty for now — significant decisions get logged in the charter itself, this section captures operational decisions)

| Date | Decision | Why |
|---|---|---|

---

**Operator runbook end. Append-only.**
