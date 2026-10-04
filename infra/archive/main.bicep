@description('Globally unique name for the dedicated public evidence storage account.')
@minLength(3)
@maxLength(24)
param storageAccountName string

@description('Object ID of the existing GitHub OIDC deployment service principal.')
param publisherPrincipalId string

param location string = resourceGroup().location
param containerName string = 'history'

resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    allowBlobPublicAccess: true
    allowCrossTenantReplication: false
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: account
  name: 'default'
  properties: {
    isVersioningEnabled: true
    deleteRetentionPolicy: {
      enabled: true
      days: 30
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 30
    }
  }
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobs
  name: containerName
  properties: {
    publicAccess: 'Blob'
  }
}

var blobContributorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
)

resource publisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(container.id, publisherPrincipalId, blobContributorRoleId)
  scope: container
  properties: {
    principalId: publisherPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobContributorRoleId
  }
}

output archiveBaseUrl string = '${account.properties.primaryEndpoints.blob}${containerName}'
output storageAccountId string = account.id
output publisherScope string = container.id
