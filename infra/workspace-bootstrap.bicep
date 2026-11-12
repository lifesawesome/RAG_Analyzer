targetScope = 'subscription'

param location string = 'westeurope'
param resourceGroupName string = 'rg-rag-dbx-dev-weu'
param workspaceName string = 'dbw-regulatory-demo-weu'

var tags = {
  workload: 'regulatory-rag-demo'
  environment: 'demo'
  deploymentScope: 'workspace-bootstrap'
  reviewAfter: '2026-11-13'
}

resource dataGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module databricks './databricks.bicep' = {
  name: 'regulatory-workspace-bootstrap'
  scope: dataGroup
  params: {
    location: location
    workspaceName: workspaceName
    tags: tags
  }
}

output databricksHost string = databricks.outputs.host
output databricksWorkspaceResourceId string = databricks.outputs.workspaceId
output subscriptionId string = subscription().subscriptionId
output tenantId string = tenant().tenantId
