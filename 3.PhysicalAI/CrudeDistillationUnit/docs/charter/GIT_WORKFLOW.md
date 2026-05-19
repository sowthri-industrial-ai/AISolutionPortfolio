# Git Workflow

How code, docs, and decisions move between this Mac, the cloud GPU
instance, and GitHub. This is a derived document — it implements
charter §7 (repo structure) and supports principle 8 (durable
knowledge in the runbook).

If anything in this document conflicts with the charter, the charter
wins. Flag the contradiction.

---

## 1. Where things live

**Canonical home for the project:**
```
github.com/sowthri-industrial-ai/SolutionPortfolio
└── AISolutions/refinery-twin/    ← project root
```

**Local on the Mac:**
```
~/Documents/SolutionPortfolio/AISolutions/refinery-twin/
```

(The Mac path mirrors the GitHub path inside `~/Documents/`. This is
just a convention to avoid mental load — the path on the cloud
instance will be different.)

**On the cloud instance:**
```
~/SolutionPortfolio/AISolutions/refinery-twin/
```

(Cloud is just `~/`, no `Documents/` subdirectory. Linux-shaped paths.)

A shell alias is the polite thing to do on the cloud:

```bash
alias cdrt='cd ~/SolutionPortfolio/AISolutions/refinery-twin'
```

Add it to `~/.bashrc` on the cloud instance during Phase 0.

---

## 2. Authentication: HTTPS + token

Decision (charter §11, dated 2026-04-29): no SSH keys for git. HTTPS
with a Personal Access Token (PAT), stored in the OS keychain on Mac
and in git credential cache on the cloud instance.

### Mac setup (one time)

If you've cloned anything from `sowthri-industrial-ai` or any other
GitHub URL recently, you've already done this. Verify:

```bash
git config --global credential.helper
# expected output:  osxkeychain
```

If it returns nothing, set it:

```bash
git config --global credential.helper osxkeychain
```

The first time you `git push`, a dialog will prompt for username +
password. Username is your GitHub username. **Password is a Personal
Access Token, not your GitHub login password.**

### Generate a Personal Access Token

1. Go to https://github.com/settings/tokens
2. Click **Generate new token** → **Generate new token (classic)**
3. Note: `refinery-twin project` (or similar — this is just for your
   reference)
4. Expiration: 90 days (project should finish well before this)
5. Scopes: tick **repo** (full control of private repos — but we're
   public, this still grants the necessary write access)
6. Click **Generate token**, copy it immediately, save in your password
   manager under "GitHub PAT — refinery-twin"

The token is shown once. If you lose it, generate a new one.

### Cloud instance setup (during Phase 0)

On the cloud instance, after cloning:

```bash
git config --global credential.helper 'cache --timeout=86400'
git config --global user.email "your-email@example.com"
git config --global user.name "Your Name"
```

The `cache` helper holds the token in memory for 24 hours. After
SSH'ing back in past 24h you re-enter once. This avoids putting the
token on disk anywhere on the cloud instance.

First push from cloud will prompt for username (your GitHub username)
and password (the PAT from above).

---

## 3. The simplest workflow: cloud writes, Mac reads

Single source of truth: the cloud instance is where the real work
happens during Phases 0–4. The Mac is for reading, planning, and
docs-only edits.

**Discipline (memorize):**
- On the cloud, before stopping the instance for the day:
  ```bash
  cd ~/SolutionPortfolio
  git add -A
  git status              # eyeball what's staged
  git commit -m "..."
  git push origin main
  ```
- On the Mac, before reading or editing anything:
  ```bash
  cd ~/Documents/SolutionPortfolio
  git pull origin main
  ```

That is the whole workflow. Two commands the cloud runs, one command
the Mac runs.

**Why this is safe:**
- Single writer per period (cloud during work, Mac only for docs edits at non-work time)
- No branch coordination needed
- No merge conflicts unless both edit the same file at the same time, which discipline prevents

**When to deviate from this:**
- Editing the charter itself, or BACKLOG_PHASE_*.md, or this document — all of these can be Mac-side edits during the day, since the cloud doesn't touch them. Just remember to `git pull` on the cloud after pushing the doc edit, before you start coding.

---

## 4. What NEVER goes in git

