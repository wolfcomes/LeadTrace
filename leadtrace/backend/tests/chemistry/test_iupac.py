from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from rdkit import Chem

from app.chemistry.iupac import IupacError, resolve_iupac


@pytest.mark.parametrize('name', ['', 'ethanol\nmethane', 'x' * 1001])
def test_rejects_invalid_input_without_starting_java(name, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('Java must not run for invalid input')
    monkeypatch.setattr(subprocess, 'run', unexpected)
    with pytest.raises(IupacError) as error:
        resolve_iupac(name, jar_path=Path('/missing.jar'))
    assert error.value.code == 'IUPAC_NAME_INVALID'


def test_missing_local_runtime_is_reported():
    with pytest.raises(IupacError) as error:
        resolve_iupac('ethanol', jar_path=Path('/missing.jar'))
    assert error.value.code == 'IUPAC_UNAVAILABLE'


@pytest.fixture
def opsin_jar():
    path = os.environ.get('LEADTRACE_OPSIN_JAR')
    if not path:
        pytest.skip('Install pinned OPSIN and set LEADTRACE_OPSIN_JAR for local integration')
    return Path(path)


def test_real_opsin_resolves_ethanol_and_preserves_stereochemistry(opsin_jar):
    assert resolve_iupac('ethanol', jar_path=opsin_jar).smiles == 'CCO'
    result = resolve_iupac('(2R)-2-hydroxypropanoic acid', jar_path=opsin_jar)
    molecule = Chem.MolFromMolBlock(result.molfile)
    assert molecule is not None
    assert Chem.FindMolChiralCenters(molecule) == [(1, 'R')]
    assert Chem.MolToSmiles(molecule) == result.smiles


def test_real_opsin_invalid_name_has_safe_failure(opsin_jar):
    with pytest.raises(IupacError) as error:
        resolve_iupac('this is not a chemical name', jar_path=opsin_jar)
    assert error.value.code == 'IUPAC_UNPARSEABLE'
    assert 'chemical name' not in str(error.value)


def test_timeout_does_not_expose_name_or_subprocess_details(opsin_jar, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(['secret argument'], 8, stderr='sensitive output')
    monkeypatch.setattr(subprocess, 'run', timeout)
    with pytest.raises(IupacError) as error:
        resolve_iupac('ethanol', jar_path=opsin_jar)
    assert error.value.code == 'IUPAC_TIMEOUT'
    assert 'secret' not in str(error.value)
    assert 'sensitive' not in str(error.value)


def test_rdkit_rejects_invalid_opsin_output(opsin_jar, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess([], 0, 'C(C)(C)(C)(C)C\n', ''))
    with pytest.raises(IupacError) as error:
        resolve_iupac('ethanol', jar_path=opsin_jar)
    assert error.value.code == 'IUPAC_STRUCTURE_INVALID'


def test_pinned_runtime_integrity_is_checked(tmp_path):
    altered = tmp_path / 'opsin.jar'
    altered.write_bytes(b'not the pinned OPSIN release')
    with pytest.raises(IupacError) as error:
        resolve_iupac('ethanol', jar_path=altered)
    assert error.value.code == 'IUPAC_UNAVAILABLE'
