#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "${SCRIPT_DIRECTORY}/common.sh"

validate_backup_environment
require_value LEADTRACE_DATABASE_URL

command -v pg_dump >/dev/null 2>&1 || fail "pg_dump is required"
command -v age >/dev/null 2>&1 || fail "age is required"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"

new_staging_directory database
trap cleanup_staging_directory EXIT
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PLAIN_DUMP="${STAGING_DIRECTORY}/database.dump"
ENCRYPTED_DUMP="${STAGING_DIRECTORY}/database.dump.age"

pg_dump --format=custom --no-owner --no-privileges \
  --file="${PLAIN_DUMP}" "${LEADTRACE_DATABASE_URL}"
age --encrypt -r "${LEADTRACE_ENCRYPTION_RECIPIENT}" \
  -o "${ENCRYPTED_DUMP}" "${PLAIN_DUMP}"
rm -f -- "${PLAIN_DUMP}"

python "${SCRIPT_DIRECTORY}/write_metadata.py" \
  --output "${STAGING_DIRECTORY}/backup-metadata.json" \
  --backup-id "${BACKUP_ID}" \
  --backup-scope database \
  --started-at "${STARTED_AT}" \
  --destination-id "${LEADTRACE_DESTINATION_ID}" \
  --destination-kind "${LEADTRACE_DESTINATION_KIND:-separate_disk}" \
  --encryption-recipient "${LEADTRACE_ENCRYPTION_FINGERPRINT}" \
  --application-version "${LEADTRACE_APPLICATION_VERSION}" \
  --schema-version "${LEADTRACE_SCHEMA_VERSION}" \
  --release-version "${LEADTRACE_RELEASE_VERSION}" \
  --artifact "database_dump=${ENCRYPTED_DUMP}"
python "${SCRIPT_DIRECTORY}/verify_backup.py" \
  "${STAGING_DIRECTORY}/backup-metadata.json" >/dev/null

finalize_staging_directory
