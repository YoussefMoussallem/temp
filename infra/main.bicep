targetScope = 'subscription'

@description('Azure region for Temp-Slide dev persistence resources.')
param location string = 'westeurope'

@description('Resource group that will contain Temp-Slide dev application resources.')
param resourceGroupName string = 'rg-temp-slide'

@description('Resource group containing the DevEx-created Temp-Slide virtual network.')
param networkResourceGroupName string = 'pzi-sw5t3-dev001-we-rgp-base-002'

@description('DevEx-created Temp-Slide virtual network name.')
param virtualNetworkName string = 'pzi-sw5t3-dev001-we-vnt-002'

@description('Existing subnet for PostgreSQL Flexible Server private access.')
param postgresSubnetName string = 'pzi-sw5t3-dev001-we-snt-006'

@description('Existing subnet for private endpoints.')
param privateEndpointSubnetName string = 'pzi-sw5t3-dev001-we-snt-007'

@description('Subscription that hosts centrally managed Private DNS zones.')
param centralPrivateDnsSubscriptionId string = 'c72daa19-9a38-4155-b2c6-9121045a0fdc'

@description('Resource group that hosts centrally managed Private DNS zones.')
param centralPrivateDnsResourceGroupName string = 'pzi-gxus-p-rgp-eddi-p003'

@description('Centrally managed PostgreSQL Flexible Server private DNS zone name.')
param postgresPrivateDnsZoneName string = 'flexible.postgres.database.azure.com'

@description('Centrally managed Azure Managed Redis private DNS zone name.')
param redisPrivateDnsZoneName string = 'privatelink.redis.azure.net'

@description('Centrally managed Blob Storage private DNS zone name, used only when creating optional central DNS VNet links.')
param blobPrivateDnsZoneName string = 'privatelink.blob.${environment().suffixes.storage}'

@description('Optional centrally managed Blob Storage private DNS zone resource ID. Leave empty to skip the storage private endpoint DNS zone group.')
param blobPrivateDnsZoneId string = ''

@description('Create central Private DNS VNet links. Requires Microsoft.Network/privateDnsZones/virtualNetworkLinks/write on the central DNS resource group.')
param createCentralDnsLinks bool = false

@description('PostgreSQL Flexible Server name.')
param postgresServerName string = 'pgsql-temp-slide-dev'

@description('PostgreSQL database used by server/db-service Alembic migrations.')
param postgresDatabaseName string = 'tempslide'

@description('User-assigned managed identity used by db-service for PostgreSQL Entra authentication.')
param postgresIdentityName string = 'id-temp-slide-postgres-dev'

@description('User-assigned managed identity used by db-service for Redis Entra authentication.')
param redisIdentityName string = 'id-temp-slide-redis-dev'

@description('User-assigned managed identity reserved for Azure Blob log writes.')
param storageLoggingIdentityName string = 'id-temp-slide-storage-logs-dev'

@description('Initial PostgreSQL Entra administrator object ID. Defaults to the current deployment user.')
param postgresAdminObjectId string = 'd420f154-0ca2-466d-8281-8d40781fadc0'

@description('Initial PostgreSQL Entra administrator principal name.')
param postgresAdminPrincipalName string = 'bahaa.kaaki@admin.pwc.com'

@allowed([
  'Group'
  'ServicePrincipal'
  'Unknown'
  'User'
])
@description('Initial PostgreSQL Entra administrator principal type.')
param postgresAdminPrincipalType string = 'User'

@description('Azure Managed Redis / Redis Enterprise cluster name.')
param redisClusterName string = 'redis-temp-slide-dev'

@description('Storage account that receives application log blobs.')
param storageAccountName string = 'sttempslidelogsdev'

@description('Blob container that receives application log blobs.')
param storageLogsContainerName string = 'logs'

@description('Allow storage shared-key authentication for compatibility with the current connection-string logger. Set false once runtime logging uses Entra ID.')
param storageAllowSharedKeyAccess bool = true

@description('Additional Entra principal object IDs to grant Storage Blob Data Contributor on the logs container.')
param storageBlobDataContributorPrincipalIds array = []

