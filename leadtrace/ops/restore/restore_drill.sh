#!/usr/bin/env bash

set -euo pipefail
umask 077

SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BACKUP_DIRECTORY="$(cd -- "${SCRIPT_DIRECTORY}/../backup" && pwd -P)"

fail() {
  printf 'leadtrace restore drill: %s\n' "$1" >&2
  exit 2
}

require_value() {
  local variable_name="$1"
  [[ -n "${!variable_name:-}" ]] || fail "${variable_name} is required"
}

PYTHON_BIN="${LEADTRACE_PYTHON_BIN:-python}"
command -v -- "${PYTHON_BIN}" >/dev/null 2>&1 \
  || fail "configured Python interpreter is not executable"

require_value LEADTRACE_RESTORE_ROOT
require_value LEADTRACE_DATABASE_METADATA
require_value LEADTRACE_ASSET_METADATA
require_value LEADTRACE_RESTORE_DATABASE_URL
require_value LEADTRACE_PRODUCTION_DATABASE_URL
require_value LEADTRACE_RESTORE_DATABASE_ALLOWLIST
require_value LEADTRACE_AGE_IDENTITY_FILE
require_value LEADTRACE_DRILL_BASE_URL
require_value LEADTRACE_DRILL_USERNAME
require_value LEADTRACE_DRILL_PASSWORD
require_value LEADTRACE_EXPECTED_AGGREGATE
require_value LEADTRACE_RESTORE_RTO_SECONDS

DRILL_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

