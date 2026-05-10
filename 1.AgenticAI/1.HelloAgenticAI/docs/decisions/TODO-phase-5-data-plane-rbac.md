# TODO (Phase 5) — declarative data-plane RBAC for dev principal + OIDC SP

**Status:** deferred to Phase 5. Tracked here so it doesn't get lost.

**Why this doc exists:** Phase 1 Bicep grants every data-plane role to the runtime user-assigned managed identity (correct for the deployed Container App). Local development uses a different principal (the developer's `az login` user) and CI will use a different principal (the OIDC service principal). Both currently need their grants applied **manually via `az` after every `azd up` / re-applied after every `azd down --purge`** — see CLAUDE.md "First-time / post-teardown developer setup" and ADR-0003 risk #7 for the runbook.

Phase 5's Bicep refactor makes this declarative and persistent.

## Scope

Add **two optional parameters** to `infra/main.bicep` (and propagate to the relevant per-service modules) so `azd up` can grant the analogous roles to a developer principal and to the CI OIDC service principal at provision time:

```bicep
@description('Object id of the developer principal that should receive data-plane roles for local integration testing. Empty = no dev grants.')
param developerPrincipalId string = ''

@description('Object id of the GitHub Actions OIDC service principal that should receive data-plane roles for CI. Empty = no CI grants.')
param oidcServicePrincipalId string = ''
```

Each per-service module conditionally creates the analogous role assignment when the param is non-empty. The runtime MI grants stay exactly as they are today.

## Per-service grant matrix

The Phase 5 refactor must mirror this set:

| Service | Bicep module | Role | Already granted to MI in Phase 1 | Add for dev principal | Add for OIDC SP |
|---|---|---|:---:|:---:|:---:|
| Cosmos DB | `infra/modules/cosmos.bicep` | `Cosmos DB Built-in Data Contributor` (`00000000-0000-0000-0000-000000000002`) | yes | yes | yes (for evals workflow) |
| Azure OpenAI | `infra/modules/openai.bicep` | `Cognitive Services OpenAI User` (`5e0bd9bd-7b93-4f28-af87-19fc36ad61bd`) | yes | yes | yes (for evals workflow) |
| Content Safety | `infra/modules/contentsafety.bicep` | `Cognitive Services User` (`a97b65f3-24c7-4388-baec-2e87135dc908`) | yes | yes | yes (Phase 4 wires it live) |
| Storage | `infra/modules/storage.bicep` | `Storage Blob Data Contributor` (`ba92f5b4-2d11-453d-a403-e96b0029c9fe`) | yes | yes | yes (eval artefacts) |
| Key Vault | `infra/modules/keyvault.bicep` | `Key Vault Secrets User` (`4633458b-17de-408a-b874-0445c86b69e6`) | yes | yes | yes (Langfuse keys, Phase 4) |
| ACR | `infra/modules/registry.bicep` | `AcrPull` (`7f951dda-4ed3-4680-a7ca-43fe172d538d`) | yes | no (not needed locally) | no |

Cosmos uses its own RBAC system (`Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments`); the others use standard Azure RBAC (`Microsoft.Authorization/roleAssignments`).

## Bicep sketch (per non-Cosmos module)

```bicep
@description('Optional: developer principal id to grant the same data-plane role assigned to the MI.')
param developerPrincipalId string = ''

@description('Optional: GitHub Actions OIDC SP object id to grant the same data-plane role assigned to the MI.')
param oidcServicePrincipalId string = ''

// existing MI role assignment unchanged …

resource devRoleAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(developerPrincipalId)) {
  scope: <resource>
  name: guid(<resource>.id, developerPrincipalId, <roleId>)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', <roleId>)
    principalId: developerPrincipalId
    principalType: 'User'
  }
}

resource oidcRoleAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(oidcServicePrincipalId)) {
  scope: <resource>
  name: guid(<resource>.id, oidcServicePrincipalId, <roleId>)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', <roleId>)
    principalId: oidcServicePrincipalId
    principalType: 'ServicePrincipal'
  }
}
```

Cosmos needs the analogous `Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments` form.

## Parameters wiring

`infra/main.parameters.json` reads from azd env vars:

```json
"developerPrincipalId": { "value": "${AZURE_DEV_PRINCIPAL_ID=}" },
"oidcServicePrincipalId": { "value": "${AZURE_OIDC_SP_OBJECT_ID=}" }
```

The `=` after the env name lets azd default to empty when not set, so production deploys with neither variable set are unaffected.

For dev, either:

- `azd env set AZURE_DEV_PRINCIPAL_ID $(az ad signed-in-user show --query id -o tsv)`
- Or detect at provision via an `azd hooks` preprovision step

For Phase 5 CI, the `deploy.yml` workflow sets `AZURE_OIDC_SP_OBJECT_ID` to the SP's object id (also discoverable via `az ad sp show --id $AZURE_CLIENT_ID --query id`).

## Verification checklist

When the refactor lands, all of these must pass cleanly:

- [ ] Fresh `azd up` (no env vars set): runtime MI has all 6 grants; dev/OIDC have none. (Production parity.)
- [ ] `azd env set AZURE_DEV_PRINCIPAL_ID <objid> && azd up`: dev principal also has all 5 dev-applicable grants.
- [ ] `azd env set AZURE_OIDC_SP_OBJECT_ID <objid> && azd up`: OIDC SP has all 5 CI-applicable grants.
- [ ] All grants survive `azd down --purge && azd up` with the env vars persistent.
- [ ] AOAI propagation note (ADR-0003 risk #7) still applies — even with declarative grants, integration tests immediately after `azd up` may need a wait-and-retry for AOAI / Content Safety.
- [ ] CLAUDE.md "First-time / post-teardown developer setup" gets simplified to one line: `azd env set AZURE_DEV_PRINCIPAL_ID $(az ad signed-in-user show --query id -o tsv)` then `azd up`. The 5 manual `az` commands disappear.

## Risk

ADR-0003 risk #7 (DefaultAzureCredential local-dev vs MI). The refactor closes that risk; mark risk #7 as "resolved by Phase 5 Bicep refactor" in the ADR when this lands.

## Cross-link

- `CLAUDE.md` §"First-time / post-teardown developer setup" — the manual runbook this replaces
- `docs/decisions/0003-azd-up-preflight-risks.md` §risk #7 — the failure mode this fixes
- `PROJECT_PLAN.md` Phase 5 — where this work belongs (alongside `deploy.yml` workflow + OIDC setup)
