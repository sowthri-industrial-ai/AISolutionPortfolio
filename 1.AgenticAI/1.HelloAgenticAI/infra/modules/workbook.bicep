// Azure Monitor Workbook bound to an App Insights component. Phase 4
// deliverable 5: the "operational dashboard" demo link in the README.
//
// The workbook content (charts + KQL) lives in
// `infra/workbooks/agent-observability.workbook.json` and is loaded via
// `loadTextContent()` at template-compile time — keeps the JSON readable
// and diff-friendly, doesn't bake it into the Bicep itself.
//
// Resource name is a deterministic GUID per (resourceGroup, displayName)
// so re-provisioning is idempotent (Microsoft.Insights/workbooks
// requires a GUID name; using a stable hash here means `azd provision`
// updates the existing workbook in place rather than creating a new
// one on every run).

@description('Workbook display name (shown in Azure Portal → Application Insights → Workbooks).')
@minLength(1)
param displayName string

@description('App Insights component resource id this workbook reads from. From observability.outputs.appInsightsId.')
param appInsightsResourceId string

@description('Workbook serialized data — the JSON content of the workbook, loaded via loadTextContent() in main.bicep.')
param workbookJsonContent string

@description('Azure region (workbooks colocate with the App Insights resource).')
param location string

@description('Resource tags.')
param tags object = {}

resource workbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: guid(resourceGroup().id, displayName)
  location: location
  tags: tags
  kind: 'shared'
  properties: {
    displayName: displayName
    serializedData: workbookJsonContent
    sourceId: appInsightsResourceId
    category: 'workbook'
    version: 'Notebook/1.0'
  }
}

output id string = workbook.id
output name string = workbook.name
