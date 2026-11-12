targetScope = 'subscription'

param location string = 'westeurope'
param dataResourceGroupName string = 'rg-rag-dbx-dev-weu'
param foundryResourceGroupName string = 'rg-rag-foundry-dev-weu'
param workspaceName string = 'dbw-regulatory-demo-weu'
param foundryAccountName string = 'foundry-rag-${uniqueString(subscription().id, foundryResourceGroupName)}'
param projectName string = 'regulatory-research-demo'
param modelDeploymentName string = 'gpt-4.1'
param foundryUserRoleId string

var tags = {
  workload: 'regulatory-rag-demo'
  environment: 'demo'
  budgetTarget: 'USD300-per-month'
  reviewAfter: '2026-11-11'
}

resource dataGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: dataResourceGroupName
  location: location
  tags: tags
}

resource foundryGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: foundryResourceGroupName
  location: location
  tags: tags
}

module databricks './databricks.bicep' = {
  name: 'regulatory-databricks-foundation'
  scope: dataGroup
  params: {
    location: location
    workspaceName: workspaceName
    tags: tags
  }
}

module foundry './foundry.bicep' = {
  name: 'regulatory-foundry-foundation'
  scope: foundryGroup
  params: {
    location: location
    accountName: foundryAccountName
    projectName: projectName
    modelDeploymentName: modelDeploymentName
    foundryUserRoleId: foundryUserRoleId
    tags: tags
  }
}

output databricksHost string = databricks.outputs.host
output databricksWorkspaceId string = databricks.outputs.workspaceId
output foundryProjectEndpoint string = foundry.outputs.projectEndpoint
output foundryAccountName string = foundryAccountName
output foundryModelDeploymentName string = modelDeploymentName
