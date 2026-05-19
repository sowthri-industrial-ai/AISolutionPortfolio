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

- **Owner GitHub handle:** sowthri-industrial-ai (org)
- **Local working directory:** ~/Documents/SolutionPortfolio/AISolutions/RefineryTwin
- **Local Mac:** SOWTHRIs-MacBook-Air
- **Local Python:** 3.11.3, project venv at `RefineryTwin/.venv` (created 2026-04-30, empty, awaiting Phase 1)
- **Cloud provider:** AWS (pivoted from Lambda Labs 2026-04-30 — see Decision log)
- **AWS account ID:** 534883914089
- **AWS account alias:** sowthri-industrial-ai
- **AWS region:** ap-south-1 (Mumbai)
- **AWS root email:** stored in password manager (entry "AWS Root — RefineryTwin")
- **AWS IAM admin user:** sowthri-admin
- **AWS IAM credentials:** stored in password manager as "AWS IAM — sowthri-admin"
- **NGC account email:** stored in password manager (entry "NGC Account — RefineryTwin")
- **NGC API key:** stored in password manager as "NGC API Key — RefineryTwin"
- **GitHub PAT:** stored in macOS keychain via `osxkeychain` credential helper
- **SSH key path:** `~/.ssh/id_ed25519` (private), `~/.ssh/id_ed25519.pub` (public)
- **SSH key fingerprint:** `SHA256:6mV0wTzN0uL7kCbiHuVWcDA+WMGr5Pzl9HBXMcYsS88`
- **SSH key uploaded to AWS as Key Pair:** `sowthri-mac-refinery-twin` (in ap-south-1)

---

## Cloud instance details

| Date provisioned | Region | Instance type | Public IP | Driver version | Notes |
|---|---|---|---|---|---|
| 2026-05-05 | ap-south-1 (Mumbai) | g6.xlarge | Changes per restart (latest: 3.110.118.104) | 580.105.08 | First instance. NVIDIA L4 GPU 24 GB VRAM. Story 0.2-0.7 instance ID `i-084dcf23391e63165`. Currently Stopped. |

---

## Snapshots

| Date | Phase | Snapshot ID | Size (GB) | Boot-from-snapshot tested? | Notes |
|---|---|---|---|---|---|
| | | | | | |

---

## Cost log

| Date | Activity | Hours | Cost (USD) | Cumulative |
|---|---|---|---|---|
| 2026-05-01 | AWS account creation, IAM, MFA, budgets | 0 | $0.00 | $0.00 |
| 2026-05-01 | AWS promotional credits issued | — | -$120.00 (credit balance) | -$120.00 |
| 2026-05-05 | Story 0.2 — first instance launch + verify + stop | 0.5 | ~$0.50 (covered by credits) | -$119.50 |
| 2026-05-08 | Stories 0.3-0.7 — deps install + Vulkan verify + Kit build + Kit boot + VNC | ~2.0 | ~$1.94 (covered by credits) | -$117.56 |

---

## Phase 0 — Foundation

### Story 0.0 — Project skeleton in git (DONE 2026-04-30)

**What was done:**
- Used existing SolutionPortfolio working copy at `~/Documents/SolutionPortfolio`
- Created `AISolutions/RefineryTwin/` directory tree with module skeleton
- Copied charter docs into `docs/charter/`
- Initialized OPERATOR_RUNBOOK.md from template
- Wrote `.gitignore` at project root and repo root
- Wrote README.md stub
- First commit, push, tag

**Result:**
- Commit hash: `44790b8`
- 12 files changed, 2819 insertions
- Tag `phase-0-start` pushed to origin
- Visible at: https://github.com/sowthri-industrial-ai/SolutionPortfolio/tree/main/AISolutions/RefineryTwin

**Issues encountered & resolution:**
- None.

---

### Story 0.1 — Pre-flight on Mac (DONE 2026-05-05)

#### Block 1 — SSH key generation (DONE 2026-04-30)

