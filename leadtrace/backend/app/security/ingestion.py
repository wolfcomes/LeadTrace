from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path, PurePosixPath
from urllib.parse import ParseResult, urlparse
from zipfile import BadZipFile, ZipFile


class UnsafeArchiveError(ValueError):
    pass


class UnsafeOutboundURLError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    max_members: int = 1000
    max_total_bytes: int = 2 * 1024 * 1024 * 1024
    max_depth: int = 12
    max_compression_ratio: int = 200

    def __post_init__(self) -> None:
        if min(
            self.max_members,
            self.max_total_bytes,
            self.max_depth,
            self.max_compression_ratio,
        ) <= 0:
            raise ValueError("archive limits must be positive")


def validate_zip_archive(path: Path, limits: ArchiveLimits) -> None:
    archive = Path(path).resolve(strict=True)
    if archive.is_symlink() or not archive.is_file():
        raise UnsafeArchiveError("archive must be a regular file")
    try:
        with ZipFile(archive) as handle:
            members = handle.infolist()
            if len(members) > limits.max_members:
                raise UnsafeArchiveError("archive member count exceeds limit")
            total_bytes = 0
            for member in members:
                normalized_name = member.filename.replace("\\", "/")
                member_path = PurePosixPath(normalized_name)
                if (
                    not normalized_name
                    or member_path.is_absolute()
                    or any(part in {"", ".", ".."} for part in member_path.parts)
                ):
                    raise UnsafeArchiveError("archive member path is unsafe")
                if len(member_path.parts) > limits.max_depth:
                    raise UnsafeArchiveError("archive member depth exceeds limit")
                total_bytes += member.file_size
                if total_bytes > limits.max_total_bytes:
                    raise UnsafeArchiveError("archive expanded size exceeds limit")
                compressed_size = max(member.compress_size, 1)
                if member.file_size / compressed_size > limits.max_compression_ratio:
                    raise UnsafeArchiveError("archive compression ratio exceeds limit")
    except BadZipFile as error:
        raise UnsafeArchiveError("archive is not a valid ZIP file") from error


def validate_outbound_url(
    value: str,
    *,
    allowed_hosts: set[str] | frozenset[str],
) -> ParseResult:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    normalized_allowlist = {host.casefold().rstrip(".") for host in allowed_hosts}
    if parsed.scheme != "https" or not hostname or hostname not in normalized_allowlist:
        raise UnsafeOutboundURLError("outbound URL host is not allowlisted for HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeOutboundURLError("outbound URL credentials are forbidden")
    try:
        port = parsed.port
    except ValueError as error:
        raise UnsafeOutboundURLError("outbound URL port is invalid") from error
    if port not in (None, 443):
        raise UnsafeOutboundURLError("outbound URL port is forbidden")
    try:
        ip_address(hostname)
    except ValueError:
        pass
    else:
        raise UnsafeOutboundURLError("outbound URL IP literals are forbidden")
    if parsed.fragment:
        raise UnsafeOutboundURLError("outbound URL fragments are forbidden")
    return parsed
