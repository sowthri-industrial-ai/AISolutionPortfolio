# Cloud Runbook — Day 1 (Phase 0 kickoff)

This is the concrete what-to-do-today document. It assumes you've
read the PROJECT_CHARTER and CLAUDE_CODE_AGREEMENT.

Goal for today (Story 0.1 + 0.2): get a Lambda Labs A6000 instance
running and SSH-able, with NGC and GitHub setup confirmed. **Today
does not include installing Omniverse Kit yet** — that's tomorrow.

Today's expected duration: 60-90 minutes.
Today's expected cost: under $1 (you'll launch the instance late and
shut it off after smoke testing).

---

## Pre-flight (15 min) — Story 0.1

### SSH key

Run on your Mac:

```bash
ls -la ~/.ssh/id_ed25519.pub
```

If that file exists, you're done. If not:

```bash
ssh-keygen -t ed25519 -C "your-email@example.com"
# press Enter through all prompts
# default location, no passphrase
```

Then copy the public key to clipboard:

```bash
cat ~/.ssh/id_ed25519.pub | pbcopy
```

### NGC account (NVIDIA GPU Cloud)

1. Go to <https://ngc.nvidia.com>
2. Sign up (free) — use the same email you'll use for Lambda
3. After login, go to your profile → **Setup** → **Generate API Key**
4. **Copy the API key immediately** — it's shown only once
5. Save in a password manager under "NGC API Key"

You'll need this in Phase 4 (Isaac Sim install) and possibly Phase 0
(if Kit pulls anything from NGC). Have it ready.

### GitHub handle confirmation

Decide and write down: which GitHub username will own these repos?
This becomes part of the extension namespace (`com.<handle>.cdutwin`),
so it's locked early. Acceptable handles are alphanumeric + hyphens,
no underscores (extension namespacing is fussy).

Write it in `cloud_notes.md`:

```bash
cd ~/Documents/AISolutions/2.refinery-twin-prep
echo "GitHub handle: <your-handle>" >> cloud_notes.md
```

### Local tools

```bash
which ssh tmux git
# tmux not found? install:
brew install tmux
```

---

## Lambda Labs setup (20 min) — Story 0.2

### Account

1. Go to <https://lambdalabs.com>
2. Sign up if you haven't already
3. Verify email
4. Add payment method (credit card)
5. Go to **SSH keys** → paste your public key from earlier (the contents of `~/.ssh/id_ed25519.pub`)

### Launch instance

1. Go to **Instances** → **Launch instance**
2. Region: pick one close to you (Frankfurt/N. Virginia for KSA — both ~150ms latency, fine for SSH)
3. Instance type: **gpu_1x_a6000** ($0.80/hr)
4. Storage: **default 200 GB** is correct, don't reduce
5. SSH key: select the one you uploaded
6. Click **Launch**
7. Wait ~90 seconds for status to flip to **Running**
8. Copy the public IP

### First SSH

In your Mac terminal:

```bash
ssh ubuntu@<paste-ip>
# accept the host key when prompted (yes)
```

If you get connected, you'll see Ubuntu's welcome banner. If you get
a connection error, verify:
- The IP is correct (sometimes copy/paste adds whitespace)
- You're using the right SSH key (`ssh -i ~/.ssh/id_ed25519 ubuntu@<ip>` if needed)
- Your Mac's network isn't blocking outbound port 22

### Smoke test on the instance

You're now logged into the cloud GPU. Run:

```bash
nvidia-smi
```

Expected output: a table showing the A6000 GPU, ~48 GB VRAM, driver
version (note this in `cloud_notes.md` — the driver version matters
later). If `nvidia-smi` doesn't work, this is a Lambda issue —
terminate the instance, contact Lambda support, launch a fresh one in
a different region.

### Set up tmux on the instance

This protects long-running commands from network hiccups.

```bash
sudo apt-get install -y tmux
tmux new -s refinery
```

You're now in a tmux session. If your SSH disconnects, your work
keeps running. To reattach next time:

```bash
ssh ubuntu@<ip>
tmux attach -t refinery
```

### Stop the instance for now

You don't need to keep paying $0.80/hr while reading the rest of
today's plan. From the Lambda console:

1. Click your instance
2. Click **Stop** (NOT Terminate — Stop preserves the instance, Terminate destroys it)
3. Confirm

You'll resume work tomorrow with Story 0.3 (system dependencies).

---

## Initialize the OPERATOR_RUNBOOK (10 min)

Back on your Mac:

