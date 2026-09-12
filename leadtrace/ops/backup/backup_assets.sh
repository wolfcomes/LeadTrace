#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "${SCRIPT_DIRECTORY}/common.sh"

validate_backup_environment
acquire_backup_lock
require_value LEADTRACE_ASSET_ROOT
require_value LEADTRACE_ASSET_ALLOWED_PARENT
ASSET_ROOT="$(resolve_directory_below \
  'asset root' "${LEADTRACE_ASSET_ROOT}" "${LEADTRACE_ASSET_ALLOWED_PARENT}")"
reject_path_overlap "${ASSET_ROOT}" "${BACKUP_DESTINATION}"
command -v age >/dev/null 2>&1 || fail "age is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"
command -v cp >/dev/null 2>&1 || fail "cp is required"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"

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

python - "${ASSET_ROOT}" "${CAPTURE_ROOT}" "${BACKUP_DESTINATION}" <<'PY'
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path


def overlaps(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


managed_root = Path(sys.argv[1]).resolve(strict=True)
capture_root = Path(sys.argv[2]).resolve(strict=False)
backup_destination = Path(sys.argv[3]).resolve(strict=True)
try:
    raw_source_roots = json.loads(os.environ.get("LEADTRACE_SOURCE_ROOTS", "{}"))
except json.JSONDecodeError as error:
    raise SystemExit("LEADTRACE_SOURCE_ROOTS must be a JSON object") from error
if not isinstance(raw_source_roots, dict):
    raise SystemExit("LEADTRACE_SOURCE_ROOTS must be a JSON object")

roots: list[tuple[str, Path, Path]] = [
    ("managed asset root", managed_root, capture_root / "managed")
]
for key, value in sorted(raw_source_roots.items()):
    if (
        not isinstance(key, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", key) is None
        or not isinstance(value, str)
        or not Path(value).is_absolute()
    ):
        raise SystemExit("source root mapping contains an invalid key or path")
    source_root = Path(value).resolve(strict=True)
    roots.append((f"source root {key}", source_root, capture_root / "sources" / key))

for index, (label, source_root, _) in enumerate(roots):
    if source_root == Path("/") or not source_root.is_dir():
        raise SystemExit(f"{label} must be an existing dedicated directory")
    if overlaps(source_root, backup_destination):
        raise SystemExit(f"{label} and backup destination paths must not overlap")
    if any(path.is_symlink() for path in source_root.rglob("*")):
        raise SystemExit(f"{label} must not contain symbolic links")
    if any(overlaps(source_root, other[1]) for other in roots[index + 1 :]):
        raise SystemExit("managed and source asset roots must not overlap")

capture_root.mkdir(mode=0o700)
for _, source_root, target in roots:
    shutil.copytree(source_root, target, copy_function=shutil.copy2)
PY

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
    "layout": {
        "managed_root": "managed",
        "source_roots": {
            path.name: path.relative_to(root).as_posix()
            for path in sorted((root / "sources").iterdir())
            if path.is_dir()
        } if (root / "sources").is_dir() else {},
    },
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
