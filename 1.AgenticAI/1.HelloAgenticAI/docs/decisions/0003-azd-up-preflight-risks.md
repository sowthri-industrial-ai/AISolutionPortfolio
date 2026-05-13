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

### 7. DefaultAzureCredential local-dev vs Container App managed identity

**Symptom:** integration tests run from a developer's machine (post-`azd up`) get `401`/`403` PermissionDenied from Cosmos / AOAI / Content Safety / Storage / Key Vault even though the Container App in Azure works fine against the same resources.

**Cause:** Phase 1 Bicep grants every data-plane role to the **runtime user-assigned managed identity** (`id-helloagenticai-dev-…`). That identity is what the deployed Container App uses. **Local development uses a different principal** — your `az login` user, picked up by `DefaultAzureCredential` via the AzureCLI credential type. The MI's grants don't transfer; the dev principal needs analogous grants.

This is a structural truth about Azure managed-identity auth, not a v1 bug. Production-style code uses MI; local-dev code uses your user; the two principals need separate grants.

**Empirical note (2026-05-10, HelloAgenticAI Phase 2 first integration test):**

| Service | Grant time → request 200 (dev principal) |
|---|---|
| Cosmos DB | <2 min |
| Storage | <2 min (anticipated; not directly measured) |
| Azure OpenAI | **>45 min observed** (Microsoft documents up to 30 min for Cognitive Services; this run exceeded that) |
| Content Safety | likely similar to AOAI (Cognitive Services family) |
| Key Vault | <5 min (typical) |

Plan AOAI grants accordingly: don't run integration tests immediately after a fresh AOAI grant; wait 30+ min, or use a wait-and-retry loop that re-attempts the test every 5 min for up to 60 min.

**Remediation:**

1. Mirror the Phase 1 MI grants to your dev principal. The exact `az` commands are in `CLAUDE.md` §"First-time / post-teardown developer setup" — Cosmos, AOAI, plus the Content Safety / Storage / Key Vault grants needed by Phase 4+.
2. If a grant is in place but the request still 401s after 60 min, then it's not propagation — investigate the role assignment scope, the resource's `disableLocalAuth` setting, and the credential's tenant binding.

**Permanent fix (Phase 5):** `docs/decisions/TODO-phase-5-data-plane-rbac.md` specs a Bicep refactor that adds optional `developerPrincipalId` and `oidcServicePrincipalId` parameters to each per-service module, conditionally creating the analogous role assignments at provision time. After Phase 5 lands, `azd up` is idempotent for both production-style and dev-style auth — no manual `az` commands.

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

**Wider lesson surfaced in Phase 3 (2026-05-11):** the original Phase 1 Bicep had the placeholder image hardcoded as a *default* in `container-app.bicep` (`param image string = 'mcr.microsoft.com/k8se/quickstart:latest'`) and never wired it through `main.bicep` as a parameter. That made the symptom above sound transient ("expected and self-resolves within the same `azd up` invocation") — but only because `azd up` runs `provision` then `deploy` in sequence. **Any subsequent solo `azd provision`** (e.g. to push a small Bicep-only change to env vars, IAM, or networking) silently reverts the Container App's image to the placeholder. The hardcoded default in the module is the design defect.

The canonical azd idiom for image-bearing Container App Bicep is:

1. Bicep module receives `image` as a required parameter (no default — the source of truth is the parameter substitution, not a stale local default).
2. `main.bicep` declares a top-level `containerImage` parameter and passes it through.
3. `main.parameters.json` substitutes the value: `"containerImage": { "value": "${SERVICE_AGENT_IMAGE_NAME=mcr.microsoft.com/k8se/quickstart:latest}" }`. azd populates `SERVICE_AGENT_IMAGE_NAME` after every `azd deploy`; the `=default` clause keeps the placeholder as the *only* fallback, used solely pre-first-deploy.

After this wiring lands, `azd provision` and `azd deploy` are independent and idempotent: `provision` preserves the latest deployed image; `deploy` updates only the image. Risk #4's "expected transient" window is then bounded entirely to the very first `azd up` on a fresh subscription.

