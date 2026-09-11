from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError


class AssetPathError(ValueError):
    pass


class AssetMimeMismatchError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class InspectedFile:
    path: Path
    sha256: str
    byte_size: int
    mime_type: str
    width: int | None = None
    height: int | None = None
    page_count: int | None = None


@dataclass(frozen=True, slots=True)
class StoredFile:
    storage_key: str
    path: Path
    sha256: str
    byte_size: int


_MIME_BY_SUFFIX = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".zip": "application/zip",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".log": "text/plain",
}


def _stream_sha256(handle: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    while chunk := handle.read(1024 * 1024):
        digest.update(chunk)
        byte_size += len(chunk)
    return digest.hexdigest(), byte_size


def _detected_mime(path: Path, header: bytes) -> str:
    suffix = path.suffix.casefold()
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if header.startswith(b"PK\x03\x04"):
        if suffix == ".xlsx":
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "application/zip"
    if header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "application/vnd.ms-excel"
    if suffix in {".csv", ".json", ".txt", ".md", ".log"}:
        try:
            header.decode("utf-8")
        except UnicodeDecodeError:
            return "application/octet-stream"
        return _MIME_BY_SUFFIX[suffix]
    return "application/octet-stream"


class LocalAssetStore:
    def __init__(
        self,
        managed_root: Path,
        *,
        source_roots: dict[str, Path] | None = None,
    ) -> None:
        self.managed_root = managed_root.resolve()
        self.managed_root.mkdir(parents=True, exist_ok=True)
        self.source_roots = {
            key: value.resolve()
            for key, value in (source_roots or {}).items()
        }

    @staticmethod
    def _validated_parts(storage_key: str) -> tuple[str, ...]:
        if not storage_key or "\\" in storage_key:
            raise AssetPathError("Invalid storage key")
        key = PurePosixPath(storage_key)
        if key.is_absolute() or any(part in {"", ".", ".."} for part in key.parts):
            raise AssetPathError("Storage key traversal is not allowed")
        return key.parts

    @staticmethod
    def _within(base: Path, target: Path) -> bool:
        try:
            target.relative_to(base)
        except ValueError:
            return False
        return True

    def source_storage_key(self, source_root_key: str, source_key: str) -> str:
        if source_root_key not in self.source_roots:
            raise AssetPathError("Unknown source root key")
        relative_parts = self._validated_parts(source_key)
        return PurePosixPath("source", source_root_key, *relative_parts).as_posix()

    def path_for(self, storage_key: str) -> Path:
        parts = self._validated_parts(storage_key)
        if parts[0] == "managed" and len(parts) >= 2:
            base = self.managed_root
            relative_parts = parts[1:]
        elif parts[0] == "source" and len(parts) >= 3:
            try:
                base = self.source_roots[parts[1]]
            except KeyError as error:
                raise AssetPathError("Unknown source root key") from error
            relative_parts = parts[2:]
        else:
            raise AssetPathError("Unknown storage namespace")
        target = base.joinpath(*relative_parts).resolve(strict=False)
        if not self._within(base, target):
            raise AssetPathError("Storage key escapes its configured root")
        return target

    def inspect(
        self,
        storage_key: str,
        *,
        validate_extension: bool = True,
        validate_content: bool = True,
    ) -> InspectedFile:
        path = self.path_for(storage_key)
        with path.open("rb") as handle:
            header = handle.read(8192)
            handle.seek(0)
            sha256, byte_size = _stream_sha256(handle)
        mime_type = _detected_mime(path, header)
        expected_mime = _MIME_BY_SUFFIX.get(path.suffix.casefold())
        if validate_extension and expected_mime and mime_type != expected_mime:
            label = path.suffix.lstrip(".").upper()
            raise AssetMimeMismatchError(
                f"{label} extension does not match detected content type"
            )

        width = height = None
        if validate_content and mime_type.startswith("image/"):
            try:
                with Image.open(path) as image:
                    width, height = image.size
            except (OSError, UnidentifiedImageError) as error:
                raise AssetMimeMismatchError("Image content is invalid") from error
        page_count = None
        if mime_type == "application/pdf":
            matches = re.findall(rb"/Type\s*/Page(?!s)\b", path.read_bytes())
            page_count = len(matches) or None
        return InspectedFile(
            path=path,
            sha256=sha256,
            byte_size=byte_size,
            mime_type=mime_type,
            width=width,
            height=height,
            page_count=page_count,
        )

    def put_bytes(self, content: bytes, *, suffix: str = "") -> StoredFile:
        if suffix and not re.fullmatch(r"\.[A-Za-z0-9]{1,12}", suffix):
            raise AssetPathError("Invalid managed-file suffix")
        sha256 = hashlib.sha256(content).hexdigest()
        relative = PurePosixPath("objects", sha256[:2], f"{sha256}{suffix.casefold()}")
        storage_key = PurePosixPath("managed", relative).as_posix()
        target = self.path_for(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{sha256}.",
                suffix=".tmp",
                dir=target.parent,
            )
            try:
                with os.fdopen(file_descriptor, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_name, target)
            finally:
                temporary_path = Path(temporary_name)
                if temporary_path.exists():
                    temporary_path.unlink()
        return StoredFile(
            storage_key=storage_key,
            path=target,
            sha256=sha256,
            byte_size=len(content),
        )
