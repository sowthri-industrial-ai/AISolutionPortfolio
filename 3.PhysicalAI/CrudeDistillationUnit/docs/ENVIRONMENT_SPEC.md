# RefineryTwin — Cloud GPU Environment Specification

**Date documented:** 2026-05-08
**Status:** Phase 0 infrastructure complete; Kit application booting and rendering via remote viewer

---

## Summary

A cloud-based NVIDIA Omniverse Kit development environment, built on AWS EC2, accessed remotely from a Mac via SSH tunnel and browser-based VNC. The configuration provides a workstation-class GPU rendering capability without owning or maintaining workstation hardware. Total monthly cost approximately $25-50 depending on usage hours; covered by AWS promotional credits during the project.

The setup is the foundation for a refinery digital twin demo built on NVIDIA Omniverse Kit and Isaac Sim. It enables real-time RTX-rendered 3D scene authoring, custom Python extension development, and physics-based safety scenario simulation — all running on a remote GPU but visible and interactive from a personal laptop.

---

## Hardware

| Component | Specification |
|---|---|
| **GPU** | 1× NVIDIA L4 (Ada Lovelace architecture, RTX-capable, RT Cores) |
| **GPU memory** | 24 GB GDDR6 (23,034 MiB usable after driver overhead) |
| **GPU power envelope** | 72W max (idle ~12W) |
| **CPU** | 4 vCPUs (AWS g6.xlarge — Intel Sapphire Rapids equivalent) |
| **RAM** | 16 GiB DDR5 |
| **Primary storage (EBS)** | 200 GiB gp3 SSD, encrypted, 3000 IOPS, 125 MiB/s throughput |
| **Scratch storage (instance store)** | 250 GB local NVMe SSD (free, ephemeral) |
| **Network** | Up to 10 Gbps (AWS Enhanced Networking via ENA) |

**Physical location:** AWS Mumbai region, Availability Zone ap-south-1b
**Architecture:** x86_64

---

## Software stack

### Operating system
- **Ubuntu 22.04 LTS** (Jammy Jellyfish)
- AMI: AWS Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.6.0 (build 20260103)

### NVIDIA stack
- **GPU driver:** 580.105.08 (NVIDIA proprietary)
- **CUDA:** 13.0 (runtime); 12.6 (default toolkit)
- **Vulkan API:** 1.4.312 (NVIDIA ICD)

### Graphics rendering chain
- **Vulkan runtime:** libvulkan1, mesa-vulkan-drivers, vulkan-tools
- **Virtual display server:** Xvfb (X Virtual Framebuffer) on display `:99`, 1920×1080×24-bit
- **Display extensions enabled:** GLX, Render

### NVIDIA Omniverse
- **Kit SDK:** 110.1.1+main (production manylinux build)
- **Application:** `com.sowthri.cdutwin` v0.1.0 (Kit Base Editor template)
- **Build tooling:** kit-app-template (NVIDIA-Omniverse GitHub, main branch)
- **Renderer:** RTX Real-Time 2.0
- **Loaded extensions:** ~50 standard Kit extensions including
  - `omni.physx.gpu` — PhysX rigid-body and articulation physics on GPU
  - `omni.usd.metrics.assembler` — USD scene composition
  - `omni.warp.core` — NVIDIA Warp simulation framework
  - `omni.kit.window.*` — UI panels (Stage, Console, Toolbar, etc.)

### Remote access stack
- **VNC server:** x11vnc (bridges Xvfb framebuffer to TCP port 5900)
- **WebSocket proxy:** websockify with bundled noVNC web client (port 6080)
- **Web UI:** noVNC HTML5 client served from `/usr/share/novnc`
- **Tunnel encryption:** SSH (OpenSSH, ed25519 key authentication)

### Development tools
- **Shell:** bash with tmux (terminal multiplexer for persistent sessions)
- **Version control:** Git 2.34.1
- **Build dependencies:** build-essential (make, gcc, etc.)

---

## Network architecture

### End-to-end rendering path

```
[Mac browser]
    │  HTTP/WebSocket
    │
[Mac: localhost:6080 (SSH-forwarded)]
    │
    │  SSH tunnel — encrypted
    │  Internet (public IP, AWS data center peering)
    │
[Cloud: localhost:6080 (websockify)]
    │  WebSocket → TCP translation
    │
[Cloud: localhost:5900 (x11vnc)]
    │  X11 framebuffer capture
    │
[Cloud: Xvfb display :99]
    │  X11 protocol
    │
[Cloud: NVIDIA Omniverse Kit application]
    │  Vulkan API
    │
[Cloud: NVIDIA L4 GPU]
```

