# Backlog — Phase 0 (Foundation)

This file holds detailed story-level work for **Phase 0 only**. Phase 1
will be written when Phase 0 is closed; we don't write detail more
than one phase ahead, because we'll learn things in Phase 0 that
change Phase 1's specifics.

Phase 0 goal: Cloud GPU instance running, Omniverse Kit booting
headlessly, owner sees Kit window in Mac browser via VNC.

---

## Story 0.0 — Project skeleton in git (NEW, do this first)

**Owner-driven on the Mac. No Claude Code yet.**

This story creates the project's home in git before anything else.
Every later story commits into the structure created here. Doing this
first means we can `git pull` on the cloud instance from the very
beginning of Phase 0 work tomorrow.

**Time estimate:** 30 min.

### 0.0.1 Confirm and clone SolutionPortfolio locally

- [ ] On Mac, ensure no uncommitted local copy already exists. If
      `~/Documents/SolutionPortfolio/` exists with content already in
      it, paste status to architect before continuing.
- [ ] Clone fresh to a clean location:
      ```bash
      cd ~/Documents
      git clone https://github.com/sowthri-industrial-ai/SolutionPortfolio.git
      cd SolutionPortfolio
      git pull
      ```
- [ ] Confirm `AISolutions/` exists. List contents:
      ```bash
      ls AISolutions/
      ```
- [ ] If you have a current SolutionPortfolio at a different path
      already, stop and reconcile before proceeding. Do NOT have two
      working copies — confusion guaranteed.

### 0.0.2 Create the project directory structure

- [ ] Make the project root and skeleton directories:
      ```bash
      cd ~/Documents/SolutionPortfolio/AISolutions
      mkdir -p refinery-twin/{docs/media,asset-library,data-fabric,kit-extension,isaac-scenarios}
      cd refinery-twin
      ```

### 0.0.3 Copy charter docs into the project

- [ ] Copy the charter package into `docs/`:
      ```bash
      cp -r ~/Documents/SolutionPortfolio/AISolutions/2.refinery-twin-prep/charter docs/charter
      ```
- [ ] Copy `RUNBOOK_TEMPLATE.md` to the active runbook location:
      ```bash
      cp docs/charter/RUNBOOK_TEMPLATE.md docs/OPERATOR_RUNBOOK.md
      ```
- [ ] Open `docs/OPERATOR_RUNBOOK.md` in an editor and fill in the
      "My environment" section (GitHub handle, Lambda email, etc.).
- [ ] Verify structure:
      ```bash
      tree -L 3 || find . -maxdepth 3 -type d -o -type f | sort
      ```

### 0.0.4 Add `.gitignore` and project README stub

- [ ] Create `.gitignore` at the project root with the contents from
      `GIT_WORKFLOW.md` §4. (Architect provides the exact content if
      not already in the file.)
- [ ] Create `README.md` at the project root with this minimum content:
      ```markdown
      # Refinery Twin — NVIDIA Omniverse + Isaac Sim

      A real Physical AI demo: Crude Distillation Unit twin in
      Omniverse Kit with live process data binding, plus Isaac Sim
      scenarios for safety and inspection use cases.

      Status: in-build. See `docs/charter/PROJECT_CHARTER.md` for
      scope and `docs/OPERATOR_RUNBOOK.md` for the live operations
      log.

      ## Architecture
      (placeholder — diagram added end of Phase 1)

      ## Demo
      (placeholder — video added end of Phase 5)
      ```

### 0.0.5 First commit and push

- [ ] From the project root:
      ```bash
      cd ~/Documents/SolutionPortfolio
      git status
      ```
- [ ] Eyeball the diff. Confirm no `.venv/`, no `__pycache__/`, no
      secret files. If anything looks suspicious, paste status to
      architect before continuing.
- [ ] Stage and commit:
      ```bash
      git add AISolutions/refinery-twin
      git commit -m "phase-0/0.0: bootstrap refinery-twin project skeleton

      - Charter docs in docs/charter/
      - Operator runbook initialized at docs/OPERATOR_RUNBOOK.md
      - .gitignore covering Python/USD/Kit build artifacts
      - Skeleton directories for asset-library, data-fabric,
        kit-extension, isaac-scenarios"
      ```
- [ ] Push:
      ```bash
      git push origin main
      ```
- [ ] First-time HTTPS push will prompt for username + password.
      Username: GitHub username. Password: PAT generated per
      `GIT_WORKFLOW.md` §2.
- [ ] Verify on GitHub: visit
      `https://github.com/sowthri-industrial-ai/SolutionPortfolio/tree/main/AISolutions/refinery-twin`
      — content should be visible.

### 0.0.6 Tag the start of Phase 0

- [ ] Tag the commit:
      ```bash
      git tag -a phase-0-start -m "Phase 0 begins YYYY-MM-DD"
      git push origin --tags
      ```

**DoD for Story 0.0:**
- [ ] `AISolutions/refinery-twin/` exists on GitHub with charter docs, runbook, .gitignore, README stub
- [ ] First commit visible on GitHub with proper message format
- [ ] Tag `phase-0-start` exists
- [ ] OPERATOR_RUNBOOK.md "Story 0.0" section filled in with the commit hash and date

