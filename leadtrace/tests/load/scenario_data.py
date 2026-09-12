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
