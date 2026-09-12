from __future__ import annotations

from uuid import uuid4


COLD_PREVIEW_MIN_SAMPLES = 25


def cold_preview_payload(unique_token: int | None = None) -> dict[str, object]:
    token = uuid4().int if unique_token is None else unique_token
    map_number = abs(token) % 2_000_000_000 + 1
    return {
        "smiles": f"[CH3:{map_number}]C[C@H](O)c1ccc(F)cc1",
        "width": 600 + (abs(token) >> 64) % 20,
        "height": 420 + (abs(token) >> 72) % 20,
        "atom_indices": False,
        "transparent_background": False,
    }


def evaluate_request_gate(
    *,
    name: str,
    target_ms: int,
    num_requests: int,
    num_failures: int,
    p95_ms: int,
    minimum_successful_samples: int = 1,
    require_zero_failures: bool = False,
) -> tuple[str, ...]:
    failures: list[str] = []
    successful_samples = max(0, num_requests - num_failures)
    if successful_samples < minimum_successful_samples:
        failures.append(
            f"{name}: {successful_samples} successful samples is below "
            f"{minimum_successful_samples}"
        )
    if require_zero_failures and num_failures:
        sample_label = "sample" if num_failures == 1 else "samples"
        failures.append(
            f"{name}: {num_failures} failed {sample_label} is not allowed"
        )
    if successful_samples >= minimum_successful_samples and p95_ms > target_ms:
        failures.append(f"{name}: p95 {p95_ms}ms exceeds {target_ms}ms")
    return tuple(failures)
