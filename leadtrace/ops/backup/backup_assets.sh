#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "${SCRIPT_DIRECTORY}/common.sh"

validate_backup_environment
require_value LEADTRACE_ASSET_ROOT
require_value LEADTRACE_ASSET_ALLOWED_PARENT
ASSET_ROOT="$(resolve_directory_below \
  'asset root' "${LEADTRACE_ASSET_ROOT}" "${LEADTRACE_ASSET_ALLOWED_PARENT}")"
reject_path_overlap "${ASSET_ROOT}" "${BACKUP_DESTINATION}"
command -v age >/dev/null 2>&1 || fail "age is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"
command -v cp >/dev/null 2>&1 || fail "cp is required"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"

if [[ -n "$(find "${ASSET_ROOT}" -type l -print -quit)" ]]; then
  fail "asset root must not contain symbolic links"
fi

new_staging_directory assets
trap cleanup_staging_directory EXIT
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
MANIFEST="${STAGING_DIRECTORY}/assets.manifest.json"
PLAIN_ARCHIVE="${STAGING_DIRECTORY}/assets.tar"
ENCRYPTED_ARCHIVE="${STAGING_DIRECTORY}/assets.tar.age"
CAPTURE_ROOT="${STAGING_DIRECTORY}/asset-snapshot"
MODE="${LEADTRACE_ASSET_BACKUP_MODE:-full}"
[[ "${MODE}" == "full" || "${MODE}" == "incremental" ]] || fail "asset backup mode must be full or incremental"
SNAPSHOT="${STAGING_DIRECTORY}/tar.snapshot"
PARENT_BACKUP_ID=""
CHAIN_POSITION=0
if [[ "${MODE}" == "incremental" ]]; then
  PARENT_METADATA_INPUT="${LEADTRACE_ASSET_PARENT_METADATA:-${BACKUP_DESTINATION}/.leadtrace-latest-assets/backup-metadata.json}"
  PARENT_METADATA="$(realpath -e -- "${PARENT_METADATA_INPUT}")" \
    || fail "incremental asset backup requires a verified parent backup"
  [[ "${PARENT_METADATA}" == "${BACKUP_DESTINATION}/"*/backup-metadata.json ]] \
    || fail "incremental parent metadata must be a finalized backup in this destination"
  CHAIN_INFO="$(PYTHONPATH="${SCRIPT_DIRECTORY}/../../.." python \
    "${SCRIPT_DIRECTORY}/asset_chain.py" --metadata "${PARENT_METADATA}" --next)"
  IFS='|' read -r PARENT_BACKUP_ID CHAIN_POSITION PARENT_SNAPSHOT <<<"${CHAIN_INFO}"
  cp -- "${PARENT_SNAPSHOT}" "${SNAPSHOT}"
fi

mkdir --mode=0700 -- "${CAPTURE_ROOT}"
cp -a --reflink=auto -- "${ASSET_ROOT}/." "${CAPTURE_ROOT}/"

python - "${CAPTURE_ROOT}" "${MANIFEST}" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=True)
output = Path(sys.argv[2]).resolve(strict=False)
rows = []
for path in sorted(root.rglob("*")):
    if path.is_symlink() or not path.is_file():
        continue
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    rows.append({
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    })
payload = {
    "schema_version": 1,
    "asset_root_name": root.name,
    "file_count": len(rows),
    "total_bytes": sum(row["size_bytes"] for row in rows),
    "files": rows,
}
output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

tar --listed-incremental="${SNAPSHOT}" --create --file="${PLAIN_ARCHIVE}" \
  --directory="${CAPTURE_ROOT}" .
rm -rf -- "${CAPTURE_ROOT}"
age --encrypt -r "${LEADTRACE_ENCRYPTION_RECIPIENT}" \
  -o "${ENCRYPTED_ARCHIVE}" "${PLAIN_ARCHIVE}"
rm -f -- "${PLAIN_ARCHIVE}"

python "${SCRIPT_DIRECTORY}/write_metadata.py" \
  --output "${STAGING_DIRECTORY}/backup-metadata.json" \
  --backup-id "${BACKUP_ID}" \
  --backup-scope assets \
  --started-at "${STARTED_AT}" \
  --destination-id "${LEADTRACE_DESTINATION_ID}" \
  --destination-kind "${LEADTRACE_DESTINATION_KIND:-separate_disk}" \
  --encryption-recipient "${LEADTRACE_ENCRYPTION_FINGERPRINT}" \
  --application-version "${LEADTRACE_APPLICATION_VERSION}" \
  --schema-version "${LEADTRACE_SCHEMA_VERSION}" \
  --release-version "${LEADTRACE_RELEASE_VERSION}" \
  --asset-mode "${MODE}" \
  --chain-position "${CHAIN_POSITION}" \
  ${PARENT_BACKUP_ID:+--parent-backup-id "${PARENT_BACKUP_ID}"} \
  --artifact "asset_manifest=${MANIFEST}" \
  --artifact "asset_archive=${ENCRYPTED_ARCHIVE}" \
  --artifact "asset_snapshot=${SNAPSHOT}"
python "${SCRIPT_DIRECTORY}/verify_backup.py" \
  "${STAGING_DIRECTORY}/backup-metadata.json" >/dev/null

finalize_staging_directory
LATEST_LINK="${BACKUP_DESTINATION}/.leadtrace-latest-assets"
LATEST_TEMP="${BACKUP_DESTINATION}/.leadtrace-latest-assets.${BACKUP_ID}.tmp"
ln -s -- "${BACKUP_ID}" "${LATEST_TEMP}"
mv -Tf -- "${LATEST_TEMP}" "${LATEST_LINK}"
