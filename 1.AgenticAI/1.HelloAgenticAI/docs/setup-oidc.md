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

## Phase 5c — eval data-plane grant (AUTHORIZED 2026-05-19)

Per ADR-0006, Phase 5c grants the SP **only the 5 RG-scoped data-plane roles** the eval workflow needs to run the real agent against live Azure — **NOT** `Contributor`/`UAA` (that is the deploy privilege, deferred — see next section). Staged per ADR-0003 risk #12: new credential + environment first, an inert trust-verify proves the new subject with zero privilege, **then** these roles, **then** the privileged `evals.yml`. Run only at the Phase 5c privilege-grant batch, command-by-command, output-verified each step.

New environment-scoped federated credential (subject scrutinized char-for-char before running):

```bash
az ad app federated-credential create \
    --id "$APP_ID" \
    --parameters '{
        "name": "github-env-evals",
        "issuer": "https://token.actions.githubusercontent.com",
        "subject": "repo:sowthri-industrial-ai/AISolutionPortfolio:environment:evals",
        "audiences": ["api://AzureADTokenExchange"]
    }'
```

The 5 data-plane roles (GUIDs in ADR-0006 / `TODO-phase-5-data-plane-rbac.md`), RG-scoped, assignee = the OIDC SP object id `4bc75532-91d1-4b68-8a60-019e6611bce0`:

```bash
SUB=d599c6a3-6859-4aae-8c0e-63674a3b0704
RG=rg-helloagenticai-dev
SP=4bc75532-91d1-4b68-8a60-019e6611bce0   # az ad sp show --id "$APP_ID" --query id -o tsv

# 4 standard-RBAC data-plane roles, RG-scoped:
for ROLE in \
  "Cognitive Services OpenAI User" \
  "Cognitive Services User" \
  "Storage Blob Data Contributor" \
  "Key Vault Secrets User" ; do
  az role assignment create --assignee-object-id "$SP" --assignee-principal-type ServicePrincipal \
      --role "$ROLE" --scope "/subscriptions/$SUB/resourceGroups/$RG"
done

# Cosmos uses its OWN RBAC system — DIFFERENT command, account-scoped:
COSMOS=$(az cosmosdb list -g "$RG" --query "[0].name" -o tsv)
az cosmosdb sql role assignment create \
    --account-name "$COSMOS" --resource-group "$RG" --scope "/" \
    --principal-id "$SP" \
    --role-definition-id "00000000-0000-0000-0000-000000000002"   # Cosmos DB Built-in Data Contributor
```

Propagation (ADR-0003 risk #7): Cosmos/Storage typically <2 min; AOAI/Content Safety 15–45 min. A first `evals.yml` 401/403 right after granting is propagation lag, **not** a trust failure — the inert trust-verify already proved the subject.

**Consumer (added Phase 5c Batch 5):** the workflow that exercises these grants is `.github/workflows/evals.yml`. It runs the 10 canonical `EvalCase`s in `demo_fruitmarket/eval/cases.json` against the real fruit-market agent on every pull request to `main`, posts the pass-rate result as a PR comment, and fails the PR if pass rate is below 90% (PROJECT_PLAN.md Phase 5 acceptance). The workflow's job is bound to the `evals` GitHub Environment so the required-reviewer gate fires per PR run.

**Endpoint repo Variables (NON-secret, one-time set):** `evals.yml` reads three resource endpoint URIs from GitHub repo Variables. The OIDC SP already has the 5 data-plane roles to invoke them (above); these variables just tell the runner *which* endpoints to dial. Extract them from `azd env get-values` and set via `gh` (or the UI):

```bash
REPO=sowthri-industrial-ai/AISolutionPortfolio
# Inspect the values first (from the project's azd env):
azd env get-values | grep -E '^(AZURE_OPENAI_ENDPOINT|AZURE_COSMOS_ENDPOINT|AZURE_CONTENT_SAFETY_ENDPOINT)='
# Then set them as repo Variables (NOT secrets — these are public URIs):
gh variable set AZURE_OPENAI_ENDPOINT         --body "<from azd>" --repo "$REPO"
gh variable set AZURE_COSMOS_ENDPOINT         --body "<from azd>" --repo "$REPO"
gh variable set AZURE_CONTENT_SAFETY_ENDPOINT --body "<from azd>" --repo "$REPO"
```

`AZURE_CONTENT_SAFETY_ENDPOINT` is optional functionally (the agent fails-open without it, per Phase 4); but the `guardrail-block-*` eval case requires Content Safety to be wired to pass — leaving it unset will fail that case (other 9 still run).

## Deploy privilege — Contributor + User Access Administrator (DEFERRED — NOT Phase 5c)

**DO NOT run these.** Per ADR-0006, `Contributor` + `User Access Administrator` is **deliberately deferred** — it is the deploy (`azd up`) privilege, has **no consumer** (no `deploy.yml` exists), and is the project's highest-blast-radius grant (UAA-on-RG = escalate to anything in `rg-helloagenticai-dev`; Contributor = create/modify/delete every resource in it). This deferral is a decision, not an oversight.

```bash
# DEFERRED — for the future deploy phase ONLY, never the eval credential:
SUB=d599c6a3-6859-4aae-8c0e-63674a3b0704
RG=rg-helloagenticai-dev
az role assignment create --assignee-object-id "$SP_OBJECT_ID" --assignee-principal-type ServicePrincipal \
    --role "Contributor"                  --scope "/subscriptions/$SUB/resourceGroups/$RG"
az role assignment create --assignee-object-id "$SP_OBJECT_ID" --assignee-principal-type ServicePrincipal \
    --role "User Access Administrator"    --scope "/subscriptions/$SUB/resourceGroups/$RG"
```

`User Access Administrator` is required because `infra/main.bicep` creates role assignments for the runtime managed identity (RG-scoped, the ADR-0005 downgrade from subscription-wide). **Condition to grant later:** a real `deploy.yml` exists and requires it — granted then in its own phase, own hard gate, own ADR, own environment-scoped credential (e.g. `environment:deploy`), never reusing the eval credential. The declarative data-plane grants are tracked in `docs/decisions/TODO-phase-5-data-plane-rbac.md` (`oidcServicePrincipalId` param).

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
