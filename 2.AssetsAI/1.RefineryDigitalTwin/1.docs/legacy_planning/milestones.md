# Backlog — Milestones

> Four milestones, each with a single demonstrable outcome. Skip none. Re-plan only if a milestone slips by more than 50%.

---

## M1 — "Skeleton walks"

**Outcome:** Repo is alive. Simulator emits structured tick logs. Ontology service serves entities. CI is green.

**Stories included (15):**
- All E1 (S01–S08)
- E2: S01–S05
- E3: S01

**Demo:** Run `make setup && make test && make run-simulator` on a fresh laptop. See the simulator log with named equipment ticking; query ontology service for `H-101`; CI badge is green.

**Exit criteria:**
- `make status` shows green
- All E1 + E2 stories ticked
- Architect signs off in `docs/backlog/sign-offs.md`

**Estimated time:** 3–5 evenings + 1 weekend day

**Risks:**
- Bicep / Terraform setup takes longer than expected → defer Fabric provisioning to M2 if needed
- Equipment class modelling debates → architect calls it; don't litigate in PR

---

## M2 — "Data flows"

**Outcome:** A tag value changes in the simulator and appears in Eventhouse within 3 seconds, end-to-end.

**Stories included (24):**
- E2: S06
- E3: S02–S05, S07–S08 (steady-state + 2 scenarios)
- E4: all (S01–S07)
- E5: all (S01–S09)

**Demo:** Run the dev stack. Trigger `feed quality change` scenario from a CLI. Watch tags shift in OPC-UA browser. Watch new rows in TimescaleDB and (if Fabric is up) Eventhouse. Show end-to-end latency under 3 seconds in the smoke test.

**Exit criteria:**
- E5-S06 (smoke test) green in CI
- Bridge + simulator survive 24h soak test
- ADR-0006 validation criteria met

**Estimated time:** 1 week of evenings + 1 weekend

**Risks:**
- DWSIM integration drag (mitigated: thermo fallback)
- Fabric trial sign-up slow → use ADX cluster fallback per ADR-0001

---

## M3 — "Twin breathes"

**Outcome:** Platform services run; two agents answer real questions over real twin state.

**Stories included (22):**
- E3: S06, S09–S11 (rest of scenarios)
- E6: all (S01–S12)
- E7: S01–S09

**Demo:** Trigger pump failure scenario. Anomaly service surfaces alert. Ask Reliability agent: "Should I be worried about P-100?" — agent calls `get_asset_state`, `query_historian`, `predict_failure`; produces grounded answer with explicit tool trace.

**Exit criteria:**
- All four anomaly models produce expected detections in their scenarios
- Reliability + Operations agents pass demo questions
- E6-S12 (platform integration test) green
- MCP tool audit log review by architect

**Estimated time:** 1.5 weeks of evenings + 2 weekends

**Risks:**
- Anomaly model false-positive rates too high → tune thresholds before release
- MCP tool latency too high → cache aggressively; profile early

---

## M4 — "Demo-ready"

**Outcome:** Interview-ready. Dashboard polished. Six scenarios runnable. README + demo script complete. All four agents working.

**Stories included (11):**
- E7: S10 (energy + safety agents)
- E8: all (S01–S09)

**Demo:** The actual interview demo. 10-minute walkthrough:
1. Open dashboard. Show map of CDU. Live values updating.
2. Trigger heater fouling. Watch progression on chart.
3. Reliability agent: "What's happening to H-101?" → grounded answer.
4. Trigger feed change. Switch to Power BI: yield shifts.
5. Energy agent: "What's the cost of staying on heavy crude this week?"
6. Show MCP tool trace. Show OneLake transcript.
7. Open ADRs; walk one (ADR-0001 or ADR-0004).

**Exit criteria:**
- Demo runs end-to-end in under 10 minutes
- All six scenarios visibly produce expected outcomes
- Power BI embed renders
- README quickstart works on a clean machine in < 30 minutes
- Public repo published; private notes (interview prep, etc.) in separate repo

**Estimated time:** 1 week of evenings + 1 weekend (mostly polish)

**Risks:**
- Polish creep → strict scope; "later" is the right answer for non-essentials
- Power BI Embedded licensing → fall back to Apache Superset (ADR-0007 trigger)

---

## Cross-milestone gates (architect responsibility)

Between every milestone:

1. **Backlog cleanup.** Move done items, re-estimate the next batch, document any new ADRs.
2. **NFR check.** Run latency, ingest, query benchmarks. Compare to `docs/04-non-functional-requirements.md`.
3. **Security review.** Verify ADR-0005 controls remain in place; CI segregation check passes.
4. **Documentation sweep.** Every doc current. Cross-references work. ADRs reflect any decisions made during the milestone.
5. **Decision capture.** Anything decided informally during the milestone gets an ADR or a note.

Sign-off recorded in `docs/backlog/sign-offs.md` with date and one-line summary.

---

## Definition of Done (project)

The project is done when:

- All M4 exit criteria met
- README walks a stranger from `git clone` to working demo without help
- ADRs explain every non-obvious choice
- Architecture doc still matches the code
- Demo script tested twice with stopwatch
- CV references RefineryTwin as a public, demonstrable industrial AI portfolio piece (github.com/sowthri-industrial-ai/RefineryTwin)

That last one is the actual goal.
