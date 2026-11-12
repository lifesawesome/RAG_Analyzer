targetScope = 'subscription'

param location string = 'westeurope'
param resourceGroupName string = 'rg-rag-foundry-dev-weu'
param accountName string = 'foundry-rag-${uniqueString(subscription().id, resourceGroupName)}'
param projectName string = 'regulatory-research-demo'
param modelDeploymentName string = 'gpt-4.1'
param foundryUserRoleId string = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

var tags = {
  workload: 'regulatory-rag-demo'
  environment: 'demo'
  deploymentScope: 'foundry-bootstrap'
  reviewAfter: '2026-11-13'
}

resource foundryGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module foundry './foundry.bicep' = {
  name: 'regulatory-foundry-bootstrap'
  scope: foundryGroup
  params: {
    location: location
    accountName: accountName
    projectName: projectName
    modelDeploymentName: modelDeploymentName
    foundryUserRoleId: foundryUserRoleId
    tags: tags
  }
}

output foundryProjectEndpoint string = foundry.outputs.projectEndpoint
output foundryAccountName string = accountName
output foundryModelDeploymentName string = modelDeploymentName
output subscriptionId string = subscription().subscriptionId
output tenantId string = tenant().tenantId
