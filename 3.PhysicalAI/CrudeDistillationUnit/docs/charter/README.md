# Refinery Twin — Project Documents

This is the index. Read the files in this order on your first
session:

---

## 1. Read first (10 min)

**[PROJECT_CHARTER.md](./PROJECT_CHARTER.md)**

The master document. What we're building, what we're not, why, and
how we'll know we're done. **Binding** — every later document derives
from this. If you read only one document, read this.

---

## 2. Read second (5 min)

**[CLAUDE_CODE_AGREEMENT.md](./CLAUDE_CODE_AGREEMENT.md)**

The standing rules for Claude Code over the project lifetime. The
roles, the responsibilities, the anti-patterns. Read at the start of
every Claude Code session. Reread when something feels off.

---

## 3. Read third (8 min)

**[GIT_WORKFLOW.md](./GIT_WORKFLOW.md)**

How code, docs, and decisions move between Mac, cloud, and GitHub.
Auth setup, what NEVER goes in git, commit conventions, the
cloud-writes-Mac-reads pattern. Read before Story 0.0; reread before
the first Phase 0 cloud session.

---

## 4. Read fourth (10 min)

**[ROADMAP.md](./ROADMAP.md)**

Week-by-week plan. Phases, durations, gates, risks. This will be
wrong by Week 2 — that's expected, we revise at every phase boundary.
Read it for the shape, not the exact dates.

---

## 5. Active work (right now)

**[BACKLOG_PHASE_0.md](./BACKLOG_PHASE_0.md)**

Story-level detail for Phase 0 only. This is what you actually do
this week. Phase 1 backlog gets written at end of Phase 0.

**[CLOUD_RUNBOOK_DAY_1.md](./CLOUD_RUNBOOK_DAY_1.md)**

The concrete what-to-do-today document for Stories 0.1 and 0.2.
Lambda Labs signup, NGC account, SSH, first instance launch, smoke
test. Today's deliverable: instance running, identities verified.

---

## 6. Reference & ongoing

**[RUNBOOK_TEMPLATE.md](./RUNBOOK_TEMPLATE.md)**

Empty operator runbook template. Copy this to your project's
`refinery-twin/docs/OPERATOR_RUNBOOK.md` and fill it in as you work.
**The runbook is a mandatory project artifact, not optional.**

---

## What's where (file map)

```
charter/
├── README.md                    ← you are here
├── PROJECT_CHARTER.md           ← master, binding
├── CLAUDE_CODE_AGREEMENT.md     ← standing rules, every session
├── GIT_WORKFLOW.md              ← how code moves between Mac/cloud/GitHub
├── ROADMAP.md                   ← week-by-week
├── BACKLOG_PHASE_0.md           ← active stories for Phase 0
├── CLOUD_RUNBOOK_DAY_1.md       ← what to do on cloud (Stories 0.1-0.2)
└── RUNBOOK_TEMPLATE.md          ← copy this to your project
```

---

## Workflow per phase

```
Architect writes BACKLOG_PHASE_<N>.md with story detail
  ↓
Owner picks Story N.1 prompt from architect
  ↓
Owner pastes session-prep prompt into Claude Code
  ↓
Claude Code executes, reports
  ↓
Owner pastes session-close summary back to architect
  ↓
Architect verifies story DoD
  ↓
Repeat for next story
  ↓ (at end of phase)
Architect-facilitated phase gate review
  ↓
Architect writes BACKLOG_PHASE_<N+1>.md
  ↓
Loop
```

---

## Today's specific action

**Story 0.0 — Project skeleton in git.** Open
**[BACKLOG_PHASE_0.md](./BACKLOG_PHASE_0.md)** and execute Story 0.0
in order. Time required: 30 min. Outcome: `AISolutions/refinery-twin/`
exists in the SolutionPortfolio repo on GitHub, with charter docs,
runbook, and `.gitignore` committed and tagged `phase-0-start`.

After Story 0.0 is done, **stop**. Story 0.1 (cloud pre-flight) is
tomorrow morning, fresh, in a fresh Claude Code session against the
new repo location.

When done with Story 0.0, paste the day's check-in to architect using
the template in `CLAUDE_CODE_AGREEMENT.md` §6.

---

**Ship safely.**