```bash
ssh-keygen -t ed25519 -C "sowthri2020@yahoo.com"
# 3x Enter: default location, no passphrase, confirm no passphrase
```

Result:
- Private key: `~/.ssh/id_ed25519` (mode 600)
- Public key: `~/.ssh/id_ed25519.pub` (mode 644)
- Fingerprint: `SHA256:6mV0wTzN0uL7kCbiHuVWcDA+WMGr5Pzl9HBXMcYsS88`

To copy public key to clipboard for paste:
```bash
pbcopy < ~/.ssh/id_ed25519.pub
```

#### Block 2 — NGC account + Personal Key (DONE 2026-04-30)

Created NGC account at https://ngc.nvidia.com.
Generated Personal Key under Profile → Personal Keys.
Services granted: NGC Catalog + Private Registry.
Storage: Saved in password manager as "NGC API Key — RefineryTwin".

#### Block 3 — AWS account + security baseline (DONE 2026-05-01)

After Lambda Labs → AWS pivot (Saudi card declined at Lambda).

Steps performed:
1. Account created at https://aws.amazon.com
2. MFA enabled on root account (Google Authenticator, named `sowthri-root-phone`)
3. Verified MFA by signing out and back in
4. Created IAM user `sowthri-admin` with AdministratorAccess policy
5. Enabled IAM access to billing
6. Created two Budgets: $10 early warning + $100 monthly cap
7. Signed out root, signed in as IAM user
8. Confirmed region: Asia Pacific (Mumbai) `ap-south-1`
9. Verified $120 in promotional credits ($100 Free Tier + $20 Explore AWS, both expire 2027-05-01)

Account details:
- AWS account ID: `534883914089`
- AWS account alias: `sowthri-industrial-ai`
- IAM user: `sowthri-admin`
- Default region: `ap-south-1`

#### Block 4 — SSH key uploaded to AWS (DONE 2026-05-01)

EC2 → Network & Security → Key Pairs → Import key pair.
Name: `sowthri-mac-refinery-twin`
Pasted from `pbcopy < ~/.ssh/id_ed25519.pub`.
Fingerprint matches local: `SHA256:6mV0wTzN0uL7kCbiHuVWcDA+WMGr5Pzl9HBXMcYsS88`.

#### Block 5 — Pre-flight checks + quota request (DONE 2026-05-05)

Instance type chosen: g6.xlarge ($0.97/hr, 4 vCPUs, 1× NVIDIA L4 GPU 24 GB VRAM).
Quota code: L-DB2E81BA in ap-south-1.

Quota saga:
- Request #1 via console form: auto-denied within 30 min
- Request #2 via Support chat (Esteban): submitted 2026-05-01 ~6:30pm IST, escalated to EC2 team
- Wait period: weekend + 4 business days
- Polite follow-up via chat (Richa): 2026-05-05 ~7:25am IST
- Approval confirmed at 7:29am IST: "Your new quota is 4"
- Case ID: 177764536900839 (Resolved)

---

### Story 0.2 — AWS instance launched (DONE 2026-05-05)

**What was done:**
- Launched first g6.xlarge instance via EC2 console wizard
- SSH'd from Mac to instance using existing ed25519 key pair
- Verified NVIDIA L4 GPU detected and operational via `nvidia-smi`
- Stopped instance cleanly to halt billing

**Instance details:**
- Instance ID: `i-084dcf23391e63165`
- Region: ap-south-1 (Mumbai), AZ: ap-south-1b
- Type: g6.xlarge ($0.97/hr while Running)
- AMI: `ami-001ba428c0f3efe11` — Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.6.0 (Ubuntu 22.04) build 20260103
- Public IP: changes per restart (first: 65.2.153.152, later: 3.110.118.104)
- Security group: `refinery-twin-sg` (SSH from My IP only, source `5.244.109.155/32`)
- Key pair: `sowthri-mac-refinery-twin`
- EBS root volume: 200 GiB gp3, encrypted, delete-on-termination=Yes
- Instance store: 250 GB NVMe SSD ephemeral (free; wiped on stop)