Applied to HelloAgenticAI 2026-05-11 (commit on `phase-3-fruitmarket` alongside the AOAI/Cosmos env wiring). Any vertical project that copied Phase 1's Bicep before this date inherited the same defect — see the cross-lane note that should accompany this commit.

### 8. Phase-zero placeholder containers should exercise the full credential-reach surface

**Surfaced in:** Phase 3 deploy, when Chainlit tried to read `AZURE_OPENAI_ENDPOINT` and `AZURE_COSMOS_ENDPOINT` and found them unset.

**Root cause:** Phase 1's `placeholder.py` only checked `CONTAINER_APP_NAME` / `CONTAINER_APP_REVISION`. The Bicep env block in `container-app.bicep` only set `AZURE_CLIENT_ID` + `CONTAINER_APP_NAME`. AOAI and Cosmos endpoints were declared as outputs in `main.bicep` but never threaded into the Container App module. The Dockerfile comment referred to env injection that didn't exist. Phase 1 looked green, but actually had a latent gap in the data-plane env wiring that only Phase 3's real application discovered.

**Lesson for future projects:** A Phase-zero placeholder must do a one-shot credential-reach smoke test against every data-plane dependency the production app will use. For HelloAgenticAI, that means: at `/health`, the placeholder should attempt a token mint via `DefaultAzureCredential` for AOAI scope, attempt a token mint for Cosmos scope, and return both endpoints + success/fail booleans in the response body. If either is missing or the credential mint fails, `/health` returns 500. This catches env-wiring gaps and RBAC propagation issues during Phase 1 instead of Phase 3.

**Migration note:** Apply this lesson to RefineryDigitalTwin Phase 1 before its Phase 3 lands — same Bicep-wiring class of bug can exist there.

**Observation during the Phase 3 wiring fix:** `azd provision --preview` (run before applying the env-wiring fix, then re-run with the fix stashed for baseline comparison) revealed pre-existing drift from Phase 1's initial provision — Cosmos `enableAutomaticFailover=true` (ARM-default-at-deploy-time that Bicep never declared, now reverting to `false`), AOAI `currentCapacity` (server-managed output that Bicep doesn't track), Key Vault `networkAcls` (explicit default vs. implicit), Container Apps Environment customerId switching from literal to reference, App Insights `Flow_Type`/`Request_Source` auto-populated values being re-applied, ACR `dataEndpointEnabled`/`encryption` defaults. All functionally no-op for our single-region single-tenant setup, but a reminder that ARM what-if shows the Bicep-vs-deployed gap, not just intended changes. The two `--preview` runs were byte-identical except for duration — proving the drift was independent of the env-wiring commit. Future preflight reviews should distinguish "my intended change" from "pre-existing convergence noise" explicitly — and run preview against an unmodified Bicep baseline when in doubt.

**Postscript — preview opacity at the property level (same session):** the env-wiring `azd provision` (between the env-wiring commit and the image-parameterization commit) reverted the Container App's image to the quickstart placeholder, because the Bicep module had the placeholder hardcoded as the parameter default (the design defect now captured in risk #4's "Wider lesson" paragraph). Crucially, the `--preview` summary did *not* surface this — it grouped both the env-block change and the image revert under one `* properties.template.containers` line. The baseline-vs-with-changes diff was byte-identical (except duration), giving false confidence that only the env vars would change. The image revert was caught **post-provision** via console logs (`Listening on :80...` instead of Chainlit on 8000), not in the preview. **Lesson:** when preview analysis is consequential, do not stop at the resource-level summary — drill into property-level state explicitly, e.g. `az containerapp show -n <name> -g <rg> --query "properties.template.containers[0].image" -o tsv` against the deployed resource, and reason about every property Bicep is going to assert (especially default-bearing ones). The preview's opaque grouping is a known azd limitation; defence is property-level inspection before provision, not after.

### 9. OpenTelemetry SpanKind determines which App Insights table the data lands in

