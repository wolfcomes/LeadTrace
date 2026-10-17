"""Bounded, offline name parsing with a pinned local OPSIN runtime."""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore

from rdkit import Chem, rdBase
from rdkit.Chem import rdDepictor

OPSIN_VERSION = '2.8.0'
OPSIN_SHA256 = 'd25bc08f41b8f6fcd6f35e18ab83f3b8d9218cdb003d55c5f74aaefe2e0c68ab'
OPSIN_FILENAME = f'opsin-cli-{OPSIN_VERSION}-jar-with-dependencies.jar'
OPSIN_URL = f'https://github.com/dan2097/opsin/releases/download/{OPSIN_VERSION}/{OPSIN_FILENAME}'
DEFAULT_OPSIN_JAR = Path('/opt/leadtrace/opsin') / OPSIN_FILENAME
_slots = BoundedSemaphore(2)


class IupacError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class IupacResult:
    smiles: str
    molfile: str
    resolver: str = f'OPSIN {OPSIN_VERSION}'


def resolve_iupac(name: str, *, jar_path: Path = DEFAULT_OPSIN_JAR) -> IupacResult:
    if not name.strip() or len(name) > 1000 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise IupacError('IUPAC_NAME_INVALID')
    if not _slots.acquire(blocking=False):
        raise IupacError('IUPAC_BUSY')
    try:
        try:
            with jar_path.open('rb') as stream:
                checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
            if checksum != OPSIN_SHA256:
                raise IupacError('IUPAC_UNAVAILABLE')
            process = subprocess.run(
                ['java', '-Xmx128m', '-jar', str(jar_path), '-o', 'smi'],
                input=name.strip() + '\n', text=True, encoding='utf-8',
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8, check=False,
            )
        except subprocess.TimeoutExpired:
            raise IupacError('IUPAC_TIMEOUT') from None
        except (OSError, UnicodeError):
            raise IupacError('IUPAC_UNAVAILABLE') from None
        if process.returncode != 0:
            raise IupacError('IUPAC_UNAVAILABLE')
        smiles = process.stdout.strip()
        if not smiles or '\n' in smiles:
            raise IupacError('IUPAC_UNPARSEABLE')
        with rdBase.BlockLogs():
            molecule = Chem.MolFromSmiles(smiles)
        if molecule is None or not molecule.GetNumAtoms():
            raise IupacError('IUPAC_STRUCTURE_INVALID')
        rdDepictor.Compute2DCoords(molecule)
        return IupacResult(
            smiles=Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True),
            molfile=Chem.MolToMolBlock(molecule),
        )
    finally:
        _slots.release()