**Working SSH command:**
```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@<public-ip>
# First-time fingerprint prompt: type "yes"
```

**Verification — `nvidia-smi`:**
- NVIDIA L4 detected
- Driver 580.105.08, CUDA 13.0
- 23034 MiB VRAM total
- Idle: 12W/72W, 29°C, 0% utilization

**Stop discipline (CRITICAL):**
- Instance MUST be stopped at end of every work session
- "Stopped" = $0 compute (only ~$0.02/hr EBS storage)
- "Running" = $0.97/hr — leaving overnight burns ~$8 for nothing
- AWS Budgets configured as backstop ($10 early warning)

**Issues encountered & resolution:**
- Storage UI auto-attached an unwanted 8 GiB Volume 2 — removed before launch
- Source type "My IP" missing from dropdown initially — fixed by removing rule and re-adding via "Add security group rule" flow

---

### Story 0.3 — System dependencies installed (DONE 2026-05-08)

**What was done:**
- Installed system packages required for Kit and VNC workflow
- Verified all installs succeeded without breaking running services

**Working commands:**
```bash
# Refresh apt index
sudo apt update

# Install all dependencies in one transaction
sudo apt install -y \
    libvulkan1 \
    mesa-vulkan-drivers \
    vulkan-tools \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    tmux

# build-essential is already installed in the Deep Learning AMI
# git is already installed (version 2.34.1)
```

**What each package does:**

| Package | Purpose |
|---|---|
| libvulkan1 | Vulkan runtime library — Kit's RTX renderer talks to GPU through this |
| mesa-vulkan-drivers | Mesa Vulkan ICD (CPU fallback, harmless to have) |
| vulkan-tools | Includes `vulkaninfo` for verification |
| xvfb | X virtual framebuffer — fakes a display for headless Kit |
| x11vnc | VNC server bridging X11 to TCP — Story 0.7 |
| novnc | Browser-based VNC client (HTML/JS) — Story 0.7 |
| websockify | TCP-to-WebSocket proxy — Story 0.7 |
| tmux | Terminal multiplexer — survives SSH disconnect during long ops |

**Verification:**
- Install completed in ~2 min, no errors
- "No services need to be restarted" confirmed by needrestart
- Kernel up-to-date, no reboot needed

**Issues encountered & resolution:**
- Two harmless apt warnings about NVIDIA repos configured multiple times in `/etc/apt/sources.list.d/`. Cosmetic, ignored.
- "197 packages can be upgraded" — NOT performed. System upgrade could change kernel/driver versions and break GPU. Stay on AMI's known-good versions.

---

### Story 0.4 — Vulkan + GPU verified (DONE 2026-05-08)

**What was done:**
- Ran `vulkaninfo --summary` to verify Vulkan can see the L4 GPU through NVIDIA's proprietary driver

**Working command:**
```bash
vulkaninfo --summary
```

**Output (key lines):**
```
Vulkan Instance Version: 1.4.312

Instance Layers: count = 5
- VK_LAYER_INTEL_nullhw       (cosmetic)
- VK_LAYER_MESA_device_select (cosmetic)
- VK_LAYER_MESA_overlay       (cosmetic)
- VK_LAYER_NV_optimus         (NVIDIA Optimus — relevant)
- VK_LAYER_NV_present         (NVIDIA presentation — relevant)

Devices:
GPU0:
    apiVersion         = 1.4.312
    driverVersion      = 580.105.08
    vendorID           = 0x10de
    deviceID           = 0x27b8
    deviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
    deviceName         = NVIDIA L4
    driverID           = DRIVER_ID_NVIDIA_PROPRIETARY
    driverName         = NVIDIA
    driverInfo         = 580.105.08

GPU1: (Mesa LLVMPIPE — CPU fallback, harmless)
```

