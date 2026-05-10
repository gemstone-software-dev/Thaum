#!/usr/bin/env bash
# Interactive helper for systemd encrypted credentials used by Thaum quickstarts.
#
# If you use the container image with bundled PostgreSQL and omit [server.database].db_url
# in thaum.conf, you do not need thaum-db-url — press Enter at that prompt to skip, and
# remove the thaum-db-url line from thaum.service.credentials.conf (see example comments).

set -euo pipefail

CREDSTORE_DIR="${CREDSTORE_DIR:-/etc/credstore.encrypted}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (or use sudo) so credentials can be written to ${CREDSTORE_DIR}."
  exit 1
fi

if ! command -v systemd-creds >/dev/null 2>&1; then
  echo "systemd-creds not found in PATH."
  exit 1
fi

mkdir -p "${CREDSTORE_DIR}"
chmod 0700 "${CREDSTORE_DIR}"

write_credential() {
  local cred_name="$1"
  local prompt="$2"
  local secret_value

  read -r -s -p "${prompt}: " secret_value
  echo

  if [[ -z "${secret_value}" ]]; then
    echo "Credential ${cred_name} was empty; skipping."
    return 1
  fi

  printf '%s' "${secret_value}" | systemd-creds encrypt - "${CREDSTORE_DIR}/${cred_name}" --name="${cred_name}"
  chmod 0600 "${CREDSTORE_DIR}/${cred_name}"
  echo "Saved encrypted credential: ${CREDSTORE_DIR}/${cred_name}"
}

# Optional: skip with empty input (e.g. bundled PostgreSQL with no db_url in config).
write_credential_optional() {
  local cred_name="$1"
  local prompt="$2"
  local secret_value

  read -r -s -p "${prompt}: " secret_value
  echo

  if [[ -z "${secret_value}" ]]; then
    echo "Credential ${cred_name} skipped (empty)."
    return 0
  fi

  printf '%s' "${secret_value}" | systemd-creds encrypt - "${CREDSTORE_DIR}/${cred_name}" --name="${cred_name}"
  chmod 0600 "${CREDSTORE_DIR}/${cred_name}"
  echo "Saved encrypted credential: ${CREDSTORE_DIR}/${cred_name}"
}

echo "Creating encrypted systemd credentials for Thaum."
write_credential_optional "thaum-db-url" "Database URL (bundled PG: postgresql+psycopg://thaum@/thaum?host=/tmp/postgres&client_encoding=utf8; sqlite: sqlite:////var/lib/thaum/thaum.db; or Enter to skip if db_url omitted in config)"
write_credential "thaum-db-passphrase" "Database vault passphrase"
write_credential "atlassian-api-token" "Atlassian API token (Jira + connections; one secret for both)"
write_credential "webex-token-database" "Webex bot token (database bot)"

echo "Done."
