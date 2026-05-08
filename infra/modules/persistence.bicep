targetScope = 'resourceGroup'

@description('Azure region for persistence resources.')
param location string

@description('Required resource tags.')
param tags object

@description('Delegated subnet ID for PostgreSQL Flexible Server private access.')
param postgresDelegatedSubnetId string

@description('Existing subnet ID for Redis private endpoint.')
param privateEndpointSubnetId string

@description('Centrally managed PostgreSQL Flexible Server private DNS zone ID.')
param postgresPrivateDnsZoneId string

@description('Centrally managed Azure Managed Redis private DNS zone ID.')
param redisPrivateDnsZoneId string

@description('Optional centrally managed Blob Storage private DNS zone ID. Leave empty to skip the storage private endpoint DNS zone group.')
param blobPrivateDnsZoneId string = ''

@description('PostgreSQL Flexible Server name.')
param postgresServerName string

@description('PostgreSQL database name.')
param postgresDatabaseName string

@description('User-assigned managed identity used by db-service for PostgreSQL Entra authentication.')
param postgresIdentityName string

@description('User-assigned managed identity used by db-service for Redis Entra authentication.')
param redisIdentityName string

@description('User-assigned managed identity reserved for Azure Blob log writes.')
param storageLoggingIdentityName string

@description('Initial PostgreSQL Entra administrator object ID.')
param postgresAdminObjectId string

@description('Initial PostgreSQL Entra administrator principal name.')
param postgresAdminPrincipalName string

@description('Initial PostgreSQL Entra administrator principal type.')
param postgresAdminPrincipalType string

@description('Azure Managed Redis / Redis Enterprise cluster name.')
param redisClusterName string

@description('Storage account that receives application log blobs.')
param storageAccountName string

@description('Blob container that receives application log blobs.')
param storageLogsContainerName string

@description('Allow storage shared-key authentication for compatibility with the current connection-string logger. Set false once runtime logging uses Entra ID.')
param storageAllowSharedKeyAccess bool = true

@description('Additional Entra principal object IDs to grant Storage Blob Data Contributor on the logs container.')
param storageBlobDataContributorPrincipalIds array = []

var redisDatabaseName = 'default'
var blobPrivateDnsZoneName = 'privatelink.blob.${environment().suffixes.storage}'
var storageBlobDataContributorRoleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')

resource postgresIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: postgresIdentityName
  location: location
  tags: tags
}

resource redisIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: redisIdentityName
  location: location
  tags: tags
}

resource storageLoggingIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: storageLoggingIdentityName
  location: location
  tags: tags
}

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2025-08-01' = {
  name: postgresServerName
  location: location
  tags: tags
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '17'
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Disabled'
      tenantId: subscription().tenantId
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      delegatedSubnetResourceId: postgresDelegatedSubnetId
      privateDnsZoneArmResourceId: postgresPrivateDnsZoneId
      publicNetworkAccess: 'Disabled'
    }
    storage: {
      autoGrow: 'Enabled'
      storageSizeGB: 32
    }
  }
}

resource postgresAdmin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2025-08-01' = {
  parent: postgresServer
  name: postgresAdminObjectId
  properties: {
    principalName: postgresAdminPrincipalName
    principalType: postgresAdminPrincipalType
    tenantId: subscription().tenantId
  }
}

resource postgresDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2025-08-01' = {
  parent: postgresServer
  name: postgresDatabaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource redisCluster 'Microsoft.Cache/redisEnterprise@2025-07-01' = {
  name: redisClusterName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${redisIdentity.id}': {}
    }
  }
  sku: {
    name: 'Balanced_B0'
  }
  properties: {
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
  }
}

resource redisDatabase 'Microsoft.Cache/redisEnterprise/databases@2025-07-01' = {
  parent: redisCluster
  name: redisDatabaseName
  properties: {
    accessKeysAuthentication: 'Disabled'
    clientProtocol: 'Encrypted'
    clusteringPolicy: 'EnterpriseCluster'
    evictionPolicy: 'NoEviction'
    persistence: {
      aofEnabled: false
      rdbEnabled: false
    }
  }
}

resource redisAccessPolicyAssignment 'Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2025-07-01' = {
  parent: redisDatabase
  name: redisIdentity.name
  properties: {
    accessPolicyName: 'default'
    user: {
      objectId: redisIdentity.properties.principalId
    }
  }
}

resource redisPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: 'pe-${redisClusterName}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'redis-enterprise'
        properties: {
          privateLinkServiceId: redisCluster.id
          groupIds: [
            'redisEnterprise'
          ]
        }
      }
    ]
  }
  dependsOn: [
    redisDatabase
  ]
}

resource redisPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = {
  parent: redisPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink.redis.azure.net'
        properties: {
          privateDnsZoneId: redisPrivateDnsZoneId
        }
      }
    ]
  }
}

resource logsStorageAccount 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowCrossTenantReplication: false
    allowSharedKeyAccess: storageAllowSharedKeyAccess
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    networkAcls: {
      bypass: 'None'
      defaultAction: 'Deny'
      ipRules: []
      virtualNetworkRules: []
    }
    publicNetworkAccess: 'Disabled'
    supportsHttpsTrafficOnly: true
  }
}

resource logsBlobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' existing = {
  parent: logsStorageAccount
  name: 'default'
}

resource logsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: logsBlobService
  name: storageLogsContainerName
  properties: {
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: false
    publicAccess: 'None'
  }
}

resource storagePrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: 'pe-${storageAccountName}-blob'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'pec-${storageAccountName}-blob'
        properties: {
          privateLinkServiceId: logsStorageAccount.id
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
}

resource storagePrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = if (!empty(blobPrivateDnsZoneId)) {
  parent: storagePrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: blobPrivateDnsZoneName
        properties: {
          privateDnsZoneId: blobPrivateDnsZoneId
        }
      }
    ]
  }
}

resource storageLoggingRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(logsContainer.id, storageLoggingIdentity.id, storageBlobDataContributorRoleDefinitionId)
  scope: logsContainer
  properties: {
    principalId: storageLoggingIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageBlobDataContributorRoleDefinitionId
  }
}

resource additionalStorageBlobDataContributorAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in storageBlobDataContributorPrincipalIds: {
  name: guid(logsContainer.id, principalId, storageBlobDataContributorRoleDefinitionId)
  scope: logsContainer
  properties: {
    principalId: principalId
    roleDefinitionId: storageBlobDataContributorRoleDefinitionId
  }
}]

output postgresHost string = postgresServer.properties.fullyQualifiedDomainName
output redisHost string = redisCluster.properties.hostName
output redisPort int = 10000
output postgresManagedIdentityClientId string = postgresIdentity.properties.clientId
output postgresManagedIdentityPrincipalId string = postgresIdentity.properties.principalId
output redisManagedIdentityClientId string = redisIdentity.properties.clientId
output redisManagedIdentityPrincipalId string = redisIdentity.properties.principalId
output storageAccountName string = logsStorageAccount.name
output storageBlobEndpoint string = logsStorageAccount.properties.primaryEndpoints.blob
output storageLogsContainerName string = logsContainer.name
output storageLoggingManagedIdentityClientId string = storageLoggingIdentity.properties.clientId
output storageLoggingManagedIdentityPrincipalId string = storageLoggingIdentity.properties.principalId
