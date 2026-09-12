#!/usr/bin/env bash

set -euo pipefail

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

require_value LEADTRACE_RESTORE_ROOT
require_value LEADTRACE_DATABASE_METADATA
require_value LEADTRACE_ASSET_METADATA
require_value LEADTRACE_RESTORE_DATABASE_URL
require_value LEADTRACE_AGE_IDENTITY_FILE
require_value LEADTRACE_DRILL_BASE_URL
require_value LEADTRACE_DRILL_USERNAME
require_value LEADTRACE_DRILL_PASSWORD

RESTORE_ROOT_RAW="${LEADTRACE_RESTORE_ROOT}"
[[ "${RESTORE_ROOT_RAW}" == /* && "${RESTORE_ROOT_RAW}" != "/" ]] \
  || fail "restore root must be a new absolute dedicated directory"
[[ ! -e "${RESTORE_ROOT_RAW}" ]] || fail "restore root already exists; choose a new directory"
RESTORE_PARENT="$(dirname -- "${RESTORE_ROOT_RAW}")"
[[ -d "${RESTORE_PARENT}" ]] || fail "restore root parent must exist"
RESTORE_PARENT="$(realpath -e -- "${RESTORE_PARENT}")"
RESTORE_ROOT="${RESTORE_PARENT}/$(basename -- "${RESTORE_ROOT_RAW}")"
mkdir -- "${RESTORE_ROOT}"
mkdir -- "${RESTORE_ROOT}/assets"

for required_file in "${LEADTRACE_DATABASE_METADATA}" "${LEADTRACE_ASSET_METADATA}" "${LEADTRACE_AGE_IDENTITY_FILE}"; do
  [[ -f "${required_file}" && ! -L "${required_file}" ]] \
    || fail "restore input must be a regular file: $(basename -- "${required_file}")"
done

python "${BACKUP_DIRECTORY}/verify_backup.py" "${LEADTRACE_DATABASE_METADATA}" >/dev/null \
  || fail "database backup metadata verification failed"
python "${BACKUP_DIRECTORY}/verify_backup.py" "${LEADTRACE_ASSET_METADATA}" >/dev/null \
  || fail "asset backup metadata verification failed"

artifact_path() {
  local metadata_path="$1"
  local artifact_name="$2"
  python - "${metadata_path}" "${artifact_name}" <<'PY'
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
ASSET_ARCHIVE="$(artifact_path "${LEADTRACE_ASSET_METADATA}" asset_archive)"

command -v age >/dev/null 2>&1 || fail "age is required"
command -v pg_restore >/dev/null 2>&1 || fail "pg_restore is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"

age --decrypt --identity "${LEADTRACE_AGE_IDENTITY_FILE}" \
  --output "${RESTORE_ROOT}/database.dump" "${DB_DUMP}"
pg_restore --no-owner --no-privileges \
  --dbname="${LEADTRACE_RESTORE_DATABASE_URL}" "${RESTORE_ROOT}/database.dump"

age --decrypt --identity "${LEADTRACE_AGE_IDENTITY_FILE}" \
  --output "${RESTORE_ROOT}/assets.tar" "${ASSET_ARCHIVE}"
tar --extract --file="${RESTORE_ROOT}/assets.tar" \
  --directory="${RESTORE_ROOT}/assets" --no-same-owner --no-same-permissions

if [[ "${LEADTRACE_RUN_MIGRATIONS:-0}" == "1" ]]; then
  require_value LEADTRACE_BACKEND_DIRECTORY
  require_value LEADTRACE_ALEMBIC_CONFIG
  (
    cd -- "$(realpath -e -- "${LEADTRACE_BACKEND_DIRECTORY}")"
    LEADTRACE_DATABASE_URL="${LEADTRACE_RESTORE_DATABASE_URL}" \
      python -m alembic -c "${LEADTRACE_ALEMBIC_CONFIG}" upgrade head
  )
fi

VERIFY_ARGUMENTS=(
  --asset-manifest "${ASSET_MANIFEST}"
  --restored-asset-root "${RESTORE_ROOT}/assets"
  --database-url "${LEADTRACE_RESTORE_DATABASE_URL}"
  --base-url "${LEADTRACE_DRILL_BASE_URL}"
  --report "${RESTORE_ROOT}/restore-report.json"
)
if [[ -n "${LEADTRACE_EXPECTED_COUNTS:-}" ]]; then
  [[ -f "${LEADTRACE_EXPECTED_COUNTS}" && ! -L "${LEADTRACE_EXPECTED_COUNTS}" ]] \
    || fail "expected counts must be a regular file"
  VERIFY_ARGUMENTS+=(--expected-counts "${LEADTRACE_EXPECTED_COUNTS}")
fi
python "${SCRIPT_DIRECTORY}/verify_restored_system.py" "${VERIFY_ARGUMENTS[@]}"

rm -f -- "${RESTORE_ROOT}/database.dump" "${RESTORE_ROOT}/assets.tar"
printf 'restore_root=%s report=restore-report.json\n' "$(basename -- "${RESTORE_ROOT}")"
