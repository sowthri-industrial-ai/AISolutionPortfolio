# 0003 — `azd up` preflight risks for HelloAgenticAI v1

## Status

Accepted, 2026-05-10.

## Context

Phase 1 provisions the full Azure stack via `azd up`. The first run will hit one or more of four failure modes if the host environment isn't prepared. We chose to capture these in a runbook (this ADR) rather than baking workarounds into the Bicep modules — defensive code in `infra/modules/*.bicep` would obscure the architectural intent that v1 is meant to demonstrate.

This ADR documents each risk, the symptom it produces, and the remediation, so the next person to run `azd up` cold can fix in 5 minutes instead of 30.

## Risks

### 1. Azure OpenAI quota in `swedencentral`

**Symptom:** `azd up` fails partway through with `InsufficientQuota` on one of the AOAI deployments. The error names the model and the requested capacity.

**Cause:** Default AOAI quota per region varies by subscription tenure and tier. `infra/main.parameters.json` requests:

| Deployment | SKU | Capacity (1K TPM) |
|---|---|---|
| `gpt-4o` (`2024-08-06`) | GlobalStandard | 10 |
| `gpt-4o-mini` (`2024-07-18`) | GlobalStandard | 30 |
| `text-embedding-3-large` (`v1`) | Standard | 30 |

**Preflight check (5 min, no Azure mutations):** Azure portal → Subscriptions → \[sub] → **Usage + quotas** → filter region "Sweden Central", filter provider "Cognitive Services" → confirm capacity headroom for each model. If any are zero or below the requested capacity, click **Request quota** — approval can take hours, so do this the night before if possible.

**Remediation if it fails mid-deploy:**

1. **Request quota** in Azure portal for the missing model — typical approval is minutes to a few hours.
2. **Or** lower the requested capacity in `infra/main.parameters.json` and re-run. Per memory rule (`feedback_no_silent_quota_downgrade.md`): **never silently downgrade — always re-confirm with Sowthri before reducing**.
3. **Or** switch region: pick one with known headroom (`eastus2`, `westus3`, `australiaeast` typically larger). Update `AZURE_LOCATION` in azd env (`azd env set AZURE_LOCATION <region>`) and re-run.

### 2. Subscription role

**Symptom:** `azd up` fails on a role-assignment resource with `AuthorizationFailed` (the message names `Microsoft.Authorization/roleAssignments/write`).

**Cause:** The Bicep modules create role assignments granting the runtime managed identity data-plane access (Key Vault Secrets User, Cosmos Data Contributor, AcrPull, etc.). This needs `User Access Administrator` (or `Owner`) at the assignment scope.

**Preflight check (verified 2026-05-10):** signed-in user (`sowthri.s@outlook.com`, object id `c70ea106-d4b5-4468-9fcd-eaab033a5878`) has **Owner** at subscription scope (`/subscriptions/d599c6a3-6859-4aae-8c0e-63674a3b0704`). Owner includes Contributor + User Access Administrator, so this risk is currently mitigated. **No action needed for the next run.**

**If a future runner sees `AuthorizationFailed`:**

```bash
az role assignment list \
  --assignee $(az ad signed-in-user show --query id -o tsv) \
  --scope /subscriptions/<sub-id> \
  --query "[].roleDefinitionName" -o tsv
```

If neither `Owner` nor both (`Contributor` + `User Access Administrator`) is present, ask the subscription owner. Alternatively, scope `User Access Administrator` to just `rg-helloagenticai-{env}` after pre-creating the RG (`az group create -n rg-helloagenticai-dev -l swedencentral`).

### 3. Resource-provider registrations

**Symptom:** A specific resource fails with `MissingSubscriptionRegistration` ("subscription is not registered for use of namespace 'Microsoft.X'"). Or the first-ever `azd up` is slow (extra 5–10 min) while azd auto-registers providers.

**Cause:** Each Azure resource type is under a "namespace" (`Microsoft.App`, `Microsoft.DocumentDB`, etc.) that the subscription must be registered for. azd registers them automatically on first use, but registration is asynchronous and can be slow.

**Providers used in v1:**

`Microsoft.App` · `Microsoft.OperationalInsights` · `Microsoft.Insights` · `Microsoft.DocumentDB` · `Microsoft.CognitiveServices` · `Microsoft.KeyVault` · `Microsoft.Storage` · `Microsoft.ContainerRegistry` · `Microsoft.ManagedIdentity` · `Microsoft.Authorization` · `Microsoft.Resources`

**Preflight check (1 min, read-only, optional):**

```bash
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.Insights \
          Microsoft.DocumentDB Microsoft.CognitiveServices Microsoft.KeyVault \
          Microsoft.Storage Microsoft.ContainerRegistry Microsoft.ManagedIdentity ; do
  printf "%-32s " "$ns"
  az provider show --namespace "$ns" --query registrationState -o tsv
done
```