@description('Required PwC/GHS resource tags inherited from the Edwin dev subscription conventions.')
param tags object = {
  'ghs-appid': '7d390fc2-5b18-3906-17e4-73a189f6c38f'
  'ghs-apptioid': 'middleeast14377'
  'ghs-compliance': 'none'
  'ghs-dataclassification': 'public'
  'ghs-envid': 'f45fa419-65ee-4563-8ebd-d18aa3381227'
  'ghs-environment': 'dev-temp-slide'
  'ghs-environmenttype': 'development'
  'ghs-owner': 'SW5T3-DEV001-admin'
  'ghs-serviceoffering': 'scni_base'
  'ghs-solutionexposure': 'pwc_internal'
  'ghs-tariff': 'zcm'
  'ghs-territory': 'pwc_middle_east'
}

resource appResourceGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module dnsLinks 'modules/central-dns-links.bicep' = if (createCentralDnsLinks) {
  name: 'temp-slide-central-dns-links'
  scope: resourceGroup(centralPrivateDnsSubscriptionId, centralPrivateDnsResourceGroupName)
  params: {
    virtualNetworkId: resourceId(subscription().subscriptionId, networkResourceGroupName, 'Microsoft.Network/virtualNetworks', virtualNetworkName)
    postgresPrivateDnsZoneName: postgresPrivateDnsZoneName
    redisPrivateDnsZoneName: redisPrivateDnsZoneName
    blobPrivateDnsZoneName: blobPrivateDnsZoneName
  }
}

module persistence 'modules/persistence.bicep' = {
  name: 'temp-slide-persistence'
  scope: appResourceGroup
  params: {
    location: location
    tags: tags
    postgresDelegatedSubnetId: resourceId(subscription().subscriptionId, networkResourceGroupName, 'Microsoft.Network/virtualNetworks/subnets', virtualNetworkName, postgresSubnetName)
    privateEndpointSubnetId: resourceId(subscription().subscriptionId, networkResourceGroupName, 'Microsoft.Network/virtualNetworks/subnets', virtualNetworkName, privateEndpointSubnetName)
    postgresPrivateDnsZoneId: resourceId(centralPrivateDnsSubscriptionId, centralPrivateDnsResourceGroupName, 'Microsoft.Network/privateDnsZones', postgresPrivateDnsZoneName)
    redisPrivateDnsZoneId: resourceId(centralPrivateDnsSubscriptionId, centralPrivateDnsResourceGroupName, 'Microsoft.Network/privateDnsZones', redisPrivateDnsZoneName)
    blobPrivateDnsZoneId: blobPrivateDnsZoneId
    postgresServerName: postgresServerName
    postgresDatabaseName: postgresDatabaseName
    postgresIdentityName: postgresIdentityName
    redisIdentityName: redisIdentityName
    storageLoggingIdentityName: storageLoggingIdentityName
    postgresAdminObjectId: postgresAdminObjectId
    postgresAdminPrincipalName: postgresAdminPrincipalName
    postgresAdminPrincipalType: postgresAdminPrincipalType
    redisClusterName: redisClusterName
    storageAccountName: storageAccountName
    storageLogsContainerName: storageLogsContainerName
    storageAllowSharedKeyAccess: storageAllowSharedKeyAccess
    storageBlobDataContributorPrincipalIds: storageBlobDataContributorPrincipalIds
  }
}

output resourceGroup string = appResourceGroup.name
output postgresHost string = persistence.outputs.postgresHost
output postgresDatabase string = postgresDatabaseName
output postgresUser string = postgresIdentityName
output postgresManagedIdentityClientId string = persistence.outputs.postgresManagedIdentityClientId
output postgresManagedIdentityPrincipalId string = persistence.outputs.postgresManagedIdentityPrincipalId
output redisHost string = persistence.outputs.redisHost
output redisPort int = persistence.outputs.redisPort
output redisManagedIdentityClientId string = persistence.outputs.redisManagedIdentityClientId
output redisManagedIdentityPrincipalId string = persistence.outputs.redisManagedIdentityPrincipalId
output storageAccountName string = persistence.outputs.storageAccountName
output storageBlobEndpoint string = persistence.outputs.storageBlobEndpoint
output storageLogsContainerName string = persistence.outputs.storageLogsContainerName
output storageLoggingManagedIdentityClientId string = persistence.outputs.storageLoggingManagedIdentityClientId
output storageLoggingManagedIdentityPrincipalId string = persistence.outputs.storageLoggingManagedIdentityPrincipalId
output postgresDsnTemplate string = 'postgresql://${postgresIdentityName}@${persistence.outputs.postgresHost}:5432/${postgresDatabaseName}?sslmode=require'
output redisUrlTemplate string = 'rediss://${persistence.outputs.redisHost}:${persistence.outputs.redisPort}/0'
output storageBlobAccountUrl string = persistence.outputs.storageBlobEndpoint
