# Thaum on Kubernetes

Run Thaum on **any** conformant Kubernetes cluster (on-premises, EKS, GKE, AKS, or other). This guide targets **production-style** expectations: **multiple replicas**, **external PostgreSQL**, and **secrets** wired through the cluster—**not** the same “single cheap instance” story as [Azure App Service + GitHub Actions](../cloud/azure/github/README.md).

- Main quickstart index: [QUICKSTART.md](../QUICKSTART.md)
- Example TOML (trim for ConfigMaps / secrets): [systemd/thaum.conf.example](../systemd/thaum.conf.example)
- Container images and tags: [README.md](../../README.md) (*Container images (CI)*)
- Architecture (election, bootstrap): [ARCHITECTURE.md](../../docs/ARCHITECTURE.md)

## Scope

| Expectation | Notes |
|---------------|--------|
| **Replicas** | You may run **more than one** pod; Thaum uses **[server.election]** so only one leader performs webhook registration and similar work (see architecture doc). Do not scale out without understanding election and shared DB semantics. |
| **Database** | **Bundled PostgreSQL** inside the stock image is a poor fit for HA on Kubernetes (storage, restarts). **Prefer an external Postgres** reachable from the cluster. |
| **Ingress / TLS** | Expose the Service with an Ingress (or Gateway API) and terminate TLS at the edge; set **`[server].base_url`** or **`THAUM_BASE_URL`** to the public HTTPS URL. **`THAUM_BASE_URL` overrides `base_url`** when both are set (see below). |

## Container contract

- **Port**: Gunicorn listens on **5165** by default (`GUNICORN_BIND` / image default).
- **Process model**: For external DB, set **`THAUM_EXTERNAL_DB=true`** so the entrypoint runs **gunicorn only** (no bundled Postgres). See [Dockerfile](../../Dockerfile) and [docker/entrypoint.sh](../../docker/entrypoint.sh).
- **Probes**: Use HTTP **`/health`** (liveness) and **`/ready`** (readiness / DB); see root [README.md](../../README.md).

## Configuration and secrets

- Mount **`thaum.conf`** at **`/etc/thaum/thaum.conf`** (or set **`THAUM_CONFIG_FILE`**). Build the file from [systemd/thaum.conf.example](../systemd/thaum.conf.example); use **`env:`** and **`file:`** references so secrets are not baked into ConfigMaps.
- **`base_url`**: Set **`[server].base_url`** in TOML, **or** omit it and set **`THAUM_BASE_URL`** in the environment ( **`THAUM_BASE_URL` wins** when both are set). There is **no** Kubernetes-specific auto-detection in [`thaum.types._resolve_base_url`](../../thaum/types.py) (unlike some cloud PaaS env vars). For Ingress hosts, **`THAUM_BASE_URL=https://<your-hostname>`** is a common choice.

## Database: external Postgres (recommended)

Point **`[server.database].db_url`** at a PostgreSQL instance **outside** the Thaum pod—managed cloud RDS–class services, a shared cluster, or Postgres run by your platform team.

- Supply credentials via **Kubernetes Secrets** and reference them from TOML using **`env:VAR_NAME`** or **`file:/path`** to mounted secret files.
- Set **`THAUM_EXTERNAL_DB=true`** on the Deployment.

## Postgres running inside the cluster

Running **highly available** PostgreSQL **on** Kubernetes (replication, failover, backups, upgrades) is a **large** operational topic. It typically means using a **database operator**, not a bare `StatefulSet` tutorial.

### More information

- **[CloudNativePG documentation](https://cloudnative-pg.io/documentation/current/)** — a common choice for PostgreSQL on Kubernetes (CNCF Sandbox). Start with architecture and the **Cluster** CRD, then read **[Storage](https://cloudnative-pg.io/documentation/current/storage/)** before choosing storage classes and sizing.
- Treat in-cluster Postgres as **optional** and **team-owned**: backups, DR, and upgrades are your responsibility.

Thaum itself does not require a specific operator; any Postgres reachable with a SQLAlchemy URL is fine.

## Example manifests

Copy the **`.example`** files from [`examples/`](examples/) into your own repo or overlay, **remove the `.example` suffix**, and replace placeholders (`<IMAGE>`, hostnames, Secret names). They are **illustrations only**—not a complete production chart.

| File | Purpose |
|------|---------|
| [examples/deployment.yaml.example](examples/deployment.yaml.example) | Deployment with `THAUM_EXTERNAL_DB`, config volume, probe paths |
| [examples/service.yaml.example](examples/service.yaml.example) | ClusterIP on port 5165 |
| [examples/ingress.yaml.example](examples/ingress.yaml.example) | Ingress with TLS and host placeholders |
| [examples/configmap.yaml.example](examples/configmap.yaml.example) | Stub ConfigMap for `thaum.conf` (replace body with your real TOML) |

Apply order: Namespace (if used) → Secrets → ConfigMap → Deployment → Service → Ingress.

## Verification

- CI-style validation without live secrets: **`thaum_config_check.py --schema-check`** (see [scripts/python/thaum_config_check.py](../../scripts/python/thaum_config_check.py)).
- Full check with DB: **`--test-config`** where secrets and network access exist (often a staging cluster or local `kubectl port-forward` to Postgres).
