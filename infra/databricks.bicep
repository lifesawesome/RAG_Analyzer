param location string
param workspaceName string
param tags object

resource workspace 'Microsoft.Databricks/workspaces@2024-05-01' = {
  name: workspaceName
  location: location
  tags: tags
  sku: {
    name: 'premium'
  }
  properties: {
    managedResourceGroupId: subscriptionResourceId('Microsoft.Resources/resourceGroups', 'rg-rag-dbx-managed-dev-weu')
    publicNetworkAccess: 'Enabled'
    parameters: {
      enableNoPublicIp: {
        value: true
      }
    }
  }
}

output host string = 'https://${workspace.properties.workspaceUrl}'
output workspaceId string = workspace.id
