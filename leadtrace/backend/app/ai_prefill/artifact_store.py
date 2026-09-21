"""Atomic, immutable storage for AI-prefill experiments and candidates."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope,
    Evaluation,
    ExperimentRegistry,
    ValidationReport,
    validate_declared_hashes,
    with_computed_hashes,
)

_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
_T = TypeVar("_T", bound=BaseModel)


class ArtifactStoreError(RuntimeError):
    pass


class ArtifactConflictError(ArtifactStoreError):
    pass


def _safe_id(value: str) -> str:
    if not value or len(value) > 128 or any(char not in _ID_ALPHABET for char in value):
        raise ValueError("artifact identifier contains unsupported characters")
    if value in {".", ".."}:
        raise ValueError("artifact identifier cannot be a path component")
    return value


class ArtifactStore:
    """Filesystem store whose published files are never overwritten."""

    def __init__(self, root: Path) -> None:
        if root.exists() and root.is_symlink():
            raise ArtifactStoreError("artifact root must not be a symlink")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _experiment_dir(self, experiment_id: str) -> Path:
        return self.root / "experiments" / _safe_id(experiment_id)

    def _assert_no_symlink_components(self, path: Path) -> None:
        try:
            relative = path.relative_to(self.root)
        except ValueError as error:
            raise ArtifactStoreError("artifact path escapes configured root") from error
        current = self.root
        for component in relative.parts:
            current /= component
            if current.is_symlink():
                raise ArtifactStoreError("artifact path must not contain symlink components")

    @staticmethod
    def _canonical(model: BaseModel) -> bytes:
        return json.dumps(
            model.model_dump(mode="json"),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def _atomic_write(self, path: Path, content: bytes, *, overwrite: bool = False) -> None:
        self._assert_no_symlink_components(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not overwrite:
            if path.is_symlink():
                raise ArtifactStoreError("artifact path must not be a symlink")
            if path.read_bytes() == content:
                return
            raise ArtifactConflictError(f"artifact already exists with different content: {path.name}")
        temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            fd = os.open(temp, flags, 0o640)
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # link(2) publishes the fully fsynced temp file without replacing
                # a file another process may have won the race to create.
                os.link(temp, path)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != content:
                    raise ArtifactConflictError(f"artifact already exists with different content: {path.name}")
            else:
                temp.unlink(missing_ok=True)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temp.unlink(missing_ok=True)

    def put_experiment(self, registry: ExperimentRegistry) -> Path:
        path = self._experiment_dir(registry.experiment_id) / "experiment.json"
        self._atomic_write(path, self._canonical(registry))
        return path

    def put_candidate(self, candidate: CandidateEnvelope) -> CandidateEnvelope:
        validate_declared_hashes(candidate)
        candidate = with_computed_hashes(candidate)
        directory = self._experiment_dir(candidate.experiment_id) / "candidates" / _safe_id(candidate.candidate_id)
        self._atomic_write(directory / "candidate.json", self._canonical(candidate))
        self._atomic_write(directory / "payload.json", self._canonical(candidate.payload))
        return candidate

    def put_validation(self, report: ValidationReport) -> Path:
        path = self._experiment_dir(report.experiment_id) / "validations" / f"{_safe_id(report.report_id)}.json"
        self._atomic_write(path, self._canonical(report))
        return path

    def put_evaluation(self, evaluation: Evaluation) -> Path:
        path = self._experiment_dir(evaluation.experiment_id) / "evaluations" / f"{_safe_id(evaluation.evaluation_id)}.json"
        self._atomic_write(path, self._canonical(evaluation))
        return path

    def read_json(self, path: Path) -> dict[str, object]:
        resolved = path.resolve()
        if self.root not in resolved.parents:
            raise ArtifactStoreError("artifact path escapes configured root")
        self._assert_no_symlink_components(path)
        return json.loads(path.read_text(encoding="utf-8"))


__all__ = ["ArtifactConflictError", "ArtifactStore", "ArtifactStoreError"]