**What this confirms:**
- Vulkan API 1.4 available (Kit needs 1.3+)
- NVIDIA L4 detected via Vulkan API (vendor `0x10de` = NVIDIA, device `0x27b8` = L4)
- DISCRETE_GPU type (real hardware, not CPU emulation)
- NVIDIA proprietary driver loaded
- VK_LAYER_NV_optimus + VK_LAYER_NV_present layers active

**Issues encountered & resolution:**
- None. GPU is fully ready for Kit.

---

### Story 0.5 — Kit App Template built (DONE 2026-05-08)

**What was done:**
- Cloned NVIDIA's official `kit-app-template` repository
- Generated a custom Kit Base Editor application named `com.sowthri.cdutwin`
- Built the application via `./repo.sh build`
- Verified launcher artifact exists

**Working commands:**
```bash
# Clone (shallow, faster)
cd ~
git clone --depth 1 https://github.com/NVIDIA-Omniverse/kit-app-template.git
cd kit-app-template

# Generate application via interactive wizard
./repo.sh template new
# Prompts answered:
#   Type:                  Application
#   Template:              Kit Base Editor (kit_base_editor)
#   .kit file name:        com.sowthri.cdutwin
#   display_name:          CDU Twin App
#   version:               0.1.0
#   add layers?:           No

# Build (downloads Kit SDK from packman cache + NVIDIA CDN)
./repo.sh build
```

**Result:**
- BUILD (RELEASE) SUCCEEDED in 122 seconds
- Kit version: `110.1.1+main.0.f130d19b.local`
- Build output at: `_build/linux-x86_64/release/`
- Launcher: `_build/linux-x86_64/release/com.sowthri.cdutwin.kit.sh`
- Source `.kit` config: `source/apps/com.sowthri.cdutwin.kit`

**Verification:**
```bash
ls -la _build/linux-x86_64/release/
# Shows: com.sowthri.cdutwin.kit.sh (launcher), kit.sh (parent),
#        apps/, kit/, extscache/, etc.

cat source/apps/com.sowthri.cdutwin.kit | head -20
# Shows valid TOML config:
#   [package]
#   title = "CDU Twin App"
#   version = "0.1.0"
#   template_name = "kit_base_editor"
```

**Issues encountered & resolution:**
- Wizard had pre-filled placeholder text in prompt fields (e.g., "my_company.my_editor", "My Editor"). Pressing Enter without clearing accepts the placeholder.
- **Resolution:** Use `Ctrl+U` to clear each prompt before typing the correct value. Watch for placeholder text and clear it deliberately.
- First attempt accepted "My Editor" as display_name — wizard was Ctrl+C'd, restarted with deliberate clearing.

---

### Story 0.6 — Xvfb + Kit headless boot (DONE 2026-05-08)

**What was done:**
- Started Xvfb on display `:99` (1920x1080x24)
- Set DISPLAY environment variable
- Launched Kit via the built launcher script with `--no-window` for first test
- Confirmed all extensions loaded and "app ready" reached
- Killed Kit cleanly via Ctrl+C

**Working commands:**
```bash
# Start Xvfb in background
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &

# Verify Xvfb running
ps aux | grep Xvfb | grep -v grep
# Should show: Xvfb :99 ... (PID printed)

# Set DISPLAY for current shell
export DISPLAY=:99

# First boot test (10 second auto-quit)
./_build/linux-x86_64/release/com.sowthri.cdutwin.kit.sh \
    --no-window \
    --/app/quitAfter=10 \
    2>&1 | tee /tmp/kit-firstboot.log
```

**Notable boot log lines:**
- All extensions startup (omni.kit.*, omni.physx.*, omni.usd.*, omni.warp.core, omni.rtx.*, etc.)
- `[ext: com.sowthri.cdutwin-0.1.0] startup` — custom app extension loaded
- `[11.225s] app ready` — Kit fully booted, RTX initialized

