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
    data["entries"][2]["exclusion_reason"] = "Source identity not resolved; explicitly outside this pass"
    inv.write_text(json.dumps(data))
    code, report = run(c, inv, capsys)
    assert code == 0
    assert report["excluded_entries"][0]["label"] == "12b"
    assert report["inventory_count"] == 3
    assert report["required_count"] == 2


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