Anything not `Registered` should be eagerly registered:

```bash
az provider register --namespace <namespace> --wait
```

**Remediation if it fails mid-deploy:** same `az provider register --namespace <namespace> --wait`, then `azd up` again. azd is idempotent — it picks up where it left off.

### 5. azd package failure before Bicep

**Symptom:** `azd up` exits non-zero at the package step, well before Bicep runs. The error names docker, a missing Dockerfile path, an inability to connect to the docker daemon, or an image build failure.

**Cause classes:**

(a) **Docker daemon not running** — error: `Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?`

(b) **`azure.yaml` `docker.path` / `docker.context` misconfigured** — buildkit reports `failed to read dockerfile`. Schema gotcha: `services.<svc>.docker.path` and `docker.context` are relative to `services.<svc>.project`, not relative to the YAML file's location.

**Impact:** **No Azure resources are provisioned** — Bicep is never invoked. There is nothing to clean up.

**Preflight check:**

```bash
docker info >/dev/null 2>&1 && echo "docker ok" || echo "DOCKER NOT RUNNING"

# Dry-run just the package phase (catches Dockerfile path errors without
# writing to ACR or provisioning anything).
cd infra && azd package --no-prompt
```

**Remediation:**

- (a) Start Docker Desktop (`open -a Docker` on macOS, then poll `docker info` for ~30 s).
- (b) Edit `azure.yaml`'s `services.<svc>.docker.path` to be relative to `project:` (commonly just `Dockerfile` if the Dockerfile lives at the project root).

### 6. Bicep validation / runtime failure during `azd provision`

**Symptom:** `azd up` runs through the package step, starts provision, deploys SOME resources, then exits non-zero with one or more of `ServiceModelDeprecating`, `RoleDefinitionDoesNotExist`, `NetworkAclsBypassNotSupported`, `InvalidTemplateDeployment`, etc.

**Cause classes seen in Phase 1:**

- **Model version deprecating / unavailable in region.** AOAI deployment specs a model version that has entered deprecating state or doesn't exist in the target region.
- **Wrong role-definition GUID.** Role assignment specs a role id that doesn't exist (typo, mis-remembered). The error displays the GUID without hyphens, e.g. `ba92f5b42d11450ca6a66f6c0c0e98a3`.
- **Unsupported property for resource Kind.** Certain `Microsoft.CognitiveServices/accounts` Kinds reject properties that work for OpenAI Kind — e.g. `networkAcls.bypass: AzureServices` is not supported on `ContentSafety`.

**Impact:** partial resource group. Most resources are up; the failing module(s) and any later modules in the dependency graph are missing. Bicep does NOT roll back.

**Preflight check — MANDATORY before any `azd up` per CLAUDE.md:**

```bash
cd infra && azd provision --preview
# or, equivalently:
az deployment sub validate \
    --location swedencentral \
    --template-file infra/main.bicep \
    --parameters infra/main.parameters.json
```

Either form runs Azure's full pre-provisioning validator and surfaces all three error classes above in ~30 s.

**Diagnosis after a mid-deploy failure:**

```bash
# Top-level deployment error
az deployment sub show -n dev-<timestamp> --query "properties.error" -o json

# Verify a role id you suspect is wrong (NEVER hand-type role GUIDs)
az role definition list --name "<role display name>" --query "[0].name" -o tsv

# List available model versions in your region
az cognitiveservices model list -l swedencentral \
    --query "[?model.name=='gpt-4o'].{version:model.version,deprecation:model.deprecation}"
```

**Remediation:** fix the offending Bicep. Re-run `azd up` — Bicep is idempotent, the existing resources are no-op'd and only the failing/missing modules deploy.

### 4. Container App initial-image port mismatch (expected, transient)

**Symptom:** In the 1–3 min window between `azd provision` finishing and `azd deploy` starting, the Container App's `latestRevision` shows "Activation failure" or failing health probes.

**Cause:** Bicep deploys the app with `mcr.microsoft.com/k8se/quickstart:latest` (which listens on port 80), but `targetPort` is 8000. The image and ingress disagree until `azd deploy` builds the local Dockerfile, pushes to ACR, and updates the revision to use the placeholder image (port 8000).

**Remediation:** **none — expected and self-resolves** within the same `azd up` invocation. After `azd deploy` completes (~3 min after `azd provision` finishes), the Container App revision rolls forward and `/health` returns 200.

**If `/health` is still failing > 5 min after `azd up` reports success**, the problem is the placeholder image, not the transient window. Diagnostic:

```bash
ENV_NAME=dev
APP=$(az containerapp list -g "rg-helloagenticai-${ENV_NAME}" --query "[0].name" -o tsv)
az containerapp logs show -n "$APP" -g "rg-helloagenticai-${ENV_NAME}" --tail 100
az containerapp revision list -n "$APP" -g "rg-helloagenticai-${ENV_NAME}" -o table
```

Most likely causes: image build pulled `framework/` incorrectly (PYTHONPATH issue), or the `uvicorn` entrypoint doesn't bind to `0.0.0.0`.

## Decision

These six risks are captured as this preflight runbook rather than mitigated in code. Specifically:

- **No capacity fallback** in `infra/modules/openai.bicep` — silent downgrades violate the user's "never silently downgrade" rule.
- **No runtime region selection** — region is a deliberate architectural choice per `docs/ARCHITECTURE.md` and project memory.
- **No Bicep-side provider registration** — Bicep cannot reliably register subscription-scoped providers from a single deployment.
- **No swap of the placeholder image** — the brief ingress-mismatch window is a non-issue, not worth the complexity of a custom Phase-1-only image.
- **No auto-restart of Docker Desktop** — the agent can `open -a Docker` but only when explicitly working a known-Docker-down state; not as background polling.
- **Bicep dry-run preflight (`azd provision --preview`) is MANDATORY before any `azd up`** — added to `CLAUDE.md` "Useful commands". 30 s of validation beats 8 min of partial-failure cleanup.

## Consequences

Positive:

- Bicep modules stay clean and showcase the architecture without defensive code that obscures intent.
- A single ADR captures all known first-run failure modes with concrete remediation.

Negative (and mitigations):

- A first-time `azd up` in a fresh subscription may fail and require a manual retry — *mitigation:* this runbook makes recovery a 5-minute fix; preflight checks (especially #1) can preempt the most likely failure entirely.

## Scope

Applies to HelloAgenticAI Phase 1 onwards. Refinery and other vertical projects inherit the same risks (same architecture); they should reference this ADR or fork it for vertical-specific differences (e.g. different region per compliance posture).

## Tonight's preflight summary (2026-05-10, ~00:15 Asia/Riyadh)

| Check | Status | Notes |
|---|---|---|
| Active subscription | ✓ verified | `Azure subscription 1` (`d599c6a3-…`), tenant `a5798993-…`, signed in as `sowthri.s@outlook.com` |
| Subscription role | ✓ verified | Owner at subscription scope — risk #2 mitigated |
| AOAI quota (gpt-4o / gpt-4o-mini / embeddings, swedencentral) | ⏳ for Sowthri to verify in Azure portal | Optional but recommended; takes ~5 min in portal, quota approval can take hours |
| Resource-provider registrations | ⏳ deferred | Will be checked at the start of tomorrow's `azd up` (or run the bash snippet above first) |
| Container App initial-image transient | informational | No preflight action; expected behavior |

## Phase 1 first-deploy results (2026-05-10 morning, Asia/Riyadh)

| Check | Result | Notes |
|---|---|---|
| Provider registrations | ✓ all 11 Registered | No registration delay |
| AOAI quota in swedencentral | ✓ implicit | All three deployments succeeded at 10/30/30 K TPM (GlobalStandard / GlobalStandard / Standard) |
| Risk #5(a) Docker daemon | hit | First `azd up` failed at package step — daemon stopped overnight. Restarted via `open -a Docker`, daemon ready in 16 s. |
| Risk #5(b) `azure.yaml` docker.path/context | hit | Second `azd up` failed — paths resolved to `1.AgenticAI/` instead of project root. Fixed in commit `7e495a3`. |
| Risk #6 Bicep validation | hit (3 errors at once) | Third `azd up` partially provisioned then failed: gpt-4o `2024-08-06` deprecating, Storage Blob Data Contributor role GUID typo, ContentSafety `networkAcls.bypass` unsupported. Fixed in commit `29c411a`. |
| Mandatory preflight (`azd provision --preview`) | adopted | Now required by CLAUDE.md before any `azd up`. Validated the fix in 29 s on the fourth attempt. Would have caught risk #6's three errors before any provisioning. |
| `azd up` final | ✓ 5 min 34 s | All 12 resources up, image pushed, Container App revision rolled forward, `/health` returns 200 with placeholder JSON. |
| Risk #4 transient | observed | Container App was on quickstart image briefly during the `provision → deploy` window; rolled forward to the placeholder image automatically. No manual action. |

## References

- `infra/main.bicep`, `infra/modules/openai.bicep`, `infra/modules/container-app.bicep`, `infra/main.parameters.json`
- Memory: `feedback_no_silent_quota_downgrade.md`, `project_helloagenticai_constraints.md`
- `PROJECT_PLAN.md` Phase 1 acceptance criteria