**Cosmetic warning:**
- `Warning: Possible version incompatibility. Attempting to load omni::fabric::IStageReaderWriter with version v0.16 against v0.14.`
- Known cosmetic warning in Kit 110.x. Harmless. Kit boots cleanly despite it. Future-you will see this — don't be alarmed.

**Verification — Kit booted, then exited cleanly:**
- All ~50 extensions loaded
- "app ready" achieved at 11.225 seconds
- No errors, no segfaults
- Kit ran for 10 seconds (per --/app/quitAfter=10) and exited

**Issues encountered & resolution:**
- During Story 0.7 testing (Kit started without --quitAfter), Kit kept running and tmux foreground was occupied. Resolution: `Ctrl+C` in tmux pane killed Kit cleanly. Always run Kit with `--/app/quitAfter=N` for time-limited tests, or run in background with `&` for VNC sessions.

---

### Story 0.7 — VNC accessible from Mac (DONE 2026-05-08)

**What was done:**
- Started full VNC chain on cloud: x11vnc → websockify+noVNC
- Created SSH tunnel from Mac to cloud port 6080
- Opened browser at http://localhost:6080/vnc.html → noVNC web UI
- Started Kit (with window) → Kit's UI rendered live in Mac browser
- First visual proof of Phase 0 working: NVIDIA Omniverse Kit running on cloud GPU L4, displayed in Mac Chrome browser

**Architecture (mental model):**
```
Mac browser
  ↓ HTTPS to localhost:6080
[Mac terminal: SSH tunnel localhost:6080 → cloud:6080]
  ↓ encrypted SSH
[Cloud: websockify on 6080] (translates WebSocket to TCP)
  ↓ TCP localhost:5900
[Cloud: x11vnc on 5900] (reads Xvfb framebuffer)
  ↓ X11 protocol
[Cloud: Xvfb on :99] (virtual display)
  ↓ X11 rendering
[Cloud: Kit application]
  ↓ Vulkan
[NVIDIA L4 GPU]
```

**Working commands — cloud side (in tmux session):**
```bash
# Xvfb already running from Story 0.6
export DISPLAY=:99

# Start x11vnc (background, port 5900)
x11vnc -display :99 -forever -shared -rfbport 5900 -bg -o /tmp/x11vnc.log

# Verify x11vnc listening on 5900
ss -tlnp 2>/dev/null | grep 5900

# Start websockify + noVNC web UI on port 6080
websockify --web=/usr/share/novnc 6080 localhost:5900 &

# Verify websockify listening on 6080
ss -tlnp 2>/dev/null | grep 6080

# Start Kit in background (no quitAfter, real session)
./_build/linux-x86_64/release/com.sowthri.cdutwin.kit.sh > /tmp/kit-vnc.log 2>&1 &
```

**Working commands — Mac side (NEW terminal tab, NOT from cloud SSH):**
```bash
# IMPORTANT: this MUST run from your Mac shell, NOT inside cloud SSH session
# (The ~/.ssh/id_ed25519 path resolves to your Mac's ~/.ssh/, not cloud's)

# Verify on Mac (not cloud)
hostname  # should print SOWTHRIs-MacBook-Air.local

# Open SSH tunnel: Mac:6080 → cloud:6080
ssh -i ~/.ssh/id_ed25519 -L 6080:localhost:6080 -N ubuntu@<cloud-public-ip>
# Terminal hangs (no output) — that's success. Don't close this tab.

# In a SEPARATE Mac terminal tab:
lsof -i :6080
# Should show: ssh ... TCP localhost:6080 (LISTEN)

# Open in browser:
# http://localhost:6080/vnc.html
# Click "Connect"
# See Xvfb desktop (black + cursor when no app, or Kit window when running)
```