**Pivot rules:**
- If `git push` fails on the first attempt, paste error to architect — don't retry-with-modifications.
- If `AISolutions/` already has unrelated content that conflicts, stop and reconcile with architect before proceeding.

---

## Story 0.1 — Pre-flight on owner's Mac

**Owner-driven, no Claude Code needed.**

- [ ] Lambda Labs account verified, payment method on file
- [ ] SSH key pair exists on Mac (`~/.ssh/id_ed25519` or equivalent)
- [ ] NGC account created at ngc.nvidia.com, API key generated and saved to a password manager
- [ ] GitHub handle confirmed and noted in OPERATOR_RUNBOOK
- [ ] Local tools installed: `ssh`, `tmux`, `git`, `pbcopy`/clipboard helper
- [ ] `~/Documents/AISolutions/2.refinery-twin-prep/` exists with venv from earlier work

**DoD:** all checkboxes ticked.
**Time estimate:** 30 min.

---

## Story 0.2 — Lambda Labs instance launched

**Owner-driven, console clicks only.**

- [ ] In Lambda Labs console, launch `gpu_1x_a6000` instance, Ubuntu 22.04 image, region near you
- [ ] Attach the SSH public key from Story 0.1
- [ ] Storage: 200 GB (default is fine; Omniverse + Isaac Sim eat ~80 GB combined)
- [ ] Wait for "Running" state
- [ ] Note the public IP in OPERATOR_RUNBOOK
- [ ] Test SSH: `ssh ubuntu@<ip>` succeeds
- [ ] Run `nvidia-smi` on the instance — confirm A6000 detected with driver version logged

**DoD:** SSH works, `nvidia-smi` shows the GPU.
**Time estimate:** 15-30 min.
**Cost from this point:** ~$0.80/hr while running.

---

## Story 0.3 — System dependencies installed

**Claude Code drives.**

The cloud instance needs a specific set of system packages before Kit
will boot. This story installs them in one batch.

**DoD:**
- [ ] Apt updated and upgraded (security patches)
- [ ] Vulkan loader + Mesa Vulkan ICD installed
- [ ] X virtual framebuffer (Xvfb) installed
- [ ] x11vnc installed
- [ ] noVNC + websockify installed (browser-based VNC viewer)
- [ ] Build essentials: `build-essential`, `cmake`, `git`, `curl`, `unzip`
- [ ] Python 3.10+ confirmed (Ubuntu 22.04 ships with 3.10)
- [ ] Docker engine installed (for data fabric in Phase 3)
- [ ] All installs logged in OPERATOR_RUNBOOK with the exact `apt install` lines

**Reference command set (Claude Code will execute):**
```bash
sudo apt-get update
sudo apt-get -y upgrade
sudo apt-get install -y \
    libvulkan1 mesa-vulkan-drivers vulkan-tools \
    xvfb x11vnc novnc websockify \
    libfontconfig1 libxrender1 libxcomposite1 \
    libxcursor1 libxdamage1 libxi6 libxtst6 libnss3 \
    libcups2 libxss1 libxrandr2 libasound2 \
    libpangocairo-1.0-0 libatk1.0-0 libatk-bridge2.0-0 \
    libgtk-3-0 libgbm1 libxkbcommon0 \
    build-essential cmake git curl unzip tmux
```

Plus Docker per the official Ubuntu instructions (separate apt repo).

**Time estimate:** 15-30 min.

---

## Story 0.4 — Verify Vulkan + GPU on the instance

**Claude Code drives.**

Quick smoke test that the GPU is reachable through Vulkan, which is
what Kit needs.

**DoD:**
- [ ] `vulkaninfo --summary` runs without error
- [ ] Output shows the A6000 listed as a Vulkan device
- [ ] `nvidia-smi` shows driver version compatible with Kit (note version in runbook)
- [ ] If anything fails: stop, do NOT try to fix by upgrading drivers (high risk of bricking the instance) — escalate to architect review first

**Time estimate:** 5 min.

---

## Story 0.5 — Omniverse Kit App Template cloned and built

**Claude Code drives. Long-running build.**

NVIDIA's `kit-app-template` is the recommended starting point for
custom Kit apps. We clone it, generate a "Kit Base Editor" template,
and build.

**DoD:**
- [ ] `~/omniverse/kit-app-template/` exists, cloned from the official NVIDIA-Omniverse GitHub repo
- [ ] `./repo.sh template new` ran, owner picked "Omniverse Kit Base Editor", named the app `cdu_twin_app`
- [ ] `./repo.sh build` completed successfully (this is the long step — 15-30 min, expect lots of GB downloaded)
- [ ] `_build/linux-x86_64/release/` exists with the built app artifacts
- [ ] Build log saved to OPERATOR_RUNBOOK with the duration and any warnings worth noting

**Reference commands:**
```bash
mkdir -p ~/omniverse && cd ~/omniverse
git clone https://github.com/NVIDIA-Omniverse/kit-app-template.git
cd kit-app-template
./repo.sh template new
# (interactive — owner picks options)
./repo.sh build  # 15-30 min
```