### Inbound firewall (AWS Security Group `refinery-twin-sg`)

| Port | Protocol | Source | Purpose |
|---|---|---|---|
| 22 | TCP | My IP only (`5.244.109.155/32`) | SSH access for shell + tunnel |

All other inbound ports closed. VNC traffic flows through the SSH tunnel — no direct exposure of port 5900 or 6080 to the public internet.

### Outbound

Default permissive (all ports out) — required for:
- Apt package downloads (Ubuntu repos)
- Kit SDK + extension downloads (NVIDIA CDN, packman)
- GitHub clones
- License verification

### Latency profile

| Hop | Approximate latency |
|---|---|
| Dammam, Saudi Arabia → Mumbai (AWS) | ~120 ms |
| End-to-end (Mac browser → cloud GPU → Mac browser) | ~150 ms |

Latency is acceptable for SSH-driven development and viewport interaction. Frame-by-frame GPU streaming would benefit from lower latency (e.g., Bahrain or UAE region), but those are not currently available with g6 capacity.

---

## Identity and access

| Resource | Identity used |
|---|---|
| AWS console (administrative) | IAM user `sowthri-admin` (not root) |
| AWS root account | MFA-protected, used only for billing emergencies |
| Cloud Linux machine | Linux user `ubuntu` (default for AWS Deep Learning AMI) |
| GitHub | Personal Access Token in macOS keychain (HTTPS authentication) |
| NGC (NVIDIA software registry) | Personal Key for container image pulls |

SSH authentication is public-key only (no passwords). Private key (`~/.ssh/id_ed25519`) lives on Mac, never traverses the network. Public key uploaded to AWS Key Pair `sowthri-mac-refinery-twin` and auto-injected into instance at boot.

---

## Cost model

| Item | Rate | Notes |
|---|---|---|
| g6.xlarge compute (running) | $0.97/hour | Billed per-second |
| g6.xlarge compute (stopped) | $0/hour | No compute charge |
| EBS storage (200 GiB gp3) | ~$16/month | Charged regardless of instance state |
| Data transfer (outbound) | First 100 GB/month free | Then ~$0.09/GB |
| **Estimated total project cost** | **~$25-50/month at moderate usage** | Covered by $120 AWS promotional credits |

**Discipline:** Instance is stopped at the end of every work session. Running 24/7 would cost ~$700/month — discipline matters more than budgets.

---

## Why these choices

**Why g6.xlarge over alternatives:**
- L4 has RT Cores (Ada architecture) — required for Isaac Sim and Omniverse RTX rendering
- 24 GB VRAM fits Kit + Isaac Sim with headroom for moderate scenes
- $0.97/hour is the lowest-cost RT-capable AWS instance
- Newer than g5.xlarge (A10G) and 20% cheaper

**Why Mumbai region:**
- 120 ms from Dammam — interactive SSH and viewport work feel responsive
- Aramco operates significant cloud workloads from Mumbai (interview-relevant geography)
- AWS promotional credits applicable

**Why VNC over alternatives:**
- Browser-based access (noVNC) — no client install required on the Mac
- Encrypted via SSH tunnel — no firewall changes needed
- Standard, mature, troubleshootable
- Future option: NVIDIA Omniverse Kit Streaming (WebRTC) for production-grade frame delivery

**Why Ubuntu 22.04 over 24.04:**
- NVIDIA Omniverse Kit and Isaac Sim explicitly tested and supported on 22.04
- Larger community knowledge base for debugging
- Slightly older glibc/kernel but stability matters more than recency for graphics-heavy work

---

## What this enables

With this configuration in place, the following work becomes possible from a personal laptop:

1. **3D scene authoring** in Kit Base Editor — building the refinery USD scene with CDU equipment
2. **Custom Python extensions** — implementing the `com.sowthri.cdutwin` extension for industrial control panels
3. **Real-time RTX rendering** — path-traced visualization of the digital twin
4. **OPC-UA data binding** — connecting live process data to scene parameters via Kit Fabric
5. **Physics-based scenarios** — Isaac Sim integration for safety simulations (gas dispersion, rover inspection, valve operation)
6. **Persistent state** — instance can be stopped/started indefinitely, EBS preserves all software and project files

The infrastructure supports the full 5-week project timeline through Phase 1 (scene), Phase 2 (extension), Phase 3 (data binding), Phase 4 (Isaac Sim), and Phase 5 (polish + recording).

---

**Document version:** 1.0
**Maintained in:** `~/Documents/SolutionPortfolio/AISolutions/RefineryTwin/docs/`