RESTORE_ROOT_RAW="${LEADTRACE_RESTORE_ROOT}"
[[ "${RESTORE_ROOT_RAW}" == /* && "${RESTORE_ROOT_RAW}" != "/" ]] \
  || fail "restore root must be a new absolute dedicated directory"
[[ ! -e "${RESTORE_ROOT_RAW}" ]] || fail "restore root already exists; choose a new directory"
RESTORE_PARENT="$(dirname -- "${RESTORE_ROOT_RAW}")"
[[ -d "${RESTORE_PARENT}" ]] || fail "restore root parent must exist"
RESTORE_PARENT="$(realpath -e -- "${RESTORE_PARENT}")"
RESTORE_ROOT="${RESTORE_PARENT}/$(basename -- "${RESTORE_ROOT_RAW}")"
"${PYTHON_BIN}" "${SCRIPT_DIRECTORY}/validate_restore_target.py" >/dev/null \
  || fail "production database protection or empty drill target check failed"
mkdir -- "${RESTORE_ROOT}"
mkdir -- "${RESTORE_ROOT}/assets"
RESTORE_SUCCEEDED=0

cleanup_restore_plaintext() {
  rm -f -- \
    "${RESTORE_ROOT}/database.dump" \
    "${RESTORE_ROOT}"/assets-*.tar \
    "${RESTORE_ROOT}/asset-chain.list"
  if [[ "${RESTORE_SUCCEEDED}" != "1" ]]; then
    rm -rf -- "${RESTORE_ROOT}/assets"
  fi
}
trap cleanup_restore_plaintext EXIT

for required_file in "${LEADTRACE_DATABASE_METADATA}" "${LEADTRACE_ASSET_METADATA}" "${LEADTRACE_AGE_IDENTITY_FILE}"; do
  [[ -f "${required_file}" && ! -L "${required_file}" ]] \
    || fail "restore input must be a regular file: $(basename -- "${required_file}")"
done

"${PYTHON_BIN}" "${BACKUP_DIRECTORY}/verify_backup.py" "${LEADTRACE_DATABASE_METADATA}" >/dev/null \
  || fail "database backup metadata verification failed"
"${PYTHON_BIN}" "${BACKUP_DIRECTORY}/verify_backup.py" "${LEADTRACE_ASSET_METADATA}" >/dev/null \
  || fail "asset backup metadata verification failed"

artifact_path() {
  local metadata_path="$1"
  local artifact_name="$2"
  "${PYTHON_BIN}" - "${metadata_path}" "${artifact_name}" <<'PY'
import json
import sys
from pathlib import Path

metadata_path = Path(sys.argv[1]).resolve(strict=True)
artifact_name = sys.argv[2]
payload = json.loads(metadata_path.read_text(encoding="utf-8"))
path = Path(payload["artifacts"][artifact_name]["path"])
if path.is_absolute() or ".." in path.parts:
    raise SystemExit("invalid artifact path")
print(metadata_path.parent / path)
PY
}

DB_DUMP="$(artifact_path "${LEADTRACE_DATABASE_METADATA}" database_dump)"
ASSET_MANIFEST="$(artifact_path "${LEADTRACE_ASSET_METADATA}" asset_manifest)"

command -v age >/dev/null 2>&1 || fail "age is required"
command -v pg_restore >/dev/null 2>&1 || fail "pg_restore is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"

age --decrypt --identity "${LEADTRACE_AGE_IDENTITY_FILE}" \
  --output "${RESTORE_ROOT}/database.dump" "${DB_DUMP}"
PG_RESTORE_DATABASE_URL="${LEADTRACE_RESTORE_DATABASE_URL/postgresql+psycopg:/postgresql:}"
pg_restore --no-owner --no-privileges --single-transaction --exit-on-error \
  --dbname="${PG_RESTORE_DATABASE_URL}" "${RESTORE_ROOT}/database.dump"

PYTHONPATH="${SCRIPT_DIRECTORY}/../../.." "${PYTHON_BIN}" \
  "${BACKUP_DIRECTORY}/asset_chain.py" \
  --metadata "${LEADTRACE_ASSET_METADATA}" \
  >"${RESTORE_ROOT}/asset-chain.list"
CHAIN_INDEX=0
while IFS= read -r CHAIN_METADATA; do
  ASSET_ARCHIVE="$(artifact_path "${CHAIN_METADATA}" asset_archive)"
  PLAIN_ASSET_ARCHIVE="${RESTORE_ROOT}/assets-${CHAIN_INDEX}.tar"
  age --decrypt --identity "${LEADTRACE_AGE_IDENTITY_FILE}" \
    --output "${PLAIN_ASSET_ARCHIVE}" "${ASSET_ARCHIVE}"
  tar --extract --listed-incremental=/dev/null \
    --file="${PLAIN_ASSET_ARCHIVE}" \
    --directory="${RESTORE_ROOT}/assets" \
    --no-same-owner --no-same-permissions
  CHAIN_INDEX=$((CHAIN_INDEX + 1))
done <"${RESTORE_ROOT}/asset-chain.list"

if [[ "${LEADTRACE_RUN_MIGRATIONS:-0}" == "1" ]]; then
  require_value LEADTRACE_BACKEND_DIRECTORY
  require_value LEADTRACE_ALEMBIC_CONFIG
  (
    cd -- "$(realpath -e -- "${LEADTRACE_BACKEND_DIRECTORY}")"
    LEADTRACE_DATABASE_URL="${LEADTRACE_RESTORE_DATABASE_URL}" \
      "${PYTHON_BIN}" -m alembic -c "${LEADTRACE_ALEMBIC_CONFIG}" upgrade head
  )
fi

VERIFY_ARGUMENTS=(
  --asset-manifest "${ASSET_MANIFEST}"
  --restored-asset-root "${RESTORE_ROOT}/assets"
  --database-url "${LEADTRACE_RESTORE_DATABASE_URL}"
  --base-url "${LEADTRACE_DRILL_BASE_URL}"
  --expected-aggregate "${LEADTRACE_EXPECTED_AGGREGATE}"
  --database-backup-metadata "${LEADTRACE_DATABASE_METADATA}"
  --asset-backup-metadata "${LEADTRACE_ASSET_METADATA}"
  --started-at "${DRILL_STARTED_AT}"
  --rto-target-seconds "${LEADTRACE_RESTORE_RTO_SECONDS}"
  --report "${RESTORE_ROOT}/restore-report.json"
)
[[ -f "${LEADTRACE_EXPECTED_AGGREGATE}" && ! -L "${LEADTRACE_EXPECTED_AGGREGATE}" ]] \
  || fail "expected aggregate must be a regular file"
"${PYTHON_BIN}" "${SCRIPT_DIRECTORY}/verify_restored_system.py" "${VERIFY_ARGUMENTS[@]}"

RESTORE_SUCCEEDED=1
printf 'restore_root=%s report=restore-report.json\n' "$(basename -- "${RESTORE_ROOT}")"
