# Temp-Slide Azure Persistence

This folder provisions the Temp-Slide dev persistence layer in the same Azure dev subscription used by Edwin:

- subscription: `pzi-gxx1-sw5t3-dev001`
- app resource group: `rg-temp-slide`
- DevEx network resource group: `pzi-sw5t3-dev001-we-rgp-base-002`
- DevEx VNet: `pzi-sw5t3-dev001-we-vnt-002`
- region: `westeurope`

## Architecture

The layout follows the Apex OS direction while staying minimal for dev:

- `server/db-service` owns durable data in PostgreSQL and runs Alembic migrations.
- Redis is an advisory cache only; Postgres remains the source of truth.
- Azure Blob Storage receives application log blobs in the `logs` container.
- Temp-Slide uses the DevEx-created VNet `pzi-sw5t3-dev001-we-vnt-002`.
- PostgreSQL Flexible Server is private-only, with a delegated subnet and private DNS.
- Azure Managed Redis / Redis Enterprise is private-only, with encrypted client protocol and a private endpoint.
- The storage account is private-only, denies public network traffic, blocks anonymous blob access, and uses a blob private endpoint.
- PostgreSQL uses Microsoft Entra ID-only authentication to satisfy PwC policy.
- Redis access-key authentication is disabled; db-service authenticates with a managed identity token.
- Storage creates a dedicated user-assigned managed identity for future Entra-authenticated log writes and grants it `Storage Blob Data Contributor` on the `logs` container.

## Network Prerequisites

The DevEx VNet was created with:

- address space: `10.98.206.0/24`
- app integration subnet: `pzi-sw5t3-dev001-we-snt-005` (`10.98.206.0/27`), delegated to `Microsoft.Web/serverFarms`

The required additional subnets are:

- `pzi-sw5t3-dev001-we-snt-006` - `10.98.206.32/28`, delegation `Microsoft.DBforPostgreSQL/flexibleServers`
- `pzi-sw5t3-dev001-we-snt-007` - `10.98.206.48/28`, no delegation, private endpoint network policies disabled

The template references the centrally managed Private DNS zones in subscription
`PZI-GXUS-P-SUB013`, resource group `pzi-gxus-p-rgp-eddi-p003`:

- `flexible.postgres.database.azure.com`
- `privatelink.redis.azure.net`
- `privatelink.blob.core.windows.net` for the storage account blob endpoint

Direct Private DNS zone VNet links are optional in this template because the
NGC landing-zone VNets use PwC custom DNS servers (`10.250.0.1`, `10.250.0.2`),
matching the vector410/Apex test VNet pattern. If platform later requires
explicit VNet links, run this template with `createCentralDnsLinks=true` from an
account that has `Microsoft.Network/privateDnsZones/virtualNetworkLinks/write`.

Do not create `privatelink.blob.core.windows.net` in the dev subscription. That
is blocked by PwC policy `az-028`; the template only references a centrally
managed zone when `blobPrivateDnsZoneId` is supplied. If that parameter is empty,
the blob private endpoint is created without a private DNS zone group and GHS /
central DNS must provide name resolution separately.

The existing dev storage endpoint is:

- storage account: `sttempslidelogsdev`
- container: `logs`
- blob private endpoint: `pe-sttempslidelogsdev-blob`
- blob private endpoint IP: `10.98.206.53`
- blob FQDN: `sttempslidelogsdev.blob.core.windows.net`

Until GHS/private DNS resolves the blob FQDN privately, normal DNS can still
resolve to a public storage IP even though data-plane access requires the private
endpoint. For a short local smoke test only, force the FQDN to the private
endpoint IP:

```bash
sudo sh -c 'printf "\n10.98.206.53 sttempslidelogsdev.blob.core.windows.net\n" >> /etc/hosts'
```

Remove that hosts entry after testing. It is not a deployment substitute for
central private DNS.

## Deploy

