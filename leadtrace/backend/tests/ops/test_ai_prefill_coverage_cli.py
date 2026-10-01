import json
from pathlib import Path

import pytest

from leadtrace.ops.ai_prefill.cli import main


def files(tmp_path, labels=("12a",), **inventory_updates):
    example = Path(__file__).resolve().parents[4] / "docs/ai-prefill/examples/candidate-v1.json"
    candidate = json.loads(example.read_text())
    candidate["hashes"] = None
    candidate["payload"] = {"schema_version": 1, "compounds": [
        {"ref": f"c{i}", "compound_label": label, "structure": {"smiles": "CCO"}}
        for i, label in enumerate(labels)
    ]}
    candidate["omissions"] = [{"path": "payload.compounds", "reason": "Remaining table rows omitted"}]
    inventory = {
        "inventory_version": 1,
        "source": candidate["source"],
        "scope": "All unique assayed identities in main Tables 1–5",
        "reviewed_by": "independent source audit",
        "entries": [
            {"label": label, "aliases": [], "required": True,
             "source_locator": "PDF page 1, Table 1", "role": "assayed"}
            for label in ("1", "12a", "12b")
        ],
        **inventory_updates,
    }
    c, inv = tmp_path / "candidate.json", tmp_path / "inventory.json"
    c.write_text(json.dumps(candidate)); inv.write_text(json.dumps(inventory))
    return c, inv


def run(c, inv, capsys):
    code = main(["candidate", "coverage", str(c), "--inventory", str(inv)])
    return code, json.loads(capsys.readouterr().out)


def test_missing_source_rows_fail_even_with_omission_note(tmp_path, capsys):
    code, report = run(*files(tmp_path), capsys)
    assert code == 4
    assert report["missing_labels"] == ["1", "12b"]
    assert report["required_count"] == 3
    assert report["covered_count"] == 1
    assert report["status"] == "incomplete"


def test_complete_source_inventory_passes_with_extra_intermediate(tmp_path, capsys):
    code, report = run(*files(tmp_path, ("1", "12a", "12b", "10g")), capsys)
    assert code == 0
    assert report["status"] == "complete_for_declared_scope"
    assert report["extra_candidate_labels"] == ["10g"]
    assert len(report["candidate_sha256"]) == 64
    assert len(report["inventory_sha256"]) == 64


def test_coverage_hashes_identify_canonical_content_not_file_bytes(tmp_path, capsys):
    import hashlib
    c, inv = files(tmp_path, ("1", "12a", "12b"))
    _, before = run(c, inv, capsys)
    c.write_text(json.dumps(json.loads(c.read_text()), indent=4) + "\n")
    inv.write_text(json.dumps(json.loads(inv.read_text()), indent=4) + "\n")
    _, after = run(c, inv, capsys)
    assert before["candidate_sha256"] == after["candidate_sha256"]
    assert before["inventory_sha256"] == after["inventory_sha256"]
    assert after["candidate_sha256"] != hashlib.sha256(c.read_bytes()).hexdigest()
    assert after["inventory_sha256"] != hashlib.sha256(inv.read_bytes()).hexdigest()
    assert after["hash_kinds"] == {
        "candidate_sha256": "canonical_candidate_content",
        "inventory_sha256": "canonical_inventory_content",
    }


def test_prefix_match_does_not_hide_stereoisomer_gap(tmp_path, capsys):
    c, inv = files(tmp_path, ("1", "12a racemate", "12b"))
    code, report = run(c, inv, capsys)
    assert code == 4
    assert report["missing_labels"] == ["12a"]


def test_explicit_alias_matches_but_collision_fails(tmp_path, capsys):
    c, inv = files(tmp_path, ("1", "12a / known alias", "12b"))
    data = json.loads(inv.read_text()); data["entries"][1]["aliases"] = ["12a / known alias"]
    inv.write_text(json.dumps(data))
    assert run(c, inv, capsys)[0] == 0
    data["entries"][2]["aliases"] = ["12a / known alias"]
    inv.write_text(json.dumps(data))
    code, report = run(c, inv, capsys)
    assert code == 2
    assert report["code"] == "INVALID_INPUT"


@pytest.mark.parametrize("change", ["source", "unreviewed", "empty", "duplicate"])
def test_untrustworthy_inventory_rejected(tmp_path, capsys, change):
    c, inv = files(tmp_path)
    data = json.loads(inv.read_text())
    if change == "source": data["source"]["source_sha256"] = "f" * 64
    if change == "unreviewed": data["reviewed_by"] = " "
    if change == "empty": data["entries"] = []
    if change == "duplicate": data["entries"].append(data["entries"][0])
    inv.write_text(json.dumps(data))
    code, report = run(c, inv, capsys)
    assert code == 2
    assert report["code"] == "INVALID_INPUT"