These rules are non-negotiable. Public repo means leaks are
irreversible — once pushed and pulled, even a force-push doesn't
guarantee deletion (caches, mirrors, GitHub's own dangling commits).

**Secrets:**
- ❌ NGC API key
- ❌ GitHub PAT (we just generated one)
- ❌ AWS / Azure / Lambda Labs API keys or credentials
- ❌ SSH private keys (`id_ed25519`, `id_rsa`, etc.)
- ❌ `.env` files containing tokens
- ❌ Any file with literal "password", "secret", "api_key" content

**Operational data:**
- ❌ Cloud instance public IPs (mild risk — strangers can SSH-knock)
- ❌ User-specific paths if they reveal anything (`/Users/<your-name>/...` rarely matters but be thoughtful)
- ❌ Lambda Labs invoice screenshots
- ❌ NVIDIA NGC org name if it's a company secret

**Generated / large artifacts:**
- ❌ `out/` directories produced by the asset library (regenerable)
- ❌ Screen recordings over 100 MB (use Git LFS or external host; see §6)
- ❌ Kit build output (`_build/`, `_compiler/`)
- ❌ Python `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`
- ❌ macOS `.DS_Store`
- ❌ Editor swap files (`.swp`, `.swo`, `~` backups)
- ❌ Virtual environments (`.venv/`, `venv/`)

**Required `.gitignore` for the project root:**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/
.mypy_cache/
.ruff_cache/
.venv/
venv/
env/
*.egg-info/

# OS
.DS_Store
Thumbs.db

# Editors
*.swp
*.swo
.vscode/
.idea/

# Project artifacts
out/
*/out/
**/out/
_build/
_compiler/
_repo/
*.usdc           # only if regenerable; remove if hand-authored
*.tmp

# Secrets — defense in depth
.env
.env.*
*.pem
*.key
ngc-api-key.txt
github-token.txt

# Large media (use docs/media/ with restraint)
*.mov
*.mp4.bak
```

I'll deliver this as `.gitignore` content during Story 0.0.

### Pre-commit safety check

Before every push, eyeball the diff:

```bash
git diff --cached
```

Look for: any string that resembles a token (long random-looking
strings of letters and digits), any literal IP address that shouldn't
be public, any path under `/etc/` or `~/.ssh/`. If something looks
off, abort with `git reset HEAD <file>` and investigate.

---

## 5. Commit message convention

Public commit history is part of your portfolio. Recruiters and
interviewers can and will scroll your commits. Make them readable.

**Format:**
```
<phase>/<story>: <verb-led description, ≤72 chars>

<optional body, wrap at 72 chars>
<what changed and why; "what" is in the diff, "why" is what we want>
```

**Examples (good):**
```
phase-0/0.5: bootstrap Kit App Template, base editor variant

phase-1/1.3: load CDU1.usda in viewport, RTX path tracing enabled

phase-2/2.4: wire panel buttons to extension state machine

docs: capture Vulkan version that works on Lambda image v23.04
```

**Examples (avoid):**
```
fix
wip
update files
checkpoint
asdf
```

**The rule:** if a hiring manager scans your commit log and sees only
`fix` and `wip` for two weeks, it tells them you're sloppy under
pressure. Five extra seconds of thought per commit is cheap.

### When to commit

- At each story DoD checkpoint (recommended baseline)
- When you've solved a problem worth memorializing in the runbook
- Before stopping the cloud instance for the day (always)
- Before any potentially destructive change (gives you a rollback)

Don't commit at every saved file. Don't commit broken code if
avoidable; if you must (end of day, broken state), prefix the message
with `WIP:` and aim to clean up first thing next morning.

---

## 6. Large media files

Screen recordings and screenshots are project artifacts. The 90-second
demo video might be 30-100+ MB depending on resolution and codec.

**Policy:**
- Files under 5 MB → commit directly to `docs/media/`
- Files 5-50 MB → commit but compress aggressively first (e.g.
  `ffmpeg -crf 28 -preset slow`)
- Files 50-100 MB → use Git LFS:
  ```bash
  git lfs track "docs/media/*.mp4"
  git add .gitattributes
  ```
- Files over 100 MB → external host (YouTube unlisted, Vimeo, S3) and
  link from the README. GitHub's hard limit on a single file is 100
  MB; LFS handles up to 2 GB but counts against bandwidth quotas.

The headline 90-second demo video will likely be 20-40 MB if encoded
sensibly. Direct commit is fine.

---

## 7. Branching policy

**Default policy: trunk-based, no branches.**

For this project, with one developer and a tight phase structure,
branches are overhead without payoff. Commit to `main`. The phase gate
itself acts as a quality bar; we don't need a `develop` branch or PR
review (the architect review is the PR review, conducted in chat).

**Exceptions where a branch makes sense:**
- Trying a major refactor that might fail. Branch, attempt, evaluate,
  merge or discard. (But charter rule 1: refactors are rare and need
  architect approval.)
- Phase 5: pre-release polish where you want to record a clean state
  before final tweaks. Tag the commit with a `vX.Y` instead of
  branching.

If you find yourself wanting branches for daily work, you're probably
over-engineering. Stop and ask the architect.

---

## 8. Tags for milestones

At the end of every phase gate review, tag the commit:

```bash
git tag -a phase-0-complete -m "Phase 0 gate review passed YYYY-MM-DD"
git push origin --tags
```

Tags are searchable on GitHub (e.g. `https://github.com/.../tags`)
and become navigation anchors in the project history. Useful for
demos: "let me show you the state at end of Phase 3" → checkout the
tag.

---

## 9. The first commit checklist (Story 0.0)

When you do the very first commit of refinery-twin work to
SolutionPortfolio, verify:

- [ ] You're on `main` branch (`git branch --show-current`)
- [ ] You've pulled the latest first (`git pull origin main`)
- [ ] The path you're committing is `AISolutions/refinery-twin/`
- [ ] `.gitignore` is included (or already exists at the repo root)
- [ ] No `.venv/`, no `.DS_Store`, no `__pycache__/` in the diff
- [ ] No NGC keys, no PAT, no IPs in the diff
- [ ] Commit message follows the convention from §5

---

## 10. Recovery from common mistakes

**Committed something sensitive (e.g. a key):**
1. Stop. Do not push if you haven't yet.
2. If pushed already: rotate the credential immediately (regenerate
   the NGC key, revoke the PAT, etc.) — assume it's compromised.
3. Then deal with git history if you want it clean: `git filter-repo`
   is the right tool. **History rewriting is non-trivial; ask
   architect before attempting on a public repo.**
4. Log the incident in OPERATOR_RUNBOOK under "Common failure modes."

**Committed `.venv/` or `out/` by accident:**
1. Add to `.gitignore` if not already.
2. `git rm -r --cached .venv out` (removes from tracking, not from
   disk).
3. Commit with message `chore: remove accidentally tracked artifacts`.

**Force-push regret:**
1. Stop and call architect. Force-pushes on a public repo are nearly
   always a mistake during a project of this kind. Recovery options
   exist via `git reflog` but require care.

---

**Git workflow end.**