```bash
cd ~/Documents/AISolutions/2.refinery-twin-prep
mkdir -p refinery-twin/docs
touch refinery-twin/docs/OPERATOR_RUNBOOK.md
open -e refinery-twin/docs/OPERATOR_RUNBOOK.md
```

Paste this into the runbook to seed it:

````markdown
# Operator Runbook — Refinery Twin

This runbook is the cumulative record of every working command, every
solved problem, every gotcha discovered during the project. It exists
so the build knowledge doesn't live only on a server we'll someday
terminate.

Charter principle 8: if it's not in the runbook, it didn't happen.

---

## Day-1 Setup

### My environment
- GitHub handle: <your-handle>
- Local working directory: ~/Documents/AISolutions/2.refinery-twin-prep
- Local Python: 3.11.3 in `.venv`

### Lambda Labs
- Account email: <your-email>
- Region used: <region>
- Instance type: gpu_1x_a6000
- Driver version (from nvidia-smi): <version>
- Public IP (current instance): <ip>
- SSH command: `ssh ubuntu@<ip>` then `tmux attach -t refinery`

### NGC
- Account email: <your-email>
- API key location: stored in password manager as "NGC API Key"

### Snapshots
| Date | Phase | Snapshot ID | Notes |
|---|---|---|---|
| | | | |

### Cost log
| Date | Hours used | Cost (USD) | Notes |
|---|---|---|---|
| | | | |

---

## Phase 0 — Foundation

(in progress)

### Story 0.1 — Pre-flight (DONE on YYYY-MM-DD)
- Confirmed: SSH key exists at ~/.ssh/id_ed25519
- Confirmed: NGC account created, API key generated
- Confirmed: GitHub handle = <handle>

### Story 0.2 — Lambda instance launched (DONE on YYYY-MM-DD)
- Instance launched in <region>
- nvidia-smi shows A6000 with driver <version>
- tmux session "refinery" set up
- Instance currently STOPPED (resume tomorrow)

### Story 0.3 — System dependencies (TODO)
### Story 0.4 — Vulkan + GPU smoke test (TODO)
### Story 0.5 — Kit App Template build (TODO)
### Story 0.6 — Xvfb + Kit headless boot (TODO)
### Story 0.7 — VNC accessible from Mac (TODO)
### Story 0.8 — Phase 0 snapshot (TODO)
### Story 0.9 — Phase 0 gate review (TODO)
````

Fill in the bracketed placeholders with your actual values.

---

## End-of-day check-in to architect

When you're done with Story 0.1 and 0.2, paste back to the architect
(in our chat):

```
Day 1 complete:
- Story 0.1: SSH key + NGC account + GitHub handle = <handle> + tools confirmed
- Story 0.2: Lambda A6000 in <region>, IP <ip>, tmux ready, currently stopped
- Driver version: <version>
- OPERATOR_RUNBOOK initialized at refinery-twin/docs/OPERATOR_RUNBOOK.md
- Cost so far: <hours × $0.80>
- Ready for Story 0.3 tomorrow.

Issues or questions: <any>
```

The architect will respond with the Story 0.3 prompt for Claude Code.

---

## Don't do today

These things look like reasonable next steps but should NOT happen
today:

- ❌ Don't launch Claude Code yet against the cloud instance — Story 0.3 hasn't been prompted
- ❌ Don't install Omniverse — Story 0.5
- ❌ Don't clone any of the project repos to the cloud yet — Phase 1
- ❌ Don't try to "get a head start" on tomorrow's work — Phase 0 is intentionally paced

Charter principle: working software at end of every phase. Today's
Phase 0 deliverable is "instance launched, identities verified" — that
is enough. Stop there.

---

## If something fails today

### SSH won't connect
- Verify IP from Lambda console, not from memory
- Try `ssh -v ubuntu@<ip>` for verbose output
- Check `~/.ssh/known_hosts` for stale entries: `ssh-keygen -R <ip>`
- If still stuck after 15 min: stop, document what you see, paste to architect

### nvidia-smi doesn't work on the instance
- This is a Lambda image issue — terminate the instance, contact Lambda support
- Don't try to install drivers yourself — Lambda's image is supposed to have them

### NGC API key generation fails
- Try in a different browser
- Sometimes NGC requires a profile completion step before generating keys

### You ran out of time today
- Stop the Lambda instance to halt billing
- Update the runbook with what you got done
- Tell the architect; tomorrow's plan adjusts

---

**Day 1 runbook end. Tomorrow's runbook (Story 0.3 onward) is delivered after architect reviews tonight's check-in.**