**Verification:**
- noVNC web UI loaded in browser
- Connect → black screen + mouse cursor (Xvfb's empty desktop)
- After Kit launched, Kit's full UI rendered in browser:
  - Title bar: "CDU Twin App"
  - Toolbar: File / Edit / Create / Window / Developer / Help
  - 3D viewport with Z/X/Y axis indicator
  - "RTX - Real-Time 2.0" renderer indicator
  - Stage panel: World (defaultPrim), Environment
  - 1280x720 render size
  - "RTX Loading 0.00%" progress overlay (one-time shader compile)
  - 2.6 GiB process memory used / 11.7 GiB available

**This is the visual proof Phase 0 worked.**

**Issues encountered & resolution:**
- *SSH tunnel command initially run from inside cloud SSH session* — failed with "/home/ubuntu/.ssh/id_ed25519 not accessible" because that path doesn't exist on cloud. **Resolution:** Always run the tunnel command from a fresh Mac terminal tab. Verify with `hostname` first — should print Mac hostname, not `ip-172-31-...`.
- *Three terminal tabs needed:* (1) cloud SSH for services, (2) Mac SSH tunnel (hangs silently), (3) Mac shell for `lsof` and other checks. New tabs open as Mac shell by default — they do NOT inherit the SSH session of other tabs.

**Cleanup commands (when done with VNC session):**
```bash
# Cloud side — kill in this order (top of chain down)
pkill -9 kit
pkill -9 websockify
pkill -9 x11vnc
pkill -9 Xvfb

# Verify all dead
ps aux | grep -E "kit|Xvfb|x11vnc|websockify" | grep -v grep
# Should be empty (only system noise like polkitd/packagekitd remains)

# Mac side — Ctrl+C on the SSH tunnel tab
# Then exit cloud SSH session
```

---

### What's NOT done yet in Phase 0

- **Story 0.8** — Phase 0 snapshot (EBS), document snapshot ID, test boot-from-snapshot (~15 min, ~$0.20)

After Story 0.8: Phase 0 closed. Phase 1 (CDU scene authoring in Kit + USD) starts.

---

### Story 0.8 — Phase 0 snapshot

(to be filled in)

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
| IAM | AWS Identity and Access Management — controls who can do what in an AWS account |
| MFA | Multi-Factor Authentication — second factor beyond password (TOTP code from app) |
| Quota | AWS limit on resource usage (e.g., max vCPUs of GPU instances). New accounts default to 0 for GPU. |
| L4 | NVIDIA L4 GPU (Ada Lovelace architecture, 24 GB VRAM). Our GPU. |
| AMI | Amazon Machine Image — pre-baked disk image AWS clones to your instance at boot |
| EBS | Elastic Block Store — AWS's persistent disk service. Billed per GiB-month even when stopped. |
| Instance store | Local NVMe SSD on the host. Free, ephemeral, wiped on stop. |
| g6.xlarge | Our chosen instance type: 4 vCPU, 16 GB RAM, 1x NVIDIA L4, $0.97/hr |
| Vulkan | Modern low-overhead graphics API. Kit's RTX renderer uses Vulkan to talk to the GPU. |
| Xvfb | X virtual framebuffer — fakes a display server for headless graphical apps |
| VNC | Virtual Network Computing — remote desktop protocol |
| noVNC | HTML/JS VNC client that runs in a browser tab |
| websockify | Proxy that translates WebSocket connections (browser-friendly) to raw TCP (VNC-friendly) |

---

## Common failure modes

### Saudi-issued card declined at Lambda Labs (2026-04-30)

**Symptom:** Card rejected at Lambda Labs payment processor at signup.
**Root cause:** Lambda's payment processor is restrictive about Saudi-issued cards. AWS uses a different processor that accepts them.
**Resolution:** Pivoted cloud provider to AWS.

### NGC menu reorganization — "Setup" became "Personal Keys" (2026-04-30)

**Symptom:** Charter said "Profile -> Setup" but the dropdown showed different menu items.
**Root cause:** NVIDIA redesigned NGC menus in 2024-2025.
**Resolution:** Direct URL: `https://ngc.nvidia.com/setup/personal-keys`. Of menu items, "Personal Keys" is the right one.

### AWS new account default GPU quota = 0 (2026-05-01)

**Symptom:** Cannot launch any G-family instance. Service Quotas shows applied limit of 0.
**Root cause:** AWS gates GPU access on new accounts as fraud prevention.
**Resolution:** File quota request for exactly 4 vCPUs. If form-based request denies (auto-decline is common for brand-new accounts), use Support chat for the appeal.

### AWS first quota request denied without explanation (2026-05-01)

**Symptom:** Submitted via Service Quotas form, denied within 30 min by automated system.
**Root cause:** Brand-new account + GPU request + no use case provided = automatic high-risk flagging.
**Resolution:** Always use AWS Support chat for first-time GPU requests. Provide: real project description, GitHub URL, specific minimum instance, cost controls.

### AWS quota approvals slow on weekends (2026-05-02 to 2026-05-05)

**Symptom:** Case submitted Friday evening Mumbai time, status still "Pending Amazon action" Saturday morning. Took 4 business days.
**Root cause:** AWS Trust & Safety / EC2 team is heavier weekday-staffed.
**Resolution:** File quota requests early in the week. Polite follow-up via chat after 3+ business days can move things along.

### Storage configuration UI auto-attaches unwanted volumes (2026-05-05)

**Symptom:** During EC2 launch wizard, an extra 8 GiB Volume 2 appeared with bad defaults.
**Root cause:** AWS launch wizard sometimes auto-attaches secondary volumes based on AMI defaults.
**Resolution:** Always inspect the Configure storage section before launching. Click Remove on unwanted volumes.

### Security group "Source type" dropdown sometimes lacks "My IP" (2026-05-05)

**Symptom:** When configuring inbound SSH rule, "Source type" dropdown didn't show My IP option.
**Root cause:** AWS UI inconsistency — depending on how rule was created.
**Resolution:** Remove the auto-created rule and add a fresh one via "Add security group rule" button.

### EC2 "insufficient capacity" across all AZs in a region (2026-05-06 to 2026-05-08)

**Symptom:** All three Mumbai AZs (1a, 1b, 1c) showed g6.xlarge as unavailable when trying to start a stopped instance OR launch a new one.
**Root cause:** Regional GPU capacity constraint. AWS has finite physical hardware in any region. Popular instance types run dry under demand spikes.
**Resolution:** Wait. Capacity returns within hours to a few days. Don't pivot to expensive AMI workarounds — they don't help (AMI launch hits the same capacity wall). Multi-region quota is the long-term fix (file quota request in Singapore as backup before you need it).

### NVIDIA Omniverse Kit AMI creation rejects em-dashes (2026-05-06)

**Symptom:** "Value (...) for parameter Description is invalid. Character sets beyond ASCII are not supported."
**Root cause:** AWS API fields require ASCII-only. Em-dashes (—), smart quotes, Unicode arrows all fail.
**Resolution:** Use plain ASCII hyphens (-) and straight quotes. When copy-pasting into AWS forms, watch for: em-dash (—), en-dash (–), smart quotes ("..."), curly apostrophes ('), bullet (•), arrows (→ ⇒).

### Kit App Template wizard placeholder text (2026-05-08)

**Symptom:** During `./repo.sh template new`, prompt fields are pre-filled with placeholder text (e.g., "my_company.my_editor", "My Editor"). Pressing Enter accepts the placeholder.
**Root cause:** Kit wizard doesn't clear placeholders when you start typing.
**Resolution:** Use `Ctrl+U` to clear each prompt before typing the correct value. Watch for placeholder text and clear it deliberately. Verify each line shows your intended value before pressing Enter.

### Kit `--/app/quitAfter` doesn't always trigger reliably (2026-05-08)

**Symptom:** Kit started with `--/app/quitAfter=10` but kept running in tmux foreground.
**Root cause:** Unclear — possibly only kicks in after full app initialization. Or interferes with `tee` log capture.
**Resolution:** Always have a way to manually kill Kit. Foreground: `Ctrl+C` in the tmux pane. Background (`&`): note the PID and use `kill <PID>` then `pkill -9 kit`.

### SSH tunnel command must run from Mac, not cloud (2026-05-08)

**Symptom:** `Warning: Identity file /home/ubuntu/.ssh/id_ed25519 not accessible: No such file or directory.`
**Root cause:** SSH tunnel command was run from inside the cloud SSH session. The `~` resolved to cloud's `/home/ubuntu/`, where the Mac's private key doesn't exist.
**Resolution:** Always open a fresh Mac terminal tab (Cmd+T) for the tunnel. Verify with `hostname` — should print `SOWTHRIs-MacBook-Air.local`, not `ip-172-31-...`. New tabs open as Mac shell by default; they do NOT inherit cloud SSH sessions.

---

## Decision log (cross-references PROJECT_CHARTER §11)

| Date | Decision | Why |
|---|---|---|
| 2026-04-29 | Charter locked: personal-demo scope, snapshot-driven, no public URL | Owner reviewed alternatives, chose this scope |
| 2026-04-29 | Monorepo at `SolutionPortfolio/AISolutions/RefineryTwin/`, not separate repos | Personal demo with one consumer (interviewer); monorepo simpler workflow |
| 2026-04-29 | HTTPS + PAT for git auth, NOT SSH for git | Owner preference; PAT cached in macOS keychain |
| 2026-04-29 | Repos public from day one | Owner preference for transparency and recruiter-readability |
| 2026-04-29 | Kit extension namespace: `com.sowthri.cdutwin` | Hyphens illegal in Python package names |
| 2026-04-30 | **PIVOT: Lambda Labs -> AWS** | Lambda declined Saudi card; AWS Mumbai accepts it and offers $120 credits. |
| 2026-04-30 | AWS region: ap-south-1 (Mumbai) | Closest with reliable g6 capacity; 120ms latency from Dammam; Aramco runs many workloads from Mumbai (interview relevance) |
| 2026-04-30 | Instance type: g6.xlarge (L4 GPU) instead of g5.xlarge (A10G) | Newer Ada architecture, 20% cheaper, equivalent capability for Omniverse Kit |
| 2026-04-30 | AWS Budgets: $10 early warning + $100 monthly cap | Realistic for $0.97/hr × ~125-hour project usage |
| 2026-05-01 | JarvisLabs (https://jarvislabs.ai) chosen as Plan B if AWS denies | Indian provider, instant access, $0.44/hr L4. Plan B never activated (card declined when tested 2026-05-07) but kept documented. |
| 2026-05-05 | AWS GPU quota appeal granted via human Support chat (4 vCPUs in ap-south-1) | First request auto-denied; appeal via chat with detailed use case + GitHub URL succeeded in 4 business days |
| 2026-05-05 | EBS root volume sized at 200 GiB gp3, encrypted, delete-on-termination=Yes | Sized for full project: Kit (~30 GB) + Isaac Sim (~50 GB) + drivers + USD + buffer |
| 2026-05-06 | Created AMI `refinery-twin-gpu-image-v1` then deregistered after realizing it wouldn't help with capacity | Capacity issue affects ALL g6 launches in region, not specific instances. AMI was unnecessary insurance. |
| 2026-05-08 | Kit App Template version `110.1.1+main.0.f130d19b.local` chosen (NVIDIA's main branch latest) | Most recent stable Kit. Includes RTX Real-Time 2.0, omni.warp.core 1.13, omni.physx 110.1.1 |
| 2026-05-08 | Kept stopped AWS instance during JarvisLabs evaluation rather than terminating | Useful as proven-working AWS state if JarvisLabs evaluation hit blockers. ~$16/month EBS cost, covered by credits. JarvisLabs card was declined; AWS path resumed cleanly. |

---

**Operator runbook end. Append-only.**
