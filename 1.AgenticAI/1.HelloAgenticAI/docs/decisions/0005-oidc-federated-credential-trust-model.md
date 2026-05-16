# 0005 — OIDC federated-credential trust model for CI

## Status

Accepted, 2026-05-16.

## Context

Phase 5 wires GitHub Actions to Azure (Phase 5c evals, 5d Launch/Teardown). CI must authenticate to Azure. `CLAUDE.md` ("GitHub Actions with OIDC federated credentials for CI/CD"; conventions: "No keys or secrets in code anywhere") and `PROJECT_PLAN.md` Phase 5 ("OIDC federated credentials configured (zero secrets in GitHub)") mandate OIDC — no stored service-principal secret.

A complete manual runbook already existed (`docs/setup-oidc.md`, pre-Phase-5) but used a **subscription-scoped** `Contributor` + `User Access Administrator` grant and three federated-credential subjects including a repo-wide `pull_request` subject. Phase 5b's goal is narrower: *establish the trust and prove it works*, before any CI does real work. That makes the over-broad posture both unnecessary now and a standing risk. This ADR records the trust-model decision; `docs/setup-oidc.md` is the runbook that implements it.

The federated-credential **subject** is the security boundary: anything that can produce a GitHub OIDC token whose `sub` matches a configured credential can obtain an Azure token as the service principal. Subject scoping and role scoping are the two independent levers.

## Options considered

**Subject scoping:**

1. Stored SP client secret in GitHub Secrets — rejected: secret sprawl, rotation burden, exfiltration risk; violates the no-secrets mandate.
2. OIDC, repo-wide subject (`repo:ORG/REPO:*`) or `:pull_request` — too broad: any workflow, including one introduced by a pull request, can mint a token.
3. OIDC, branch-scoped (`repo:ORG/REPO:ref:refs/heads/main`) — better, but a token mints automatically on every push to `main`; no pre-mint human gate.
4. OIDC, **GitHub-Environment-scoped** (`repo:ORG/REPO:environment:oidc-verify`) — tightest: a GitHub Environment can carry a *required-reviewer* rule, so no token is issued until a human approves the run; environments also isolate 5c/5d surfaces from each other.

**Role scoping (orthogonal):**

A. Subscription-scoped `Contributor` + `User Access Administrator` (original runbook) — rejected for 5b: maximal blast radius for a step that creates nothing.
B. `Reader` on one resource group — rejected for 5b: adds no verification value (role binding was proven across Phases 1–4 via the managed identity) while still widening blast radius.
C. **Zero roles in 5b**; RG-scoped `Contributor` + `User Access Administrator` on `rg-helloagenticai-dev` deferred to 5c — chosen.

## Decision

Use **option 4 + option C**.

- One federated credential, subject `repo:sowthri-industrial-ai/AISolutionPortfolio:environment:oidc-verify`, issuer `https://token.actions.githubusercontent.com`, audience `api://AzureADTokenExchange`, on app registration `github-helloagenticai-oidc`.
- **Phase 5b grants zero Azure RBAC roles.** `az account show` succeeds with any valid AAD token irrespective of role assignment, so it proves the entire federated-trust chain (GitHub JWT issuance → subject match → AAD token exchange → `azure/login`) without granting the SP any ability to read or change resources. Confirming role binding again would duplicate what Phases 1–4 already demonstrated and would only enlarge blast radius.
- **Privilege is deferred to Phase 5c**, granted then under explicit approval, **scoped to `rg-helloagenticai-dev` (resource group), not the subscription**. `User Access Administrator` is required there only because `infra/main.bicep` creates role assignments for the runtime managed identity; RG scope confines that authority to one resource group.
- Additional federated credentials for 5c/5d (e.g. `environment:evals`, `environment:portfolio-demo`) are environment-scoped too — never repo-wide or `pull_request`.

GitHub gets three **non-secret variables** (`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`), never secrets.

## Consequences

Positive:

- No secret exists anywhere — nothing to rotate, expire, or exfiltrate.
- Required-reviewer on the `oidc-verify` environment puts a human gate before any token mint.
- 5b blast radius is effectively nil: a worst-case mis-scoped subject yields a token that can do nothing beyond `az account show`.
- **GitHub Actions are SHA-pinned, not tag-pinned:** 5b's verify workflow is the seed for 5c/5d's privileged deploy pipeline (RG-scoped Contributor + User Access Administrator), so the immutable-pin posture is established before privilege is attached — a mutable tag would otherwise be a supply-chain entry point into the tenant once those roles exist.
- **Rollback is one command:** `az ad app delete --id $APP_ID` removes the app registration, its service principal, all federated credentials, and all role assignments held by that SP. No resource-group data is touched; no secret needs revoking because none exists. Removing a single trust path instead is `az ad app federated-credential delete`.

Negative (and mitigations):

- A mis-typed `subject` fails silently — auth just doesn't work at run time, with no creation-time error. *Mitigation:* the runbook echoes the exact subject for eyeball review before creation; the Phase 5b `workflow_dispatch` run is the validation gate (the ADR-0003 "a later layer catches it" discipline applied to identity config).
- Splitting trust (5b) from privilege (5c) is two approval rounds instead of one. *Mitigation:* deliberate — it keeps each grant minimal and explicitly reviewed, consistent with CLAUDE.md workflow rule 4.
- Per-environment federated credentials mean more credentials to manage as 5c/5d land. *Mitigation:* one `az ad app delete` still revokes the entire app and all of them.

## Scope

Applies to HelloAgenticAI CI authentication (Phase 5b onward) in repo `sowthri-industrial-ai/AISolutionPortfolio`, subscription `d599c6a3-6859-4aae-8c0e-63674a3b0704`, tenant `a5798993-43f3-452a-9e32-5893aff20a36`. Identity, federated-credential, and role-assignment operations are executed by Sowthri only; Claude Code proposes the exact commands and never runs them (CLAUDE.md workflow rule 4). Vertical projects (RefineryDigitalTwin, etc.) re-evaluate per project — they get their own app registration and RG-scoped grants; they do not share this SP.

## References

- `docs/setup-oidc.md` — the runbook implementing this decision
- `docs/decisions/TODO-phase-5-data-plane-rbac.md` — declarative data-plane RBAC for the OIDC SP (`oidcServicePrincipalId`), Phase 5c
- `docs/decisions/0003-azd-up-preflight-risks.md` — the "validate before you create / a later gate catches it" discipline applied here to the subject string
- `CLAUDE.md` — workflow rule 4 (approval gates), no-secrets convention
- `PROJECT_PLAN.md` Phase 5 — OIDC + CI/CD deliverables
- https://docs.github.com/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-azure
