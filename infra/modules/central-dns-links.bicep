targetScope = 'resourceGroup'

@description('Temp-Slide VNet ID to link to central Private DNS zones.')
param virtualNetworkId string

@description('Centrally managed PostgreSQL Flexible Server private DNS zone name.')
param postgresPrivateDnsZoneName string

@description('Centrally managed Azure Managed Redis private DNS zone name.')
param redisPrivateDnsZoneName string

@description('Optional centrally managed Blob Storage private DNS zone name.')
param blobPrivateDnsZoneName string = ''

resource postgresPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' existing = {
  name: postgresPrivateDnsZoneName
}

resource redisPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' existing = {
  name: redisPrivateDnsZoneName
}

resource blobPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' existing = if (!empty(blobPrivateDnsZoneName)) {
  name: blobPrivateDnsZoneName
}

resource postgresVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: postgresPrivateDnsZone
  name: 'lnk-temp-slide-dev-postgres'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

resource redisVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: redisPrivateDnsZone
  name: 'lnk-temp-slide-dev-redis'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

resource blobVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!empty(blobPrivateDnsZoneName)) {
  parent: blobPrivateDnsZone
  name: 'lnk-temp-slide-dev-blob'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

output postgresPrivateDnsZoneId string = postgresPrivateDnsZone.id
output redisPrivateDnsZoneId string = redisPrivateDnsZone.id
output blobPrivateDnsZoneId string = empty(blobPrivateDnsZoneName) ? '' : blobPrivateDnsZone.id
