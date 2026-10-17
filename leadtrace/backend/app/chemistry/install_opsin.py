"""Install the pinned OPSIN release; downloads occur only during provisioning."""
from __future__ import annotations

import argparse
import hashlib
import tempfile
import urllib.request
from pathlib import Path

from app.chemistry.iupac import DEFAULT_OPSIN_JAR, OPSIN_SHA256, OPSIN_URL


def install(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with urllib.request.urlopen(OPSIN_URL, timeout=60) as response:
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
                temporary = Path(output.name)
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        with temporary.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != OPSIN_SHA256:
                raise ValueError('OPSIN checksum mismatch; refusing installation')
        temporary.chmod(0o644)
        temporary.replace(destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=DEFAULT_OPSIN_JAR)
    install(parser.parse_args().destination)
