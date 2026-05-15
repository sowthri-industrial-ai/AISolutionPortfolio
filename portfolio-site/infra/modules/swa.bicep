// Azure Static Web App — Free tier. Hosts the Astro-built portfolio site.
//
// Free tier covers this site indefinitely (per ADR-0002): 100 GB bandwidth,
// 0.5 GB storage, free SSL on the *.azurestaticapps.net subdomain, no SLA.
// Custom domain is deferred to v2.
//
// Deployment trigger: this Bicep is identical for both supported triggers —
//   A) `azd deploy` (azd CLI runs SWA build + upload via the SWA CLI under the hood)
//   B) GitHub Actions via `Azure/static-web-apps-deploy@v1` (the official SWA model)
// The choice only affects azure.yaml + .github/workflows/, not this resource.
// For B, fetch the deploy token after provision via:
//   az staticwebapp secrets list --name <swaName> --query "properties.apiKey" -o tsv
// and store as repo secret AZURE_STATIC_WEB_APPS_API_TOKEN.
//
// `provider: 'None'` + `repositoryUrl: null` keeps the SWA decoupled from
// any GitHub repo at the resource level — required for both trigger options
// (azd deploy needs control of upload; the SWA action also works fine without
// the resource being pre-bound to a repo).

@description('SWA resource name. Globally unique within Microsoft.Web/staticSites.')
@minLength(1)
@maxLength(60)
param name string

@description('Azure region. SWA is a global service but the resource record anchors here.')
param location string

@description('Resource tags.')
param tags object = {}

@description('Optional: Log Analytics workspace resource ID for SWA diagnostic settings. Empty = skip. Wiring is free; only ingested log volume is billable (well under the 5 GB/month LAW free tier for a static site).')
param logAnalyticsWorkspaceId string = ''

resource swa 'Microsoft.Web/staticSites@2023-12-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    // No GitHub binding — both deploy options upload artifacts directly.
    provider: 'None'
    // Astro builds to dist/ — the deploy tooling reads this path post-build.
    buildProperties: {
      appLocation: '/'
      outputLocation: 'dist'
      // skipGithubActionWorkflowGeneration: true — no auto-generated workflow,
      // since we control the deploy explicitly (option A or B above).
      skipGithubActionWorkflowGeneration: true
    }
  }
}

// Optional diagnostic settings → existing LAW (Phase 1 single-pane observability).
// Supported log categories on Microsoft.Web/staticSites — verified LIVE via
// `az monitor diagnostic-settings categories list --resource <swa-id>` (Phase 5a
// Batch 5). The docs-inferred name 'StaticWebAppLogs' is WRONG; ARM accepts it
// at template-build time and only rejects it at real provision — see ADR-0003
// risk #10. Always query the live resource before wiring categories.
//   - StaticSiteHttpLogs:       HTTP request logs (status, path, latency, edge region)
//   - StaticSiteDiagnosticLogs: platform / diagnostic logs
// 'AllMetrics' covers built-in metrics (BytesSent, etc.).
resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(logAnalyticsWorkspaceId)) {
  name: 'swa-to-law'
  scope: swa
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'StaticSiteHttpLogs'
        enabled: true
      }
      {
        category: 'StaticSiteDiagnosticLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

output id string = swa.id
output name string = swa.name
output defaultHostname string = swa.properties.defaultHostname
