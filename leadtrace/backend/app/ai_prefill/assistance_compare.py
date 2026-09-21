"""Conservative Candidate v1/v2 comparison."""

from __future__ import annotations

from typing import Any

from app.ai_prefill.assistance_contracts import CandidateEnvelope


def _index(items: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        result.setdefault(str(item.get(key, "")), []).append(item)
    return result


def compare_candidates(before: CandidateEnvelope, after: CandidateEnvelope) -> dict[str, Any]:
    if before.source != after.source:
        raise ValueError("candidates must use the same source identity")
    old = before.payload.model_dump(mode="json")
    new = after.payload.model_dump(mode="json")
    sections: dict[str, dict[str, list[str]]] = {}
    for section, key in (("compounds", "ref"), ("structure_locators", "ref"), ("lineages", "ref"), ("evidence", "ref"), ("activities", "compound_ref")):
        old_map = _index(old.get(section, []), key)
        new_map = _index(new.get(section, []), key)
        sections[section] = {
            "added": sorted(set(new_map) - set(old_map)),
            "removed": sorted(set(old_map) - set(new_map)),
            "changed": sorted(key_value for key_value in set(old_map) & set(new_map) if old_map[key_value] != new_map[key_value]),
            "ambiguous": sorted(key_value for key_value in set(old_map) | set(new_map) if len(old_map.get(key_value, [])) > 1 or len(new_map.get(key_value, [])) > 1),
        }
    return {
        "before_candidate_id": before.candidate_id,
        "after_candidate_id": after.candidate_id,
        "source_sha256": before.source.source_sha256,
        "payload_changed": old != new,
        "sections": sections,
    }


__all__ = ["compare_candidates"]