**Surfaced in:** Phase 4 Batch 8 smoke test — the workbook charts showed empty data even though `AppInsightsSink` was successfully sending events. The user clicked through the workbook and saw "No data available" on every chart. AppInsightsSink container logs showed `Transmission succeeded: Item received: 8` lines, so events were definitely being exported. The mismatch was in the workbook's KQL.

**Root cause:** Spans created via `tracer.start_as_current_span(name)` default to `SpanKind.INTERNAL`. The `azure-monitor-opentelemetry` exporter maps SpanKind to App Insights tables as follows:

| SpanKind | App Insights table (Log Analytics schema name) |
|---|---|
| `SERVER` | `requests` (`AppRequests`) |
| `CLIENT`, `PRODUCER`, `CONSUMER` | `dependencies` (`AppDependencies`) |
| `INTERNAL` (default) | `dependencies` (`AppDependencies`) |

The Phase 4 batch 7 workbook KQL queried `requests` (= `AppRequests`), but our `AppInsightsSink` emits INTERNAL spans, which land in `dependencies` (= `AppDependencies`). Backend was correct; workbook was querying the wrong table.

**Workaround in tree:** Workbook KQL fixed to query `dependencies` instead of `requests` in `infra/workbooks/agent-observability.workbook.json` (7 occurrences). Header markdown also gained a "Why dependencies (not requests)" explainer pointing back to this risk entry, so future readers don't repeat the lookup.

**Lesson for future projects:** When adding OTel-based workbooks (or KQL queries that aggregate App Insights spans), verify the SpanKind → table mapping **post-first-event-emission** with both queries:

```kql
AppRequests
| where TimeGenerated > ago(15m)
| where Name in ("plan_start", "plan_complete", ...)
| summarize count() by Name

AppDependencies
| where TimeGenerated > ago(15m)
| where Name in ("plan_start", "plan_complete", ...)
| summarize count() by Name
```

Whichever returns non-zero rows is the right table. If you're emitting via `start_as_current_span(name)` (no explicit kind), it's `dependencies`. If you've explicitly set `SpanKind.SERVER` (e.g. for an HTTP request handler), it's `requests`. **Document the choice in the workbook JSON's comments so future readers don't have to rediscover it.**

**Why the bug existed:** Phase 4 batch 7's pre-provision preview ran cleanly (workbook JSON was valid, ARM accepted the resource, no Bicep errors). The bug was only detectable **after** AppInsightsSink had emitted real events from a real run — i.e., post-deploy. A unit test on the workbook JSON wouldn't have caught it; verification requires live data ingestion. **For Phase 5 and beyond, workbook KQL changes should always be followed by a one-event smoke test before declaring victory.**

## Decision

These seven risks are captured as this preflight runbook rather than mitigated in code. Specifically:

- **No capacity fallback** in `infra/modules/openai.bicep` — silent downgrades violate the user's "never silently downgrade" rule.
- **No runtime region selection** — region is a deliberate architectural choice per `docs/ARCHITECTURE.md` and project memory.
- **No Bicep-side provider registration** — Bicep cannot reliably register subscription-scoped providers from a single deployment.
- **No swap of the placeholder image** — the brief ingress-mismatch window is a non-issue, not worth the complexity of a custom Phase-1-only image.
- **No auto-restart of Docker Desktop** — the agent can `open -a Docker` but only when explicitly working a known-Docker-down state; not as background polling.
- **Bicep dry-run preflight (`azd provision --preview`) is MANDATORY before any `azd up`** — added to `CLAUDE.md` "Useful commands". 30 s of validation beats 8 min of partial-failure cleanup.
- **Dev-principal data-plane grants are NOT in v1 Bicep** — Phase 1's modules grant data-plane roles only to the runtime managed identity. Local-dev grants are documented as a runbook in `CLAUDE.md` "First-time / post-teardown developer setup" (and recapped in risk #7) until the Phase 5 Bicep refactor (`docs/decisions/TODO-phase-5-data-plane-rbac.md`) makes them declarative + parameterized. v1 keeps the Bicep production-only and clean.

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