**Time estimate:** 1 hour wall-clock (mostly waiting for the build).
**Critical risk:** repo.sh may require interactive Y/N confirmations that Claude Code can't answer. If this happens, owner intervenes manually.

---

## Story 0.6 — Xvfb + Kit headless boot

**Claude Code drives.**

Without a real display, we boot a virtual one (Xvfb) and tell Kit to
render against it.

**DoD:**
- [ ] Xvfb started on display `:99` with 1920x1080x24
- [ ] `DISPLAY=:99` exported in shell
- [ ] `./repo.sh launch` in kit-app-template starts the app
- [ ] Kit log shows clean startup (no fatal errors in first 60 seconds)
- [ ] App stays running; Claude Code records process PID and writes a `kit_smoke_test_passed.txt` marker

**Reference commands:**
```bash
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
cd ~/omniverse/kit-app-template
./repo.sh launch  # logs stream; let it run for 60s, kill after
```

**Time estimate:** 15 min.
**Critical risk:** Vulkan-related errors in Kit log → revisit Story 0.4. If Kit crashes on startup, this is a Phase-0-blocking issue.

---

## Story 0.7 — VNC accessible from owner's Mac

**Claude Code drives the cloud side; owner verifies on Mac.**

The point of VNC is so the owner can SEE Kit running on the cloud
instance, in a browser tab on their Mac. This is the visual milestone.

**DoD:**
- [ ] x11vnc serving display `:99` on port 5900 (localhost only, NOT public)
- [ ] websockify bridging port 6080 → 5900 with noVNC HTML
- [ ] Owner opens local terminal and runs `ssh -L 6080:localhost:6080 ubuntu@<ip>`
- [ ] Owner opens `http://localhost:6080/vnc.html` in Safari/Chrome on Mac
- [ ] Owner sees Kit running in the noVNC browser tab
- [ ] Owner takes a screenshot, attaches to OPERATOR_RUNBOOK as visual evidence

**Reference commands (cloud side):**
```bash
x11vnc -display :99 -forever -shared -rfbport 5900 &
websockify --web /usr/share/novnc 6080 localhost:5900 &
```

**Reference commands (Mac side, separate terminal):**
```bash
ssh -L 6080:localhost:6080 ubuntu@<ip>
# leave that terminal open
# in browser: http://localhost:6080/vnc.html
```

**Time estimate:** 20 min.
**Critical risk:** if browser shows black screen, debugging needed (xrandr, Xvfb screen size mismatch). Document any fixes in runbook.

---

## Story 0.8 — Phase 0 snapshot

**Owner-driven, Lambda console clicks.**

Save the instance state so we can replay Phase 0 anytime.

**DoD:**
- [ ] Stop the instance via Lambda console (do NOT terminate)
- [ ] Take snapshot, name it `phase-0-foundation-YYYYMMDD`
- [ ] Verify snapshot appears in console
- [ ] Note snapshot ID and date in OPERATOR_RUNBOOK
- [ ] Restart instance, verify it still works (sanity check that the snapshot didn't break anything)

**Time estimate:** 10 min + however long Lambda takes to snapshot.
**Cost note:** snapshot storage starts accruing here, ~$0.05/GB/month.

---

## Story 0.9 — Phase 0 gate review

**Architect-driven (web Claude).**

Owner pastes the OPERATOR_RUNBOOK to architect. Architect reviews:

- [ ] All Story 0.1 - 0.8 DoDs ticked with evidence
- [ ] Runbook commands are accurate enough that a reasonable person could re-execute Phase 0 from scratch
- [ ] No skipped or rationalized DoDs
- [ ] Owner reports any concerns or blockers for Phase 1

If review passes: architect writes Phase 1 backlog detail. We move to Phase 1.
If review fails: identify gaps, owner fixes, re-review.

**Time estimate:** 30 min for architect review + however long the gap-fixing takes.

---

## Stories deliberately NOT in this backlog

These are things you might think belong in Phase 0 but don't:

- ❌ Asset library setup → Phase 1
- ❌ Loading any USD scene → Phase 1
- ❌ Touching the cdu-twin extension → Phase 2
- ❌ Data fabric service → Phase 3
- ❌ Isaac Sim install → Phase 4
- ❌ Repo refactoring or migration → Phase 5

If any of these come up in Phase 0 work, the answer is "not yet, Phase N." Charter principle 8: scope creep dies here.

---

## Working agreement reminders for Phase 0

- Every Claude Code session starts with reading the CLAUDE_CODE_AGREEMENT.md
- Every command that modifies the system gets logged in OPERATOR_RUNBOOK before moving to the next step
- Phase 0 is high-velocity — many small commands. Claude Code may batch them, but every batch must be reported with stdout
- Errors halt execution; Claude Code reports rather than auto-fixing
- No installs of anything not in this backlog without architect approval

---

**Phase 0 backlog end. Phase 1 backlog will be written at end of Phase 0 gate review.**
