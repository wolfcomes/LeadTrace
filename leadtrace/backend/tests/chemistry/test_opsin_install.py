from io import BytesIO

import pytest

from app.chemistry.install_opsin import install


def test_corrupt_download_preserves_existing_runtime_and_removes_temporary_file(tmp_path, monkeypatch):
    destination = tmp_path / 'opsin.jar'
    destination.write_bytes(b'existing runtime')
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: BytesIO(b'corrupt download'))
    with pytest.raises(ValueError, match='checksum mismatch'):
        install(destination)
    assert destination.read_bytes() == b'existing runtime'
    assert list(tmp_path.iterdir()) == [destination]
