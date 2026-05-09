# OIDC federated credentials: GitHub Actions → Azure (manual setup)

GitHub Actions deploys this project's infrastructure via `azd up` / `azd down`. To avoid storing Azure service-principal secrets in GitHub, we use **OIDC federated credentials** — workflows authenticate to Azure using a short-lived token issued by GitHub's OIDC identity provider, exchanged for an Azure AAD token at the federated app registration.

This document is for **Sowthri to run manually** (one-time setup) before Phase 5 wires CI/CD. Claude Code does not have (and should not have) the permissions to do this on its own.

## Prerequisites

- **Owner** or **Application Administrator** on the target Entra tenant
- **Owner** or **User Access Administrator** on the target Azure subscription
- Repository: `sowthri-industrial-ai/AISolutionPortfolio`
- `gh` CLI logged in (or web-browser access to GitHub repo settings)
- `az` CLI logged in to the right subscription (`az account show`)

## Steps

### 1. Create an Entra app registration for GitHub Actions

```bash
APP_ID=$(az ad app create \
    --display-name "github-helloagenticai-oidc" \
    --query appId -o tsv)
echo "APP_ID=$APP_ID"
```

### 2. Create the service principal for the app

```bash
SP_OBJECT_ID=$(az ad sp create --id "$APP_ID" --query id -o tsv)
echo "SP_OBJECT_ID=$SP_OBJECT_ID"
```

### 3. Grant the SP roles on the subscription

`Contributor` lets the SP create most resources; `User Access Administrator` is needed because `infra/main.bicep` creates role assignments (granting the runtime managed identity access to AOAI / Cosmos / Key Vault / etc.).

For a stricter posture, scope these to the resource group `rg-helloagenticai-dev` after the first `azd up` has created it.

```bash
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

az role assignment create \
    --assignee-object-id "$SP_OBJECT_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Contributor" \
    --scope "/subscriptions/$SUBSCRIPTION_ID"

az role assignment create \
    --assignee-object-id "$SP_OBJECT_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "User Access Administrator" \
    --scope "/subscriptions/$SUBSCRIPTION_ID"
```

### 4. Create federated credentials (one per trust scope)

For pushes to `main`:

```bash
az ad app federated-credential create \
    --id "$APP_ID" \
    --parameters '{
        "name": "github-main",
        "issuer": "https://token.actions.githubusercontent.com",
        "subject": "repo:sowthri-industrial-ai/AISolutionPortfolio:ref:refs/heads/main",
        "audiences": ["api://AzureADTokenExchange"]
    }'
```

For pull requests (so the `evals.yml` workflow can authenticate when triggered by a PR):

```bash
az ad app federated-credential create \
    --id "$APP_ID" \
    --parameters '{
        "name": "github-pr",
        "issuer": "https://token.actions.githubusercontent.com",
        "subject": "repo:sowthri-industrial-ai/AISolutionPortfolio:pull_request",
        "audiences": ["api://AzureADTokenExchange"]
    }'
```

For the `portfolio-demo` GitHub environment (used by `workflow_dispatch` from the portfolio site Launch button — Phase 5):

```bash
az ad app federated-credential create \
    --id "$APP_ID" \
    --parameters '{
        "name": "github-environment-portfolio-demo",
        "issuer": "https://token.actions.githubusercontent.com",
        "subject": "repo:sowthri-industrial-ai/AISolutionPortfolio:environment:portfolio-demo",
        "audiences": ["api://AzureADTokenExchange"]
    }'
```

### 5. Set GitHub repo variables (NOT secrets)

OIDC means no secret is stored — only the IDs are needed.

```bash
TENANT_ID=$(az account show --query tenantId -o tsv)
REPO=sowthri-industrial-ai/AISolutionPortfolio

gh variable set AZURE_CLIENT_ID --body "$APP_ID" --repo "$REPO"
gh variable set AZURE_TENANT_ID --body "$TENANT_ID" --repo "$REPO"
gh variable set AZURE_SUBSCRIPTION_ID --body "$SUBSCRIPTION_ID" --repo "$REPO"
```

### 6. Verify

`.github/workflows/deploy.yml` (created in Phase 5) will use the `azure/login` action with these values:

```yaml
permissions:
  id-token: write   # required for OIDC
  contents: read

steps:
  - uses: azure/login@v2
    with:
      client-id: ${{ vars.AZURE_CLIENT_ID }}
      tenant-id: ${{ vars.AZURE_TENANT_ID }}
      subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}
```

Run the workflow once via `workflow_dispatch` — if `az account show` succeeds inside the workflow, OIDC is working.

## Tearing it down

When the project is no longer needed:

```bash
az ad app delete --id "$APP_ID"
# deletes both the app registration and the SP, removes all federated creds
```

GitHub repo variables can be left in place (they are not secrets) or deleted via `gh variable delete`.

## Why two role assignments?

- **Contributor:** create / update / delete the resources in `infra/`
- **User Access Administrator:** assign the runtime managed identity's data-plane roles (Key Vault Secrets User, Cosmos DB Built-in Data Contributor, AcrPull, etc.) inside `infra/modules/*.bicep`. Without this, `azd up` fails midway with `AuthorizationFailed` on the role assignment resources.

If your security policy disallows User Access Administrator at subscription scope, scope it to `rg-helloagenticai-dev` after the first `azd up` (manual workaround: pre-create the RG, scope the role there, then `azd up`).

## References

- https://learn.microsoft.com/azure/developer/github/connect-from-azure-openid-connect
- https://docs.github.com/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-azure
