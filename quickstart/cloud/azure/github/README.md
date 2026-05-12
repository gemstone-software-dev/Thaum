# Azure Container Apps + GitHub Actions

Deploy Thaum as a **single** container app on **Azure Container Apps** using an image from a **container registry** (public [GHCR](https://github.com/orgs/gemstone-software-dev/packages) or your own **ACR** after [GitHub Actions](deploy.yml.example) builds and pushes). This quickstart does not use `az containerapp up --source .`; it follows the registry-based pattern in [Tutorial: Build and deploy your app to Azure Container Apps (ACR-remote)](https://learn.microsoft.com/en-us/azure/container-apps/tutorial-code-to-cloud?tabs=bash%2Ccsharp&pivots=acr-remote).

- General Thaum quickstart: [QUICKSTART.md](../../../QUICKSTART.md)
- Example TOML (adjust for Azure): [systemd/thaum.conf.example](../../../systemd/thaum.conf.example)
- Container image tags (GHCR, etc.): [README.md](../../../../README.md) (section *Container images (CI)*)

Microsoft references for secrets and Key Vault:

- [Manage secrets in Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets?tabs=azure-cli) (`keyvaultref`, `secretref`, [mounting secrets in a volume](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets?tabs=azure-cli#mounting-secrets-in-a-volume), [referencing secrets in environment variables](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets?tabs=azure-cli#referencing-secrets-in-environment-variables))
- [`az keyvault secret set`](https://learn.microsoft.com/en-us/cli/azure/keyvault/secret?view=azure-cli-latest#az-keyvault-secret-set)
- [Key Vault secret names](https://learn.microsoft.com/en-us/azure/key-vault/general/about-keys-secrets-certificates#object-types) — alphanumeric characters and hyphens only (no underscores). **Azure Container Apps** secret names must be **lowercase only**, at most [**20 characters**](https://learn.microsoft.com/en-us/cli/azure/containerapp/secret?view=azure-cli-latest#az-containerapp-secret-set). Examples below use **kebab-case** so the same names work in Key Vault, Container Apps ([`az containerapp secret set`](https://learn.microsoft.com/en-us/cli/azure/containerapp/secret?view=azure-cli-latest#az-containerapp-secret-set) `--secrets`), and `secret:<name>` in `thaum.toml`.

## What you get

| Aspect | Behavior |
|--------|----------|
| **Topology** | One resource group, one Container Apps environment, one Container App |
| **Image** | Pulled from **GHCR** (simplest if the image is public) or **ACR** (typical with a deploy repo and CI) |
| **Default database** | **Bundled PostgreSQL** inside the official Thaum image (`THAUM_EXTERNAL_DB` unset or false). No managed database cost. |
| **Data durability** | Container filesystem is **ephemeral**. The bundled Postgres store can **lose data** on revision change or restart unless you add persistent storage or switch to an external database. |
| **Optional upgrade** | **Azure Database for PostgreSQL** (or other managed Postgres): set **`THAUM_EXTERNAL_DB=true`**, set **`[server.database].db_url`** in your TOML (and supply credentials via Key Vault as below). See [Optional: external managed Postgres](#optional-external-managed-postgres). |

## Prerequisites

- Azure subscription and rights to create resource groups, Container Apps, Key Vault, and (for ACR) Azure Container Registry; permission to **assign RBAC roles** and **manage Key Vault secrets** when following [§2](#2-key-vault-and-user-assigned-managed-identity-uami) (see [§2.1](#21-key-vault-and-secret-values) if uploads fail with authorization errors)
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az login`)
- A GitHub repository for **your** deployment assets (Dockerfile + config + workflow) if you use the [ACR path](#5-acr-and-github-actions-differences-only)

Copy the example files from this directory into that repo:

- [Dockerfile.example](Dockerfile.example) → `Dockerfile`
- [deploy.yml.example](deploy.yml.example) → `.github/workflows/deploy.yml`
- [scripts/keyvault-uri.ps1.example](scripts/keyvault-uri.ps1.example) → `scripts/keyvault-uri.ps1` (optional)
- [scripts/set-keyvault-secret-from-file.ps1.example](scripts/set-keyvault-secret-from-file.ps1.example) → `scripts/set-keyvault-secret-from-file.ps1` (optional)

## 1. Azure CLI setup

```powershell
$SUBSCRIPTION = "<your-subscription-id-or-name>"
$LOCATION = "eastus"
$RESOURCE_GROUP = "thaum-rg"
$ENVIRONMENT = "thaum-env"

az account set --subscription $SUBSCRIPTION
az upgrade
az extension add --name containerapp --upgrade --allow-preview true
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az group create --name $RESOURCE_GROUP --location $LOCATION

az containerapp env create `
  --name $ENVIRONMENT `
  --resource-group $RESOURCE_GROUP `
  --location $LOCATION
```

## 2. Key Vault and user-assigned managed identity (UAMI)

Store production secret values in **Azure Key Vault**, not as plain literals on the Container App. The app will read them at runtime through **Key Vault references** (`keyvaultref:`) as in [Manage secrets](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets?tabs=azure-cli).

**Important:** Key Vault references on `az containerapp create` require a **user-assigned** managed identity on the app—the system-assigned identity is not available until after the app exists ([Microsoft Learn note](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets?tabs=azure-cli)). That is one reason this guide uses a **split** flow: create the app (or a placeholder revision), attach the UAMI, define app secrets with `az containerapp secret set`, then `az containerapp update` for image, ports, mounts, and registry settings. `secret set` is also more reliable across CLI versions than `--secrets` on `create` / `update`.

### 2.1 Key Vault and secret values

Register the **Microsoft.KeyVault** resource provider namespace for your subscription if it is not already **Registered**; otherwise `az keyvault create` can fail with an error that the subscription is not registered for that namespace. See [Azure resource providers and types](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/resource-providers-and-types).

```powershell
az provider register --namespace Microsoft.KeyVault
# Optional: wait until this prints Registered (can take a minute)
az provider show --namespace Microsoft.KeyVault --query registrationState -o tsv
```

Create a vault, then ensure **you** (or whichever principal runs the CLI) can **write** secrets. New vaults use **Azure role-based access control** for the data plane by default; without a write role, `az keyvault secret set` (and [scripts/set-keyvault-secret-from-file.ps1.example](scripts/set-keyvault-secret-from-file.ps1.example)) fail with permission errors.

This is **separate from [§2.2](#22-user-assigned-managed-identity-uami-and-key-vault-read-access):** the UAMI only needs **`Key Vault Secrets User`** (read secrets at runtime). Whoever **uploads** secret values needs a role that allows **setting** secrets—for example **`Key Vault Secrets Officer`**, or **`Key Vault Administrator`** if your organization assigns that instead. See [Key Vault and Azure RBAC](https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-guide) and [Azure built-in roles](https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles#security).

Example: grant **your** signed-in user read/write on secrets at the vault scope (same pattern as §2.2’s `--assignee-object-id` for the UAMI, but with your Entra **object ID** and **`User`**):

```powershell
$VAULT_NAME = "thaum-kv-<unique>"
az keyvault create --name $VAULT_NAME --resource-group $RESOURCE_GROUP --location $LOCATION

$KV_ID = az keyvault show --name $VAULT_NAME --resource-group $RESOURCE_GROUP --query id -o tsv

$MY_OBJECT_ID = az ad signed-in-user show --query id -o tsv
az role assignment create `
  --role "Key Vault Secrets Officer" `
  --assignee-object-id $MY_OBJECT_ID `
  --assignee-principal-type User `
  --scope $KV_ID

# Write each secret from a file (avoids secrets on the command line); delete the file afterward if needed
az keyvault secret set --vault-name $VAULT_NAME --name webex-token-database --file .\webex-token-database.txt
```

For another user’s object ID: `az ad user show --id someone@example.com --query id -o tsv`. For a **service principal** used in CI or automation, use that principal’s **object ID** in Entra ID and **`--assignee-principal-type ServicePrincipal`**.

Use one Key Vault secret name per credential you will surface to Thaum; names should match the Container Apps secret names you will use in [§4](#4-app-secrets-keyvaultref-and-file-mount-happy-path) and `secret:<name>` in `thaum.toml` (see [sample.thaum.toml](../../../../sample.thaum.toml)).

### 2.2 User-assigned managed identity (UAMI) and Key Vault read access

A **user-assigned managed identity (UAMI)** is an Azure AD identity you create as its own resource, then **attach** to the Container App. Container Apps uses that identity as **`identityref`** when resolving **`keyvaultref:`** so the app can read secret values from Key Vault at runtime without storing vault credentials in the app.

Create the UAMI and grant it **`Key Vault Secrets User`** on the vault (read-only for secret values). **`$UAMI_ID`** is the identity’s **resource ID** (full ARM id string); you need it for `identityref` in [§4](#4-app-secrets-keyvaultref-and-file-mount-happy-path) and for `az containerapp identity assign --user-assigned $UAMI_ID` after the app exists.

```powershell
$UAMI_NAME = "thaum-aca-secrets"
$UAMI_ID = az identity create --name $UAMI_NAME --resource-group $RESOURCE_GROUP --location $LOCATION --query id -o tsv
$KV_ID = az keyvault show --name $VAULT_NAME --resource-group $RESOURCE_GROUP --query id -o tsv

$UAMI_PRINCIPAL = az identity show --ids $UAMI_ID --query principalId -o tsv
az role assignment create `
  --role "Key Vault Secrets User" `
  --assignee-object-id $UAMI_PRINCIPAL `
  --assignee-principal-type ServicePrincipal `
  --scope $KV_ID
```

### 2.3 Key Vault secret URI for `keyvaultref`

For each secret, the URI passed to `keyvaultref` is either:

- `https://<vault>.vault.azure.net/secrets/<name>` (latest version), or
- `https://<vault>.vault.azure.net/secrets/<name>/<version-id>` (pinned version)

You can print the vault base URI with [scripts/keyvault-uri.ps1.example](scripts/keyvault-uri.ps1.example) and append `/secrets/<name>` (use a lowercase **kebab-case** `<name>` that satisfies Key Vault and ACA naming rules in the intro).

## 3. Container App + GHCR image

### 3.1 Public image from GHCR

If your organization pulls **public** images from GHCR without authentication, create the app with `--image` pointing at a pinned tag (see upstream [README.md](../../../../README.md)).

```powershell
$APP_NAME = "thaum-app"
$IMAGE = "ghcr.io/gemstone-software-dev/thaum:<version-tag>"

az containerapp create `
  --name $APP_NAME `
  --resource-group $RESOURCE_GROUP `
  --environment $ENVIRONMENT `
  --image $IMAGE `
  --ingress external `
  --target-port 5165
```

If you will wire **Key Vault–backed secrets** in [§4](#4-app-secrets-keyvaultref-and-file-mount-happy-path), attach the UAMI from [§2.2](#22-user-assigned-managed-identity-uami-and-key-vault-read-access) **after** the app exists (before `az containerapp secret set`):

```powershell
az containerapp identity assign `
  --name $APP_NAME `
  --resource-group $RESOURCE_GROUP `
  --user-assigned $UAMI_ID
```

### 3.2 Private GHCR image (bootstrap)

You cannot pull a **private** `ghcr.io/...` image until the Container App has **registry credentials**. **`keyvaultref`** also requires the **UAMI** from [§2.2](#22-user-assigned-managed-identity-uami-and-key-vault-read-access) to be **attached** to the app before secret references resolve. Use a **small public placeholder** image first, then complete [§4](#4-app-secrets-keyvaultref-and-file-mount-happy-path), then a single **`az containerapp update`** that sets GHCR credentials, the real Thaum **image**, port **5165**, and the same mount / `THAUM_CREDS_DIR` flags as in §4.

Recommended order (aligns with [Container Apps registries](https://learn.microsoft.com/en-us/azure/container-apps/containers#container-registries) and [Manage secrets](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets?tabs=azure-cli)):

1. Complete [§1](#1-azure-cli-setup) and [§2](#2-key-vault-and-user-assigned-managed-identity-uami) so **`$UAMI_ID`**, **`$VAULT_NAME`**, and vault secret values exist.
2. **Create the Container App** with a **public** image that listens on a known port (not Thaum yet). Example — Azure’s sample listens on **80**:

   ```powershell
   $APP_NAME = "thaum-app"
   $PLACEHOLDER = "mcr.microsoft.com/azuredocs/aci-helloworld:latest"

   az containerapp create `
     --name $APP_NAME `
     --resource-group $RESOURCE_GROUP `
     --environment $ENVIRONMENT `
     --image $PLACEHOLDER `
     --ingress external `
     --target-port 80
   ```

3. **Attach the UAMI** to the app (`$UAMI_ID` is from [§2.2](#22-user-assigned-managed-identity-uami-and-key-vault-read-access)):

   ```powershell
   az containerapp identity assign `
     --name $APP_NAME `
     --resource-group $RESOURCE_GROUP `
     --user-assigned $UAMI_ID
   ```

4. **Define app secrets and mount** — follow [§4](#4-app-secrets-keyvaultref-and-file-mount-happy-path) (`az containerapp secret set`, then `az containerapp update` with **`--secret-volume-mount`** and **`THAUM_CREDS_DIR`**). For the first `update` you can keep the **placeholder** image and port **80** if you only want secrets in place first; otherwise combine with step 5 in one `update`.

5. **Point the app at Thaum + GHCR** — one **`az containerapp update`** with **`--registry-server ghcr.io`**, **`--registry-username`** / **`--registry-password`**, **`--image`** (your private image, e.g. `ghcr.io/<org>/<repo>:<tag>`), **`--target-port 5165`**, and the same **`--secret-volume-mount`** / **`--set-env-vars`** for `THAUM_CREDS_DIR` as in §4. Use a [classic PAT or fine-grained token](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry) with `read:packages`; username is often your GitHub username and password the PAT.

Until the final image and port **5165** are applied, probes may target the wrong port or image; that is expected for the placeholder revision.

If the image is **private** but you already completed the bootstrap, you only need registry flags when adding or changing private registry images.

## 4. App secrets: keyvaultref and file mount (happy path)

Avoid putting production secret values in Container Apps as long-lived literals. After vault secrets exist and the app has **`$UAMI_ID`** attached, define **application-level** secrets that reference Key Vault using **`az containerapp secret set`** ([reference](https://learn.microsoft.com/en-us/cli/azure/containerapp/secret?view=azure-cli-latest#az-containerapp-secret-set)). Prefer **`secret set`** over relying on **`--secrets`** on **`az containerapp create`** or **`update`**, which can vary by CLI/extension build—run **`az containerapp update -h`** if you want to confirm whether **`--secrets`** is available.

**`--secrets` on `secret set`:** one parameter whose value is **space-separated** entries. Each entry is either `Name=literalValue` or **`Name=keyvaultref:<vault-uri>,identityref:<user-assigned-resource-id>`** (commas **inside** that value pair). Multiple Key Vault–backed secrets = multiple space-separated pairs, for example: `--secrets "botA=keyvaultref:...,identityref:$UAMI_ID" "botB=keyvaultref:...,identityref:$UAMI_ID"`. In PowerShell, quote each `Name=...` pair that contains commas so the shell does not split on them.

Example — define one Key Vault–backed app secret (repeat pairs for each token / secret file):

```powershell
$SECRET_URI_DB = "https://$VAULT_NAME.vault.azure.net/secrets/webex-token-database"

az containerapp secret set `
  --name $APP_NAME `
  --resource-group $RESOURCE_GROUP `
  --secrets "webex-token-database=keyvaultref:$SECRET_URI_DB,identityref:$UAMI_ID"
```

> **File-mounted secrets (this walkthrough)**  
> The next command uses **`--secret-volume-mount "/run/secrets"`** so each app secret appears as a **file** under `/run/secrets`, with filenames equal to the **Container Apps secret names** (lowercase, ≤20 characters). Thaum reads those via **`secret:<name>`** in `thaum.toml`. If you prefer **environment variables** wired with **`secretref:`** instead of files, skip the volume mount and use **`env:VAR`** in TOML; see [File-mounted secrets vs environment variable secrets](#file-mounted-secrets-vs-environment-variable-secrets) below for the full comparison and examples.

Thaum runs as user `thaum`. Orchestrator-mounted secret files are often root-readable only; set **`THAUM_CREDS_DIR`** so [docker/entrypoint.sh](../../../../docker/entrypoint.sh) copies `/run/secrets` into a tmpfs directory the app user can read.

**Caveat:** If you need **only a subset** of secrets mounted or **custom filenames** inside the volume, Microsoft documents using **YAML** (`--yaml`) instead of `--secret-volume-mount` ([Manage secrets](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets?tabs=azure-cli#mounting-secrets-in-a-volume)).

Apply mount, env, image, and ports (adjust **`$IMAGE`**; add registry flags for private GHCR as in [§3.2](#32-private-ghcr-image-bootstrap)):

```powershell
$IMAGE = "ghcr.io/gemstone-software-dev/thaum:<version-tag>"

az containerapp update `
  --name $APP_NAME `
  --resource-group $RESOURCE_GROUP `
  --image $IMAGE `
  --target-port 5165 `
  --secret-volume-mount "/run/secrets" `
  --set-env-vars "THAUM_CREDS_DIR=/tmp/thaum-creds"
```

Private GHCR on the same revision (combine with the flags above; store the PAT securely and do not commit it):

```powershell
$IMAGE = "ghcr.io/<org>/<repo>:<tag>"

az containerapp update `
  --name $APP_NAME `
  --resource-group $RESOURCE_GROUP `
  --image $IMAGE `
  --registry-server ghcr.io `
  --registry-username "<github-username>" `
  --registry-password "<github-pat-with-read-packages>" `
  --target-port 5165 `
  --secret-volume-mount "/run/secrets" `
  --set-env-vars "THAUM_CREDS_DIR=/tmp/thaum-creds"
```

If your CLI supports it, you can sometimes pass **`--user-assigned`**, **`--secrets`**, **`--secret-volume-mount`**, and **`--set-env-vars`** together on **`az containerapp create`**; the sequence above avoids depending on that.

In **`thaum.toml`**, use names that match the app secret / file basename, for example **`secret:webex-token-database`**, so `resolve_secret` reads the file staged under **`CREDENTIALS_DIRECTORY`**.

### File-mounted secrets vs environment variable secrets

**File mount (what §4 walked through)**  
[`--secret-volume-mount`](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets?tabs=azure-cli#mounting-secrets-in-a-volume) exposes **all** application-level secrets as files under the mount path (here **`/run/secrets`**). Each file name equals the **Container Apps secret name**. In TOML use **`secret:<name>`** with the same `<name>`. Set **`THAUM_CREDS_DIR`** (as in the official image) so the entrypoint can copy those files into a directory readable by user **`thaum`**. This keeps sensitive values out of the process environment and matches systemd-style **`secret:`** usage elsewhere in the repo.

**Environment variables instead**  
If you **omit** `--secret-volume-mount`, secrets do **not** automatically become environment variables. You bind each app secret to an env var on the revision with **`--set-env-vars "VARNAME=secretref:app-secret-name"`** ([referencing secrets in environment variables](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets?tabs=azure-cli#referencing-secrets-in-environment-variables)). **`VARNAME`** is whatever you choose (for example **`WEBEX_TOKEN_DATABASE`**); Azure does **not** auto-convert kebab-case secret names to SCREAMING_SNAKE_CASE. In **`thaum.toml`** use **`env:VARNAME`** with the **exact** variable name you configured.

**Tradeoffs**  
File mounts: fewer env vars; values live in files under the mount (and staged copy); aligns with **`secret:`** and the entrypoint. Env + **`secretref`**: explicit per-secret mapping; some teams prefer exposing configuration as env vars; values appear in the container’s environment (anything that can dump the environment can see names and values). Pick one style per secret and stay consistent in TOML (`secret:` vs **`env:`**).

## 5. ACR and GitHub Actions (differences only)

The steps above are the same **Key Vault + UAMI + app secrets + mount** story ([§2](#2-key-vault-and-user-assigned-managed-identity-uami), [§4](#4-app-secrets-keyvaultref-and-file-mount-happy-path)). For **Azure Container Registry** instead of GHCR:

- **Registry:** Create an ACR (name globally unique, alphanumeric), for example **`az acr create --resource-group $RESOURCE_GROUP --name <name> --sku Basic --admin-enabled true`**.
- **First image:** Either push from CI first and create the app with **`yourregistry.azurecr.io/<repo>:<tag>`**, or use the same **placeholder → attach UAMI → §4 → update image** pattern as [§3.2](#32-private-ghcr-image-bootstrap) until an image exists (see [deploy.yml.example](deploy.yml.example)).
- **Auth to pull:** Use ACR’s recommended auth (managed identity, admin user, or token) per your org; wire **`--registry-server`** / credentials on **`az containerapp update`** or **`az containerapp registry set`** the same way you would for GHCR.
- **CI:** Copy [deploy.yml.example](deploy.yml.example) to `.github/workflows/deploy.yml`, set variables (`ACR_LOGIN_SERVER`, `IMAGE_NAME`, `AZURE_RESOURCE_GROUP`, `AZURE_CONTAINERAPP_NAME`), and push. Each run builds, schema-checks, pushes to ACR, and updates the app image—the **ACR-remote** tutorial flow ([link](https://learn.microsoft.com/en-us/azure/container-apps/tutorial-code-to-cloud?tabs=bash%2Ccsharp&pivots=acr-remote)).

The workflow builds and pushes the **image** only; **application secrets** stay in Key Vault and use `keyvaultref` as in §4.

## Health checks

Thaum exposes:

- `GET /health` — process liveness
- `GET /ready` — database readiness (`SELECT 1`)

Configure Container Apps probes to hit `/ready` (or `/health`) on port **5165**.

## Configuration file

1. Start from [systemd/thaum.conf.example](../../../systemd/thaum.conf.example).
2. Set **`[server].base_url`** to your Container App’s public URL, **or** omit `base_url` and set **`THAUM_BASE_URL`** at runtime (env overrides TOML when both are set).
3. Save it in your deploy repo as **`thaum.toml`**. [Dockerfile.example](Dockerfile.example) copies it to **`/etc/thaum/thaum.toml`**.

Keep sensitive values out of Git: use **`secret:<key>`** with the file-mount flow in [§4](#4-app-secrets-keyvaultref-and-file-mount-happy-path), or **`env:VAR`** if you chose the **`secretref:`** style in [File-mounted secrets vs environment variable secrets](#file-mounted-secrets-vs-environment-variable-secrets) (not inline tokens in `az containerapp secret set` for production).

### `THAUM_BASE_URL` in CI

Pipelines often set **`THAUM_BASE_URL`** so the public URL does not live in Git; it **overrides** `[server].base_url` when both are set. **`--schema-check`** in `thaum_config_check.py` may rely on **`THAUM_BASE_URL`** when `base_url` is omitted from TOML; see that script’s epilog in the main repo.

## Dockerfile (deploy repo)

Use [Dockerfile.example](Dockerfile.example):

- **`FROM`** a **pinned** upstream image (tag or digest), not only `:latest`.
- **`COPY`** your `thaum.toml` to `/etc/thaum/thaum.toml`.
- For **external Postgres**, set **`THAUM_EXTERNAL_DB=true`** and supply **`db_url`** (and secrets via Key Vault as in §4). See [ARCHITECTURE.md](../../../../docs/ARCHITECTURE.md).

## GitHub Actions

Copy [deploy.yml.example](deploy.yml.example) to `.github/workflows/deploy.yml`. The workflow builds and pushes the **image** only; **application secrets** stay in Key Vault and are wired with `keyvaultref` as in [§4](#4-app-secrets-keyvaultref-and-file-mount-happy-path) (not stored in GitHub Secrets for Thaum tokens unless you choose that separately).

- **`--schema-check`**: safe in CI without resolving secrets or hitting the database.
- **`--test-config`**: full validation + DB ping; run only where secrets and DB exist.

## Optional: external managed Postgres

1. Create a managed Postgres instance and a database/user for Thaum.
2. Set Container Apps environment variable **`THAUM_EXTERNAL_DB=true`**.
3. In your TOML, set **`[server.database].db_url`** (reference credentials via Key Vault–mounted files and **`secret:`** / **`env:`** as in [File-mounted secrets vs environment variable secrets](#file-mounted-secrets-vs-environment-variable-secrets); do not commit passwords).
4. Redeploy. The container runs **Gunicorn only** (no bundled Postgres); see [Dockerfile](../../../../Dockerfile) and [docker/entrypoint.sh](../../../../docker/entrypoint.sh).

## Files in this directory

| File | Purpose |
|------|---------|
| [Dockerfile.example](Dockerfile.example) | `FROM` upstream Thaum image + `COPY` `thaum.toml` → `/etc/thaum/thaum.toml` |
| [deploy.yml.example](deploy.yml.example) | Build → schema-check → push to ACR → update Container App image |
| [scripts/keyvault-uri.ps1.example](scripts/keyvault-uri.ps1.example) | Print Key Vault `vaultUri` (build `keyvaultref` secret URIs) |
| [scripts/set-keyvault-secret-from-file.ps1.example](scripts/set-keyvault-secret-from-file.ps1.example) | Set a vault secret from a file via `az keyvault secret set --file` |
| [scripts/keyvault-uri.bat.example](scripts/keyvault-uri.bat.example) | Invoke the PowerShell URI script from cmd |