def test_exclusion_requires_reason_and_is_visible(tmp_path, capsys):
    c, inv = files(tmp_path, ("1", "12a"))
    data = json.loads(inv.read_text()); data["entries"][2]["required"] = False
    inv.write_text(json.dumps(data))
    assert run(c, inv, capsys)[0] == 2
    data["entries"][2]["exclusion_reason"] = "User explicitly limited this pass to 1 and 12a"
    inv.write_text(json.dumps(data))
    code, report = run(c, inv, capsys)
    assert code == 0
    assert report["excluded_entries"][0]["label"] == "12b"
    assert report["inventory_count"] == 3
    assert report["required_count"] == 2


def test_report_exposes_full_inventory_gap_beyond_declared_exclusions(tmp_path, capsys):
    """A narrowed required scope must not hide source-inventory omissions."""
    c, inv = files(tmp_path, ("1", "12a"))
    data = json.loads(inv.read_text())
    data["entries"][2]["required"] = False
    data["entries"][2]["exclusion_reason"] = "Legacy run narrowed scope"
    inv.write_text(json.dumps(data))

    code, report = run(c, inv, capsys)

    assert code == 0
    assert report["required_count"] == 2
    assert report["covered_count"] == 2
    assert report["all_inventory_coverage"] == {
        "inventory_count": 3,
        "covered_count": 2,
        "missing_labels": ["12b"],
        "ambiguous_matches": [],
    }


def test_two_candidate_aliases_are_ambiguous_not_double_coverage(tmp_path, capsys):
    c, inv = files(tmp_path, ("1", "12a", "alias12a", "12b"))
    data = json.loads(inv.read_text()); data["entries"][1]["aliases"] = ["alias12a"]
    inv.write_text(json.dumps(data))
    code, report = run(c, inv, capsys)
    assert code == 4
    assert report["covered_count"] == 2
    assert report["ambiguous_matches"] == [{"label": "12a", "candidate_refs": ["c1", "c2"]}]


def test_inventory_is_required(tmp_path, capsys):
    c, _ = files(tmp_path)
    assert main(["candidate", "coverage", str(c)]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INVENTORY_REQUIRED"


def test_pfpkg_source_inventory_detects_the_real_33_compound_gap(tmp_path, capsys):
    labels = ("10g", "11a", "11g", "12a", "12b", "13", "15a", "15b", "33", "58", "61")
    c, inv = files(tmp_path, labels)
    example = Path(__file__).resolve().parents[4] / "docs/ai-prefill/examples/compound-inventory-pfpkg-004.json"
    inventory = json.loads(example.read_text())
    data = json.loads(c.read_text()); data["source"] = inventory["source"]
    c.write_text(json.dumps(data)); inv.write_text(json.dumps(inventory))
    code, report = run(c, inv, capsys)
    assert code == 4
    assert (report["covered_count"], report["required_count"]) == (6, 39)
    assert len(report["missing_labels"]) == 33
    assert {"1", "23", "38", "50", "51", "52", "53", "54"} <= set(report["missing_labels"])


@pytest.mark.parametrize(
    "labels,covered,ambiguous",
    [
        (("1", "12a", "alias12b", "extra"), 3, []),
        (("1", "12a", "12b", "alias12b"), 2,
         [{"label": "12b", "candidate_refs": ["c2", "c3"]}]),
    ],
)
def test_full_inventory_resolves_excluded_aliases_without_double_counting(
    tmp_path, capsys, labels, covered, ambiguous,
):
    c, inv = files(tmp_path, labels)
    data = json.loads(inv.read_text())
    data["entries"][2].update(
        required=False, aliases=["alias12b"],
        exclusion_reason="User explicitly limited this pass to 1 and 12a",
    )
    inv.write_text(json.dumps(data))

    code, report = run(c, inv, capsys)

    assert code == 0  # Required-scope exit semantics remain backward compatible.
    assert report["covered_count"] == 2
    assert report["all_inventory_coverage"] == {
        "inventory_count": 3,
        "covered_count": covered,
        "missing_labels": [],
        "ambiguous_matches": ambiguous,
    }
    assert report["extra_candidate_labels"] == (["extra"] if "extra" in labels else [])


def test_full_inventory_matches_required_scope_without_exclusions(tmp_path, capsys):
    code, report = run(*files(tmp_path), capsys)
    assert code == 4
    full = report["all_inventory_coverage"]
    assert full["inventory_count"] == report["required_count"]
    for key in ("covered_count", "missing_labels", "ambiguous_matches"):
        assert full[key] == report[key]
