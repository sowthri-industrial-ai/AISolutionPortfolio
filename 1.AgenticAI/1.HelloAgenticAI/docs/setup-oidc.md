# OIDC federated credentials: GitHub Actions → Azure (manual setup runbook)

GitHub Actions authenticates to Azure using **OIDC federated credentials** — a workflow run requests a short-lived JWT from GitHub's OIDC identity provider, Entra exchanges it for an Azure AAD token. **No service-principal secret is ever stored anywhere.**

> **This document is for Sowthri to run manually.** Claude Code proposes these commands but does **not** execute identity / tenant / RBAC operations (app registration, service principal, federated credentials, role assignments) — see CLAUDE.md workflow rule 4 and ADR-0005. The decision *record* is `docs/decisions/0005-oidc-federated-credential-trust-model.md`; this file is the *runbook*.

## Trust model

```
GitHub Actions run  (workflow_dispatch, environment: oidc-verify)
   │  GitHub OIDC IdP issues a short-lived JWT
   │  sub = repo:sowthri-industrial-ai/AISolutionPortfolio:environment:oidc-verify
   ▼
Entra app registration "github-helloagenticai-oidc"  (appId → GitHub var AZURE_CLIENT_ID)
   │  federated credential matches (issuer + subject + audience) — NO secret exchanged
   ▼
Service principal (the app's SP)  →  Azure AAD access token
   ▼
Azure  (Phase 5b: zero roles — token proves trust via `az account show`)
```

**Subject is scoped to a GitHub Environment, not a branch or the whole repo.** An Environment can carry a *required-reviewer* protection rule, so the OIDC token cannot be minted until a human approves the run. This is strictly tighter than `ref:refs/heads/main` (auto-mints on every push to main) or a repo-wide subject (any workflow, including one added by a PR, can mint). Rationale in ADR-0005.

## Prerequisites

- **Owner** or **Application Administrator** on the Entra tenant `a5798993-43f3-452a-9e32-5893aff20a36`
- For Phase 5c only: **Owner** or **User Access Administrator** on subscription `d599c6a3-6859-4aae-8c0e-63674a3b0704`
- Repository `sowthri-industrial-ai/AISolutionPortfolio`; `gh` CLI logged in (`repo` scope)
- `az` CLI logged in to the right subscription (`az account show`)

---

## Phase 5b — minimal trust (run this now)

Establishes the OIDC trust and proves it works. **Zero Azure role assignments** — see "Why no roles in 5b" below.

### 1. Entra app registration

```bash
APP_ID=$(az ad app create \
    --display-name "github-helloagenticai-oidc" \
    --query appId -o tsv)
echo "APP_ID=$APP_ID"
```

### 2. Service principal for the app

```bash
SP_OBJECT_ID=$(az ad sp create --id "$APP_ID" --query id -o tsv)
echo "SP_OBJECT_ID=$SP_OBJECT_ID"   # not needed in 5b; recorded for the 5c RBAC step
```

### 3. One federated credential — environment-scoped

Eyeball the `subject` string before running — a typo fails silently at workflow run time, not here.

```bash
az ad app federated-credential create \
    --id "$APP_ID" \
    --parameters '{
        "name": "github-env-oidc-verify",
        "issuer": "https://token.actions.githubusercontent.com",
        "subject": "repo:sowthri-industrial-ai/AISolutionPortfolio:environment:oidc-verify",
        "audiences": ["api://AzureADTokenExchange"]
    }'
```

### 4. GitHub repo variables — NOT secrets

OIDC stores no secret; only non-sensitive IDs are needed. Set as **Variables** (Settings → Secrets and variables → Actions → *Variables* tab), or:

```bash
REPO=sowthri-industrial-ai/AISolutionPortfolio
gh variable set AZURE_CLIENT_ID       --body "$APP_ID"                                  --repo "$REPO"
gh variable set AZURE_TENANT_ID       --body "a5798993-43f3-452a-9e32-5893aff20a36"     --repo "$REPO"
gh variable set AZURE_SUBSCRIPTION_ID --body "d599c6a3-6859-4aae-8c0e-63674a3b0704"     --repo "$REPO"
```

### 5. No role assignments

Phase 5b grants the SP **no Azure RBAC roles**. `az account show` succeeds with any valid AAD token regardless of role, so it fully proves the federated-trust chain (GitHub JWT → subject match → AAD token) without widening blast radius. Role binding was already proven across Phases 1–4 via the managed identity. Privilege is deferred to Phase 5c (below). See ADR-0005 "Why zero roles in 5b".

### 6. GitHub environment + verify

Create the environment the subject is scoped to (UI → Settings → Environments → New environment → `oidc-verify`), or:

```bash
gh api --method PUT \
  repos/sowthri-industrial-ai/AISolutionPortfolio/environments/oidc-verify
```

**Recommended:** add yourself as a *required reviewer* on the `oidc-verify` environment — the OIDC token then cannot be minted until you approve the run.

Then run `.github/workflows/oidc-verify.yml` via `workflow_dispatch`. Success = the `azure/login@v2` step passes and `az account show` prints subscription `d599c6a3-…` inside the runner, with no stored secret.

---

## Phase 5c+ — deferred privilege (DO NOT run until Phase 5c, separately approved)

When CI must actually *do* things (run `azd up`, evals against live Azure), add — **per explicit Sowthri approval at 5c, not now**:

- Additional environment-scoped federated credentials, one per workflow surface (e.g. `environment:evals`, `environment:portfolio-demo`) — never a repo-wide or `pull_request` subject.
- RBAC, **scoped to the resource group, not the subscription**:

```bash
SUB=d599c6a3-6859-4aae-8c0e-63674a3b0704
RG=rg-helloagenticai-dev
az role assignment create --assignee-object-id "$SP_OBJECT_ID" --assignee-principal-type ServicePrincipal \
    --role "Contributor"                  --scope "/subscriptions/$SUB/resourceGroups/$RG"
az role assignment create --assignee-object-id "$SP_OBJECT_ID" --assignee-principal-type ServicePrincipal \
    --role "User Access Administrator"    --scope "/subscriptions/$SUB/resourceGroups/$RG"
```

`User Access Administrator` is required because `infra/main.bicep` creates role assignments for the runtime managed identity. **This is the explicit downgrade from the original subscription-wide grant** (ADR-0005): RG scope contains blast radius to `rg-helloagenticai-dev`. If `azd up` needs to *create* the RG, pre-create it (`az group create -n rg-helloagenticai-dev -l swedencentral`) so the RG-scoped assignment can exist first. The declarative data-plane grants for this SP are tracked in `docs/decisions/TODO-phase-5-data-plane-rbac.md` (`oidcServicePrincipalId` param).

---

## Teardown — one command revokes everything

```bash
az ad app delete --id "$APP_ID"
# removes the app registration + its SP + ALL federated credentials + ALL role
# assignments held by that SP. No secret exists, so nothing to rotate or leak.
```

GitHub variables are non-secret; leave them or `gh variable delete`. The `oidc-verify` environment can be deleted in the UI or `gh api --method DELETE repos/.../environments/oidc-verify`.

## References

- `docs/decisions/0005-oidc-federated-credential-trust-model.md` — the decision record this runbook implements
- `docs/decisions/TODO-phase-5-data-plane-rbac.md` — declarative data-plane RBAC (the 5c `oidcServicePrincipalId` work)
- `PROJECT_PLAN.md` Phase 5 — OIDC + CI/CD scope
- https://learn.microsoft.com/azure/developer/github/connect-from-azure-openid-connect
- https://docs.github.com/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-azure
