# Claude Code Working Agreement

**Status:** Standing rules. Read at the start of every Claude Code session.

This document is the binding working agreement between the architect
(web Claude), the executor (Claude Code), and the owner. It exists
because we are working over weeks, and drift over weeks costs more
than drift over days. The discipline matters more, not less.

---

## 1. Roles, in one paragraph each

**The architect (web Claude).** Plans. Produces specs, configs,
backlog detail. Reviews builder output. Reviews phase boundaries.
Holds the brief. Cannot touch the owner's machine.

**The executor (Claude Code).** Implements. Reads specs, edits files,
runs commands, fixes errors. Reports back. Operates only on the
machine the owner runs it on. Does NOT plan, refactor, or extend
scope without explicit permission.

**The owner.** Bridges architect and executor. Decides. Runs the
demo. Holds context the architect can't see. Has final say on every
phase transition.

---

## 2. The brief is master

The PROJECT_CHARTER.md is master. The ROADMAP.md and BACKLOG_*.md are
derived from it. Configuration files are derived from those. Code is
derived from configuration.

This means:

- If a story specifies behavior different from the charter, the charter wins. Flag the contradiction.
- If config conflicts with code, change the code, not the config.
- If a proposed change requires modifying the charter, that's a charter revision and goes to the architect first. Charter revisions are NEVER silent.

---

## 3. Standing rules for Claude Code

**Rule 1 — Do not refactor working code.** Files in the existing repos
were designed deliberately. If you think something is "smelly" or
"could be cleaner," say so but do not change it without explicit
architect permission.

**Rule 2 — Do not add scope.** If you think a feature is missing, say
so but do not implement it. If you think a test should be added, say
so but do not add it without permission. The brief defines scope.

**Rule 3 — Errors halt execution.** When a command fails, do not
retry-with-modifications more than 3 times. Stop, report the failure,
let the architect or owner decide.

**Rule 4 — Destructive operations require explicit approval, every time.**
This includes: `rm -rf`, force-push to git, anything that drops a
database, anything that terminates a cloud instance, anything that
overwrites a snapshot. No "yes don't ask again" for destructive ops.

**Rule 5 — Network operations are not free.** Cloud GPU costs money.
Container pulls take time. Don't do speculative downloads or installs.
If it's not in the current story's DoD, don't fetch it.

**Rule 6 — The runbook is mandatory.** Every solved problem, every
working command, every gotcha gets appended to OPERATOR_RUNBOOK.md
**immediately**, in the same session it was discovered. If it's not
in the runbook, it didn't happen.

**Rule 7 — Phase boundaries are hard.** When the current phase ends,
stop. Do NOT start the next phase until architect review approves the
gate. Even if you can see "obviously the next thing to do," don't.

**Rule 8 — Report cleanly at story end.** Every completed story ends
with a summary block:
- What was done
- What files were created or modified
- Any commands worth remembering
- Any warnings, deferred items, or surprises
- A one-line status: "Story X.Y done — moving to X.Z" or "Stuck on X.Y — see [reason]"

---

## 4. Standing rules for the owner

**Rule 1 — One story at a time.** Don't paste multi-story prompts.
Don't let Claude Code "just keep going" past a story boundary.

**Rule 2 — Read the summaries.** When Claude Code reports completion,
read the summary block. If something looks wrong (file you didn't
expect, command you don't recognize), pause and check with architect.

**Rule 3 — When in doubt, ask the architect.** It's free. Wrong
guesses on Day 14 are expensive.

**Rule 4 — Daily check-in.** End-of-day, paste the day's progress
summary to architect: which stories closed, which are open, anything
flagged. Architect responds within ~24 hours.

**Rule 5 — Sundays are off.** No coding, no Claude Code, no rabbit
holes. The architect will not respond to story-execution work on
Sundays. Use Sundays for rest, separate work, or strategic thinking
(reading the charter, reviewing decisions).

**Rule 6 — Phase gate is a hard stop.** Don't start the next phase
without architect-approved gate review. Drift past a gate is the
single most expensive mistake possible.

---

## 5. Standing rules for the architect

These are commitments the architect makes to the owner, written down
so they're checkable.

- Respond to daily check-ins within 24 hours on working days.
- Never silently revise a charter decision; revisions are explicit and logged.
- Push back on scope creep, even when the owner proposes it.
- Surface concerns early, even uncomfortable ones (timeline slipping, technical risk, sustainability).
- Do not produce artifacts the owner didn't ask for. Ask before creating.
- When a Claude Code session shows drift, halt the session before recommending next steps.

---

## 6. The session-prep prompt

At the start of every Claude Code session, the owner pastes a "session
prep" prompt that establishes context. The template:

```
PROJECT: refinery-twin (NVIDIA Omniverse + Isaac Sim)
PHASE: <current phase>
STORY: <current story id and title>

CONTEXT YOU MUST READ FIRST:
1. CLAUDE_CODE_AGREEMENT.md — standing rules
2. PROJECT_CHARTER.md §1, §3, §4, §5 — scope and principles
3. BACKLOG_PHASE_<N>.md — story-level detail

WORKING DIRECTORY: <full path>
ENVIRONMENT: <local Mac venv | cloud Lambda instance via SSH | etc.>

TODAY'S WORK: <one or two sentences describing the slice>

CONSTRAINTS SPECIFIC TO TODAY:
- <anything the architect wants emphasized>

STOP CONDITIONS:
- <when to halt, beyond the standing rules>
```

The owner fills in the brackets. The architect provides this prompt
when handing off a story.

---

## 7. The session-close prompt

At the end of every Claude Code session, before the owner closes it,
Claude Code produces a session-close summary:

```
SESSION CLOSE SUMMARY

Phase: <current>
Story: <current>
Status: <DONE | IN_PROGRESS | BLOCKED>

Files modified:
- <list>

Files created:
- <list>

Commands worth saving (added to OPERATOR_RUNBOOK):
- <list>

Cloud cost incurred this session: <hours × rate, if applicable>

Open questions for architect:
- <list>

Next story: <id and title, per backlog>
```

The owner pastes this summary to the architect as the daily check-in.

---

## 8. Decision log

Every binding decision made during the project gets logged in
PROJECT_CHARTER.md §11. Format:

```
| Date | Decision | Rationale |
```

This log is append-only. Old decisions are never silently revised. If
a previous decision needs to change, that's a new decision row that
references the old one.

---

## 9. Anti-patterns to watch for

These are the failure modes that have eaten projects like this in the
past. Watch for them in yourself and call them out.

**"Just one more thing."** You finish a story and feel momentum, so
you start the next. Don't. Hard stops are protective.

**"It's almost working, let me push through."** Three failed attempts
mean stop, not "try harder." The error is information; collect it,
think about it.

**"This is a small refactor."** No refactors during a phase, period.
Refactors go in their own phase, with their own DoD, after architect
review.

**"I'll document it later."** Never. Document now, while the context
is fresh. "Later" arrives at the worst possible time.

**"The architect doesn't need to know this."** They probably do. Err
on the side of over-reporting at first; the architect will tell you
what's noise.

**"I'll just skip this validation step."** Validation steps are the
project's immune system. Skipping them means failures land at the
worst possible moment — usually right before the demo.

**Sleep deprivation.** Tired you makes worse decisions and writes
worse code than rested you. The Sundays-off rule is not optional.

---

## 10. Amendments

This document may be amended. Amendments are explicit, dated, and
appended to a "Changes" section below. The architect proposes;
the owner approves.

### Changes

(none yet)

---

**Working agreement end.**
