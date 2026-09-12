#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "${SCRIPT_DIRECTORY}/common.sh"

validate_backup_environment
require_value LEADTRACE_ASSET_ROOT
ASSET_ROOT="$(resolve_dedicated_directory 'asset root' "${LEADTRACE_ASSET_ROOT}")"
command -v age >/dev/null 2>&1 || fail "age is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"

new_staging_directory
trap cleanup_staging_directory EXIT
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
MANIFEST="${STAGING_DIRECTORY}/assets.manifest.json"
PLAIN_ARCHIVE="${STAGING_DIRECTORY}/assets.tar"
ENCRYPTED_ARCHIVE="${STAGING_DIRECTORY}/assets.tar.age"
MODE="${LEADTRACE_ASSET_BACKUP_MODE:-full}"
[[ "${MODE}" == "full" || "${MODE}" == "incremental" ]] || fail "asset backup mode must be full or incremental"

python - "${ASSET_ROOT}" "${MANIFEST}" <<'PY'
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

SNAPSHOT="${STAGING_DIRECTORY}/tar.snapshot"
PREVIOUS_SNAPSHOT="${BACKUP_DESTINATION}/.leadtrace-asset-snapshot"
if [[ "${MODE}" == "incremental" && -f "${PREVIOUS_SNAPSHOT}" ]]; then
  cp -- "${PREVIOUS_SNAPSHOT}" "${SNAPSHOT}"
fi
if [[ -f "${SNAPSHOT}" ]]; then
  tar --listed-incremental="${SNAPSHOT}" --create --file="${PLAIN_ARCHIVE}" \
    --directory="${ASSET_ROOT}" .
else
  tar --listed-incremental="${SNAPSHOT}" --create --file="${PLAIN_ARCHIVE}" \
    --directory="${ASSET_ROOT}" .
fi
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
  --artifact "asset_manifest=${MANIFEST}" \
  --artifact "asset_archive=${ENCRYPTED_ARCHIVE}"
python "${SCRIPT_DIRECTORY}/verify_backup.py" \
  "${STAGING_DIRECTORY}/backup-metadata.json" >/dev/null

finalize_staging_directory
if [[ -f "${FINAL_DIRECTORY}/tar.snapshot" ]]; then
  mv -- "${FINAL_DIRECTORY}/tar.snapshot" "${BACKUP_DESTINATION}/.leadtrace-asset-snapshot"
fi
