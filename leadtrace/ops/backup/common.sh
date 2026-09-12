#!/usr/bin/env bash

set -euo pipefail

fail() {
  printf 'leadtrace backup: %s\n' "$1" >&2
  exit 2
}

require_value() {
  local variable_name="$1"
  local value="${!variable_name:-}"
  [[ -n "${value}" ]] || fail "${variable_name} is required"
}

resolve_dedicated_directory() {
  local label="$1"
  local raw_path="$2"

  [[ "${raw_path}" == /* ]] || fail "${label} must be an absolute resolved path"
  [[ "${raw_path}" != "/" ]] || fail "${label} must not be the filesystem root"
  [[ -d "${raw_path}" ]] || fail "${label} must be an existing directory"

  local resolved
  resolved="$(realpath -e -- "${raw_path}")"
  [[ "${resolved}" != "/" ]] || fail "${label} must not resolve to the filesystem root"
  printf '%s\n' "${resolved}"
}

validate_backup_environment() {
  require_value LEADTRACE_BACKUP_DESTINATION
  require_value LEADTRACE_DESTINATION_ID
  require_value LEADTRACE_ENCRYPTION_RECIPIENT
  require_value LEADTRACE_ENCRYPTION_FINGERPRINT
  require_value LEADTRACE_APPLICATION_VERSION
  require_value LEADTRACE_SCHEMA_VERSION
  require_value LEADTRACE_RELEASE_VERSION

  BACKUP_DESTINATION="$(resolve_dedicated_directory \
    'backup destination' "${LEADTRACE_BACKUP_DESTINATION}")"
  export BACKUP_DESTINATION
}

validate_backup_id() {
  BACKUP_ID="${LEADTRACE_BACKUP_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
  [[ "${BACKUP_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] \
    || fail "backup id contains unsupported path characters"
  export BACKUP_ID
}

new_staging_directory() {
  validate_backup_id
  FINAL_DIRECTORY="${BACKUP_DESTINATION}/${BACKUP_ID}"
  [[ ! -e "${FINAL_DIRECTORY}" ]] || fail "backup destination already exists: ${BACKUP_ID}"
  STAGING_DIRECTORY="$(mktemp -d "${BACKUP_DESTINATION}/.leadtrace-${BACKUP_ID}.staging.XXXXXX")"
  export FINAL_DIRECTORY STAGING_DIRECTORY
}

finalize_staging_directory() {
  local metadata_path="${STAGING_DIRECTORY}/backup-metadata.json"
  [[ -f "${metadata_path}" ]] || fail "backup metadata was not created"
  mv -- "${STAGING_DIRECTORY}" "${FINAL_DIRECTORY}"
  trap - EXIT
  printf 'backup_id=%s destination=%s\n' "${BACKUP_ID}" "${FINAL_DIRECTORY}"
}

cleanup_staging_directory() {
  if [[ -n "${STAGING_DIRECTORY:-}" && -d "${STAGING_DIRECTORY}" ]]; then
    rm -rf -- "${STAGING_DIRECTORY}"
  fi
}