```bash
az account set --subscription pzi-gxx1-sw5t3-dev001

az deployment sub what-if \
  --location westeurope \
  --template-file infra/main.bicep

az deployment sub create \
  --location westeurope \
  --template-file infra/main.bicep
```

If the central blob private DNS zone exists and the deployment principal may
attach a private DNS zone group, pass its resource ID:

```bash
az deployment sub create \
  --location westeurope \
  --template-file infra/main.bicep \
  --parameters blobPrivateDnsZoneId=/subscriptions/<central-dns-subscription-id>/resourceGroups/<central-dns-rg>/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net
```

If platform asks for explicit DNS VNet links:

```bash
az deployment sub create \
  --location westeurope \
  --template-file infra/main.bicep \
  --parameters createCentralDnsLinks=true
```

Additional user or group RBAC for the logs container is parameterized. Pass
Entra object IDs, not email addresses:

```bash
az deployment sub create \
  --location westeurope \
  --template-file infra/main.bicep \
  --parameters storageBlobDataContributorPrincipalIds='["<principal-object-id>"]'
```

The live dev container currently has `Storage Blob Data Contributor` assigned to
the required team members. Keep those assignments in Azure or pass the
corresponding object IDs through `storageBlobDataContributorPrincipalIds` if the
deployment should manage them.

## Runtime Settings

Use the deployment outputs to configure the future DB service host.

```bash
POSTGRES_HOST=<postgres-host>
POSTGRES_DATABASE=tempslide
POSTGRES_USER=id-temp-slide-postgres-dev
POSTGRES_USE_ENTRA_AUTH=true
POSTGRES_ENTRA_CLIENT_ID=<postgres-managed-identity-client-id>
POSTGRES_SSL=true

REDIS_URL=rediss://<redis-host>:10000/0
REDIS_USE_ENTRA_AUTH=true
REDIS_ENTRA_CLIENT_ID=<redis-managed-identity-client-id>
REDIS_ENTRA_PRINCIPAL_ID=<redis-managed-identity-principal-id>
```

After PostgreSQL is created, the initial Entra admin must grant database access
to the Postgres managed identity before Alembic migrations can run.

Storage logging outputs:

```bash
STORAGE_BLOB_ACCOUNT_URL=https://sttempslidelogsdev.blob.core.windows.net/
STORAGE_LOGS_CONTAINER=logs
STORAGE_LOGGING_ENTRA_CLIENT_ID=<storage-logging-managed-identity-client-id>
STORAGE_LOGGING_ENTRA_PRINCIPAL_ID=<storage-logging-managed-identity-principal-id>
```

The preferred runtime model is managed identity with the deployed
`id-temp-slide-storage-logs-dev` identity. The current `app_logger` Azure handler
still accepts only a storage connection string, so do not disable shared-key
access for an environment that has `LOG_AZURE_ENABLED=true` until the handler is
extended to use `DefaultAzureCredential` or `ManagedIdentityCredential`. The IaC
keeps shared-key access parameterized with `storageAllowSharedKeyAccess`; set it
to `false` once runtime logging no longer needs connection strings.

Current backend logging variables for the connection-string handler are:

```bash
LOG_AZURE_ENABLED=true
LOG_AZURE_CONNECTION_STRING=<store in Key Vault or app settings, never commit>
LOG_AZURE_CONTAINER=logs
LOG_AZURE_BLOB_PREFIX=app
```

## Storage Smoke Tests

From a host that resolves `sttempslidelogsdev.blob.core.windows.net` to the
private endpoint IP and has `Storage Blob Data Contributor` on the container:

```bash
az storage container list \
  --account-name sttempslidelogsdev \
  --auth-mode login
```

For a write smoke test:

```bash
printf "temp-slide storage smoke test\n" > /tmp/temp-slide-storage-smoke.txt
az storage blob upload \
  --account-name sttempslidelogsdev \
  --container-name logs \
  --name smoke/temp-slide-storage-smoke.txt \
  --file /tmp/temp-slide-storage-smoke.txt \
  --auth-mode login \
  --overwrite
```
