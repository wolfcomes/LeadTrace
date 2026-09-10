#!/usr/bin/env python3
"""Build and inspect sources for lineage structure reconstruction.

Manifest rows retain file extensions as hints only. Source inspection uses
file content and parses candidate structures without confirming their identity.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import re
import tempfile
from typing import Iterable, Iterator, Mapping, Sequence
from xml.etree import ElementTree
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTO_FILL_DIR = PROJECT_ROOT / "09_paper_review" / "auto_fill"
DEFAULT_DOWNLOAD_ROOT = DEFAULT_AUTO_FILL_DIR / "lineage_structure_sources"
DEFAULT_MANIFEST_PATH = DEFAULT_AUTO_FILL_DIR / "structure_source_manifest.csv"
DEFAULT_SNAPSHOT_PATH = DEFAULT_AUTO_FILL_DIR / "structure_source_snapshot.json"
DEFAULT_WORK_PATH = DEFAULT_AUTO_FILL_DIR / "compound_structure_work.csv"
DEFAULT_CONFIRMED_PATH = DEFAULT_AUTO_FILL_DIR / "confirmed_compound_structures.csv"
DEFAULT_RECONSTRUCTION_SUMMARY_PATH = (
    DEFAULT_AUTO_FILL_DIR / "lineage_structure_reconstruction_summary.json"
)
MISSING = "--"

MANIFEST_SCHEMA_VERSION = "lineage_structure_source_manifest_v1"
MANIFEST_FIELDS = (
    "source_id",
    "paper_id",
    "doi",
    "article_id",
    "file_id",
    "source_file",
    "download_url",
    "extension",
    "content_class",
    "size_bytes",
    "source_md5",
    "local_path",
    "sha256",
    "download_status",
    "inspection_status",
)

_DOI_PREFIX = re.compile(
    r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)",
    flags=re.IGNORECASE,
)
_DOI = re.compile(r"^10\.\d{4,9}/[-._;()/:a-z0-9]+$", flags=re.IGNORECASE)
_MD5 = re.compile(r"^[a-f0-9]{32}$", flags=re.IGNORECASE)
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")
_NUMERIC_ID = re.compile(r"^[0-9]+$")
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_MAX_SOURCE_NAME_LENGTH = 180
_XLS_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
_HEADER_SEPARATOR = re.compile(r"[^a-z0-9]+")
_CELL_REFERENCE = re.compile(r"^([A-Za-z]+)")
_LABEL_ALIASES = frozenset({
    "compound",
    "compounds",
    "compoundid",
    "compoundidpaper",
    "compoundidentifier",
    "compoundcode",
    "compoundno",
    "compoundnumber",
    "comp",
    "compno",
    "cmpd",
    "compd",
    "entry",
    "manuscriptcompound",
    "identificationnumber",
    "examplenbr",
    "serialnumber",
    "compondnoms",
    "n",
    "no",
    "id",
})
_STRUCTURE_ALIASES = frozenset({
    "smile",
    "smiles",
    "canonical",
    "isomeric",
    "canonicalsmile",
    "canonicalsmiles",
    "isomericsmile",
    "isomericsmiles",
    "canonicalisomericsmiles",
    "smilescanonical",
    "smilesisomeric",
    "smilesstring",
    "stringssmiles",
    "smilescode",
    "canonicalsmilespp",
    "smilesstringd",
})

STRUCTURE_WORK_FIELDS = (
    "work_row_id",
    "paper_id",
    "compound_entity_id",
    "compound_label",
    "source_label",
    "normalized_label",
    "canonical_isomeric_smiles",
    "raw_structure_text",
    "source_id",
    "source_file",
    "source_locator",
    "record_status",
    "rejection_reason",
    "binding_status",
    "binding_method",
    "binding_reason",
    "candidate_status",
    "structure_source_type",
    "structure_source_file",
    "structure_source_locator",
    "confirmation_status",
    "reconstruction_status",
    "reconstruction_reason",
    "reconstruction_method",
    "scaffold_smiles",
    "r_group_assignments",
    "attachment_mapping",
    "component_selection_status",
    "stereochemistry_status",
    "source_match_status",
    "review_decision",
    "replacement_decision",
    "rdkit_status",
    "confirmation_reason",
)

CONFIRMED_STRUCTURE_FIELDS = (
    "confirmed_structure_id",
    "paper_id",
    "compound_entity_id",
    "compound_label",
    "normalized_label",
    "canonical_isomeric_smiles",
    "confirmation_status",
    "structure_review_status",
    "structure_source_type",
    "structure_source_file",
    "structure_source_locator",
    "reconstruction_method",
    "scaffold_smiles",
    "r_group_assignments",
    "attachment_mapping",
    "rdkit_version",
    "accepted_work_row_id",
)

_CONFIRMABLE_SOURCE_MATCHES = frozenset({
    "exact_machine_readable_match",
    "exact_external_identifier_match",
    "exact_complete_structure_match",
    "visual_graph_match",
    "reconstructed_source_graph_match",
})

FIGSHARE_SEARCH_URL = "https://api.figshare.com/v2/articles/search"
_MACHINE_SOURCE_EXTENSIONS = frozenset({
    "csv", "tsv", "txt", "smi", "smiles", "sdf", "mol", "xlsx", "xls",
})


def _inspection_result(
    *,
    content_class: str,
    inspection_status: str,
    detected_format: str,
    detected_columns: list[dict[str, object]] | None = None,
    records: list[dict[str, object]] | None = None,
    issues: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "content_class": content_class,
        "inspection_status": inspection_status,
        "detected_format": detected_format,
        "detected_columns": detected_columns or [],
        "records": records or [],
        "issues": issues or [],
    }


def _issue(
    code: str, message: str, locator: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "code": code,
        "message": message,
        "source_locator": dict(locator) if locator is not None else None,
    }


def _normalize_header(value: object) -> str:
    header = str(value or "").strip()
    # A UTF-8 BOM can survive as CP1252 mojibake when a later byte forces the
    # otherwise ISO-8859/CP1252 source down the fallback decoder.  Normalize
    # only this leading signature; preserve the displayed source header.
    header = header.lstrip("\ufeff")
    if header.startswith("\u00ef\u00bb\u00bf"):
        header = header[3:]
    header = header.casefold()
    if header == "序号":
        return "serialnumber"
    return _HEADER_SEPARATOR.sub("", header)


def _column_index(headers: Sequence[str], aliases: frozenset[str]) -> int | None:
    for index, header in enumerate(headers):
        if _normalize_header(header) in aliases:
            return index
    return None


def _without_trailing_cxsmiles(raw_structure_text: str) -> str:
    parse_text = raw_structure_text.strip()
    match = re.fullmatch(r"(.*?)\s+\|.*\|", parse_text, flags=re.DOTALL)
    return match.group(1).rstrip() if match else parse_text


def _canonicalize_smiles(raw_structure_text: str) -> tuple[str, str]:
    parse_text = _without_trailing_cxsmiles(raw_structure_text)
    if not parse_text:
        return "", "empty_structure"
    from rdkit import Chem, rdBase

    # SMILES cells are single records. Newlines would otherwise be treated as
    # whitespace and RDKit can silently keep only the first expression.
    if "\n" in parse_text or "\r" in parse_text:
        return "", "invalid_structure"
    parser_parameters = Chem.SmilesParserParams()
    parser_parameters.parseName = False
    parser_parameters.strictParsing = True
    with rdBase.BlockLogs():
        molecule = Chem.MolFromSmiles(parse_text, parser_parameters)
    if molecule is None:
        return "", "invalid_structure"
    return (
        Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True),
        "",
    )


def _record_issue(
    rejection_reason: str, locator: Mapping[str, object],
) -> dict[str, object]:
    if rejection_reason == "empty_structure":
        return _issue(
            "empty_structure", "The structure field is empty.", locator,
        )
    return _issue(
        "invalid_structure",
        "RDKit could not parse the structure text.",
        locator,
    )


def _smiles_record(
    *, source_label: str, raw_structure_text: str,
    locator: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object] | None]:
    canonical, rejection_reason = _canonicalize_smiles(raw_structure_text)
    record = {
        "source_label": source_label,
        "raw_structure_text": raw_structure_text,
        "canonical_isomeric_smiles": canonical,
        "source_locator": dict(locator),
        "record_status": "rejected" if rejection_reason else "parsed",
        "rejection_reason": rejection_reason,
    }
    issue = _record_issue(rejection_reason, locator) if rejection_reason else None
    return record, issue


def _first_populated_row(
    rows: Sequence[tuple[int, list[str]]],
) -> int | None:
    for index, (_, values) in enumerate(rows):
        if any(value != "" for value in values):
            return index
    return None


def _inferred_structure_column(
    headers: Sequence[str],
    data_rows: Sequence[tuple[int, list[str]]],
    *,
    label_index: int | None,
) -> int | None:
    """Infer only an unnamed, consistently SMILES-shaped source column."""
    if label_index is None:
        return None
    candidates: list[tuple[float, int, int]] = []
    for column_index, header in enumerate(headers):
        if column_index == label_index or str(header).strip():
            continue
        populated = [
            values[column_index].strip()
            for _, values in data_rows[:100]
            if column_index < len(values) and values[column_index].strip()
        ]
        if len(populated) < 2:
            continue
        valid_count = sum(
            bool(_canonicalize_smiles(value)[0]) for value in populated
        )
        ratio = valid_count / len(populated)
        if ratio >= 0.9:
            candidates.append((ratio, valid_count, column_index))
    if not candidates:
        return None
    best = sorted(candidates, reverse=True)
    if len(best) > 1 and best[0][:2] == best[1][:2]:
        return None
    return best[0][2]


def _table_layout(
    rows: Sequence[tuple[int, list[str]]],
) -> tuple[int | None, int | None, int | None, bool]:
    direct_candidates: list[tuple[tuple[int, int, int], int, int, int | None]] = []
    for position, (_, headers) in enumerate(rows[:20]):
        structure_index = _column_index(headers, _STRUCTURE_ALIASES)
        if structure_index is None:
            continue
        label_index = _column_index(headers, _LABEL_ALIASES)
        # Prefer the earliest complete label/structure header.  ACS tables can
        # repeat a wider header later when assay panels change; selecting that
        # row would silently discard the first section of structure records.
        score = (
            int(label_index is not None),
            -position,
            sum(bool(str(header).strip()) for header in headers),
        )
        direct_candidates.append(
            (score, position, structure_index, label_index)
        )
    if direct_candidates:
        _, position, structure_index, label_index = max(direct_candidates)
        return position, structure_index, label_index, False

    header_position = _first_populated_row(rows)
    if header_position is None:
        return None, None, None, False
    headers = rows[header_position][1]
    label_index = _column_index(headers, _LABEL_ALIASES)
    structure_index = _inferred_structure_column(
        headers, rows[header_position + 1:], label_index=label_index,
    )
    return header_position, structure_index, label_index, structure_index is not None


def _inspect_tables(
    detected_format: str,
    tables: Sequence[tuple[str | None, Sequence[tuple[int, list[str]]]]],
) -> dict[str, object]:
    detected_columns: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []

    for sheet, rows in tables:
        header_position, structure_index, label_index, inferred = _table_layout(rows)
        if header_position is None:
            continue
        headers = rows[header_position][1]
        if structure_index is None:
            continue
        detected_columns.append({
            "sheet": sheet,
            "label_column": headers[label_index] if label_index is not None else None,
            "structure_column": (
                "<inferred>" if inferred else headers[structure_index]
            ),
        })

        for row_number, values in rows[header_position + 1:]:
            if not any(value != "" for value in values):
                continue
            raw_structure_text = (
                values[structure_index] if structure_index < len(values) else ""
            )
            source_label = (
                values[label_index]
                if label_index is not None and label_index < len(values)
                else ""
            )
            # Repeated table headers delimit assay sections, not molecules.
            # They may be wider or narrower than the first header, but retain
            # the same label/structure columns.
            if _normalize_header(raw_structure_text) in _STRUCTURE_ALIASES:
                continue
            locator: dict[str, object] = {"row": row_number}
            if sheet is not None:
                locator = {"sheet": sheet, "row": row_number}
            record, issue = _smiles_record(
                source_label=source_label,
                raw_structure_text=raw_structure_text,
                locator=locator,
            )
            records.append(record)
            if issue is not None:
                issues.append(issue)

    # A repeated label is safe only when every parsed structure is identical.
    # Keep all rows for audit, but prevent an ambiguous label from proceeding as
    # a valid source mapping.
    structures_by_label: dict[str, set[str]] = {}
    for record in records:
        label = str(record["source_label"]).strip()
        smiles = str(record["canonical_isomeric_smiles"])
        if label and smiles:
            structures_by_label.setdefault(label, set()).add(smiles)
    conflicting_labels = {
        label for label, structures in structures_by_label.items()
        if len(structures) > 1
    }
    for record in records:
        if str(record["source_label"]).strip() not in conflicting_labels:
            continue
        locator = record["source_locator"]
        record["record_status"] = "rejected"
        record["rejection_reason"] = "conflicting_label_structure"
        issues.append(_issue(
            "conflicting_label_structure",
            "The same source label maps to conflicting structures.",
            locator,
        ))

    if not detected_columns:
        return _inspection_result(
            content_class="non_structure_table",
            inspection_status="inspected",
            detected_format=detected_format,
            issues=[_issue(
                "structure_column_not_found",
                "No recognized structure column was found.",
            )],
        )
    return _inspection_result(
        content_class="machine_readable_structure_table",
        inspection_status="inspected",
        detected_format=detected_format,
        detected_columns=detected_columns,
        records=records,
        issues=issues,
    )


def _csv_rows(text: str, delimiter: str) -> list[tuple[int, list[str]]]:
    # Mirror ``open(..., newline="")`` so csv.reader can recognize sources
    # that use CR-only records instead of LF or CRLF line endings.
    reader = csv.reader(
        io.StringIO(text, newline=""), delimiter=delimiter, strict=True,
    )
    return [(row_number, row) for row_number, row in enumerate(reader, start=1)]


def _unwrap_complete_quoted_rows(text: str) -> str:
    """Remove one non-standard CSV quote layer applied to every physical row."""
    lines = text.splitlines()
    populated = [line for line in lines if line]
    if len(populated) < 2 or not all(
        line.startswith('"') and line.endswith('"') for line in populated
    ):
        return text

    unwrapped: list[str] = []
    for line in lines:
        if not line:
            unwrapped.append("")
            continue
        try:
            values = next(csv.reader([line], delimiter=",", strict=True))
        except csv.Error:
            return text
        if len(values) != 1:
            return text
        unwrapped.append(values[0])
    if not any(
        delimiter in value
        for value in unwrapped
        for delimiter in (",", ";", "\t")
    ):
        return text
    return "\n".join(unwrapped) + ("\n" if text.endswith(("\n", "\r")) else "")


def _inspect_delimited_text(text: str) -> dict[str, object] | None:
    text = _unwrap_complete_quoted_rows(text)
    candidates: list[tuple[tuple[int, int, int, int], list[tuple[int, list[str]]]]] = []
    parse_errors: list[str] = []
    has_structure_candidate = False
    for preference, delimiter in enumerate((",", ";", "\t")):
        try:
            rows = _csv_rows(text, delimiter)
        except csv.Error as error:
            parse_errors.append(str(error))
            continue
        header_position, structure_index, label_index, _ = _table_layout(rows)
        if header_position is None:
            continue
        headers = rows[header_position][1]
        if structure_index is not None:
            has_structure_candidate = True
            expected_width = len(headers)
            section_width = expected_width
            repaired_rows: list[tuple[int, list[str]]] = []
            for row_number, values in rows:
                if (
                    row_number > rows[header_position][0]
                    and _column_index(values, _STRUCTURE_ALIASES) is not None
                ):
                    section_width = len(values)
                    repaired_rows.append((row_number, values))
                    continue
                if (
                    row_number <= rows[header_position][0]
                    or len(values) <= section_width
                ):
                    repaired_rows.append((row_number, values))
                    continue
                extra_fields = len(values) - section_width
                end = structure_index + extra_fields + 1
                if end <= len(values):
                    values = (
                        values[:structure_index]
                        + [delimiter.join(values[structure_index:end])]
                        + values[end:]
                    )
                repaired_rows.append((row_number, values))
            rows = repaired_rows
        score = (
            int(structure_index is not None),
            int(label_index is not None),
            len(headers),
            -preference,
        )
        candidates.append((score, rows))
    if parse_errors and not has_structure_candidate:
        return _inspection_result(
            content_class="uninspected",
            inspection_status="inspection_failed",
            detected_format="csv",
            issues=[_issue(
                "malformed_delimited_text",
                "The delimited source contains malformed quoting or separators.",
            )],
        )
    if not candidates:
        return None
    _, rows = max(candidates, key=lambda candidate: candidate[0])
    return _inspect_tables("csv", [(None, rows)])


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_text(element: ElementTree.Element) -> str:
    return "".join(
        descendant.text or ""
        for descendant in element.iter()
        if _xml_local_name(descendant.tag) == "t"
    )


def _relationship_id(element: ElementTree.Element) -> str:
    for attribute, value in element.attrib.items():
        if attribute.startswith("{") and _xml_local_name(attribute) == "id":
            return value
    return ""


def _column_number(reference: str, fallback: int) -> int:
    match = _CELL_REFERENCE.match(reference)
    if match is None:
        return fallback
    number = 0
    for character in match.group(1).upper():
        number = number * 26 + ord(character) - ord("A") + 1
    return number


def _xlsx_cell_value(
    cell: ElementTree.Element, shared_strings: Sequence[str],
) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return _xml_text(cell)
    value = next(
        (
            child.text or ""
            for child in cell
            if _xml_local_name(child.tag) == "v"
        ),
        "",
    )
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError):
            return ""
    return value


def _xlsx_rows(
    worksheet: ElementTree.Element, shared_strings: Sequence[str],
) -> list[tuple[int, list[str]]]:
    rows: list[tuple[int, list[str]]] = []
    fallback_row_number = 1
    for row in worksheet.iter():
        if _xml_local_name(row.tag) != "row":
            continue
        try:
            row_number = int(row.attrib.get("r", fallback_row_number))
        except ValueError:
            row_number = fallback_row_number
        values_by_column: dict[int, str] = {}
        fallback_column = 1
        for cell in row:
            if _xml_local_name(cell.tag) != "c":
                continue
            column = _column_number(cell.attrib.get("r", ""), fallback_column)
            values_by_column[column] = _xlsx_cell_value(cell, shared_strings)
            fallback_column = column + 1
        maximum_column = max(values_by_column, default=0)
        values = [
            values_by_column.get(column, "")
            for column in range(1, maximum_column + 1)
        ]
        rows.append((row_number, values))
        fallback_row_number = row_number + 1
    return rows


def _inspect_xlsx(path: Path) -> dict[str, object]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "xl/workbook.xml" not in names:
                return _inspection_result(
                    content_class="uninspected",
                    inspection_status="unsupported_format",
                    detected_format="zip",
                    issues=[_issue(
                        "xlsx_workbook_not_found",
                        "The ZIP archive does not contain an XLSX workbook.",
                    )],
                )
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            relationships = ElementTree.fromstring(
                archive.read("xl/_rels/workbook.xml.rels")
            )
            targets = {
                relationship.attrib.get("Id", ""): relationship.attrib.get("Target", "")
                for relationship in relationships.iter()
                if _xml_local_name(relationship.tag) == "Relationship"
            }
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in names:
                shared_root = ElementTree.fromstring(
                    archive.read("xl/sharedStrings.xml")
                )
                shared_strings = [
                    _xml_text(item)
                    for item in shared_root
                    if _xml_local_name(item.tag) == "si"
                ]

            tables: list[tuple[str | None, Sequence[tuple[int, list[str]]]]] = []
            for sheet in workbook.iter():
                if _xml_local_name(sheet.tag) != "sheet":
                    continue
                relationship_id = _relationship_id(sheet)
                target = targets.get(relationship_id, "")
                if not target:
                    continue
                worksheet_path = (
                    target.lstrip("/")
                    if target.startswith("/")
                    else posixpath.normpath(posixpath.join("xl", target))
                )
                if worksheet_path not in names:
                    continue
                worksheet = ElementTree.fromstring(archive.read(worksheet_path))
                tables.append((
                    sheet.attrib.get("name", ""),
                    _xlsx_rows(worksheet, shared_strings),
                ))
    except (KeyError, OSError, ElementTree.ParseError, zipfile.BadZipFile) as error:
        return _inspection_result(
            content_class="uninspected",
            inspection_status="inspection_failed",
            detected_format="xlsx",
            issues=[_issue(
                "xlsx_parse_error",
                f"Could not parse the XLSX workbook: {type(error).__name__}.",
            )],
        )
    return _inspect_tables("xlsx", tables)


def _sdf_parts(text: str) -> list[str]:
    records: list[str] = []
    current: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.strip() == "$$$$":
            if any(part.strip() for part in current):
                records.append("".join(current))
            current = []
        else:
            current.append(line)
    if any(part.strip() for part in current):
        records.append("".join(current))
    return records


def _sdf_fields(
    record_text: str,
) -> tuple[str, list[tuple[str, str]], str]:
    lines = record_text.splitlines(keepends=True)
    end_position = next(
        (index for index, line in enumerate(lines) if line.strip() == "M  END"),
        None,
    )
    if end_position is None:
        property_position = next(
            (index for index, line in enumerate(lines) if line.lstrip().startswith(">")),
            len(lines),
        )
        mol_block = "".join(lines[:property_position])
        property_lines = lines[property_position:]
    else:
        mol_block = "".join(lines[:end_position + 1])
        property_lines = lines[end_position + 1:]

    properties: list[tuple[str, str]] = []
    index = 0
    while index < len(property_lines):
        line = property_lines[index].strip()
        match = re.search(r"<([^>]+)>", line) if line.startswith(">") else None
        if match is None:
            index += 1
            continue
        name = match.group(1)
        index += 1
        value_lines: list[str] = []
        while index < len(property_lines) and property_lines[index].strip():
            value_lines.append(property_lines[index].rstrip("\r\n"))
            index += 1
        properties.append((name, "\n".join(value_lines)))
    title = lines[0].rstrip("\r\n").strip() if lines else ""
    return mol_block, properties, title


def _sdf_source_label(
    properties: Sequence[tuple[str, str]], title: str,
) -> str:
    for name, value in properties:
        if _normalize_header(name) in _LABEL_ALIASES and value.strip():
            return value.strip()
    return title


def _molecule_record(
    *, source_label: str, raw_structure_text: str,
    locator: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object] | None]:
    from rdkit import Chem, rdBase

    parse_text = raw_structure_text
    if parse_text and not parse_text.endswith(("\n", "\r")):
        parse_text += "\n"
    with rdBase.BlockLogs():
        molecule = Chem.MolFromMolBlock(
            parse_text, sanitize=True, removeHs=True, strictParsing=True,
        )
    rejection_reason = "" if molecule is not None else "invalid_structure"
    canonical = (
        Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
        if molecule is not None
        else ""
    )
    record = {
        "source_label": source_label,
        "raw_structure_text": raw_structure_text,
        "canonical_isomeric_smiles": canonical,
        "source_locator": dict(locator),
        "record_status": "parsed" if molecule is not None else "rejected",
        "rejection_reason": rejection_reason,
    }
    issue = _record_issue(rejection_reason, locator) if rejection_reason else None
    return record, issue


def _inspect_sdf(text: str) -> dict[str, object]:
    records: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []
    for record_index, record_text in enumerate(_sdf_parts(text), start=1):
        mol_block, properties, title = _sdf_fields(record_text)
        locator = {"record_index": record_index}
        record, issue = _molecule_record(
            source_label=_sdf_source_label(properties, title),
            raw_structure_text=mol_block,
            locator=locator,
        )
        records.append(record)
        if issue is not None:
            issues.append(issue)
    if not records:
        return _inspection_result(
            content_class="uninspected",
            inspection_status="inspection_failed",
            detected_format="sdf",
            issues=[_issue(
                "empty_structure_source",
                "The SDF source contains no molecular records.",
            )],
        )
    return _inspection_result(
        content_class="machine_readable_structure_table",
        inspection_status="inspected",
        detected_format="sdf",
        records=records,
        issues=issues,
    )


def _inspect_mol(text: str) -> dict[str, object]:
    source_label = text.splitlines()[0].strip() if text.splitlines() else ""
    locator = {"record_index": 1}
    record, issue = _molecule_record(
        source_label=source_label,
        raw_structure_text=text,
        locator=locator,
    )
    issues = [issue] if issue is not None else []
    if not source_label:
        issues.insert(0, _issue(
            "source_label_not_found",
            "The MOL record has no source label.",
        ))
    return _inspection_result(
        content_class="machine_readable_structure_table",
        inspection_status="inspected",
        detected_format="mol",
        records=[record],
        issues=issues,
    )


def inspect_structure_source(path: Path) -> dict[str, object]:
    """Inspect and parse a machine-readable structure source by content."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as error:
        return _inspection_result(
            content_class="uninspected",
            inspection_status="inspection_failed",
            detected_format="",
            issues=[_issue(
                "source_read_error",
                f"Could not read the source file: {type(error).__name__}.",
            )],
        )

    if data.startswith(_XLS_MAGIC):
        return _inspection_result(
            content_class="uninspected",
            inspection_status="unsupported_missing_dependency",
            detected_format="xls",
            issues=[_issue(
                "legacy_xls_parser_unavailable",
                "Legacy binary XLS requires an optional parser dependency.",
            )],
        )
    if data.startswith(b"PK"):
        return _inspect_xlsx(path)
    if b"\x00" in data:
        return _inspection_result(
            content_class="uninspected",
            inspection_status="unsupported_format",
            detected_format="binary",
            issues=[_issue(
                "unsupported_binary_format",
                "The binary file format is not supported for inspection.",
            )],
        )

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("gb18030")
        except UnicodeDecodeError:
            try:
                text = data.decode("cp1252")
            except UnicodeDecodeError:
                return _inspection_result(
                    content_class="uninspected",
                    inspection_status="inspection_failed",
                    detected_format="text",
                    issues=[_issue(
                        "text_decode_error",
                        "The source is not valid UTF-8, GB18030, or CP1252 text.",
                    )],
                )
    if any(line.strip() == "$$$$" for line in text.splitlines()):
        return _inspect_sdf(text)
    if any(line.strip() == "M  END" for line in text.splitlines()):
        return _inspect_mol(text)
    delimited_result = _inspect_delimited_text(text)
    if delimited_result is not None:
        return delimited_result
    return _inspection_result(
        content_class="uninspected",
        inspection_status="unsupported_format",
        detected_format="unknown",
        issues=[_issue(
            "unsupported_content",
            "No supported machine-readable table or structure record was detected.",
        )],
    )


def normalize_compound_label(value: object) -> str:
    """Normalize a Paper-local compound label without doing fuzzy matching."""
    raw = str(value or "").strip().casefold()
    if not raw:
        return ""
    raw = raw.replace("–", "-").replace("—", "-")
    raw = re.sub(r"^(?:compound|compd?|cmp)\s*", "", raw)
    raw = re.sub(r"^no\.?\s*", "", raw)
    stereo = re.match(r"^\(([rs])\)-(.+)$", raw)
    if stereo:
        raw = f"{stereo.group(1)}-{stereo.group(2)}"
    racemate = re.match(r"^\((?:\u00b1|\u00a1(?:\u00c0|\u00e0)|\ufffd{1,2})\)-(.+)$", raw)
    if racemate:
        raw = racemate.group(1)
    raw = re.split(r"\s*[\(\[]", raw, maxsplit=1)[0]
    prime_suffix = re.search(r"[′’']+$", raw)
    if prime_suffix:
        raw = raw[:prime_suffix.start()] + "prime" * len(prime_suffix.group())
    numeric_label = re.sub(r"\s+", "", raw)
    if re.fullmatch(r"\d+(?:[-./]\d+)+", numeric_label):
        return numeric_label
    return re.sub(r"[^a-z0-9]+", "", raw)


def _mapped_smiles_molecule(smiles: object):
    from rdkit import Chem, rdBase

    text = str(smiles or "").strip()
    if not text or "\n" in text or "\r" in text:
        return None
    parser_parameters = Chem.SmilesParserParams()
    parser_parameters.parseName = False
    parser_parameters.strictParsing = True
    with rdBase.BlockLogs():
        return Chem.MolFromSmiles(text, parser_parameters)


def _mapped_attachment_sites(molecule) -> tuple[dict[int, tuple[int, int, object]], str]:
    sites: dict[int, tuple[int, int, object]] = {}
    for atom in molecule.GetAtoms():
        if atom.GetAtomicNum() != 0:
            continue
        map_number = atom.GetAtomMapNum()
        if map_number <= 0:
            return {}, "unmapped_attachment_atom"
        if atom.GetDegree() != 1:
            return {}, "attachment_atom_degree_invalid"
        bond = atom.GetBonds()[0]
        neighbor = bond.GetOtherAtom(atom)
        if neighbor.GetAtomicNum() == 0:
            return {}, "attachment_atom_neighbor_invalid"
        if map_number in sites:
            return {}, "duplicate_attachment_map"
        sites[map_number] = (atom.GetIdx(), neighbor.GetIdx(), bond.GetBondType())
    return sites, ""


def _bond_type_name(bond_type: object) -> str:
    return str(bond_type).rsplit(".", 1)[-1].casefold()


def assemble_mapped_fragments(
    scaffold_smiles: str,
    fragments: Mapping[object, str],
) -> dict[str, object]:
    """Assemble complete molecules from atom-mapped scaffold and R fragments.

    Each fragment value contains one dummy atom for the map named by its key.
    The paired dummy atoms are removed after their neighboring atoms are
    connected. Ambiguous maps and incomplete products are rejected rather than
    converted into a potentially misleading SMILES candidate.
    """
    def rejected(reason: str) -> dict[str, object]:
        return {
            "status": "rejected",
            "canonical_isomeric_smiles": MISSING,
            "attachment_maps": [],
            "attachment_mapping": [],
            "rejection_reason": reason,
        }

    scaffold = _mapped_smiles_molecule(scaffold_smiles)
    if scaffold is None:
        return rejected("invalid_scaffold_structure")
    scaffold_sites, scaffold_error = _mapped_attachment_sites(scaffold)
    if scaffold_error == "duplicate_attachment_map":
        return rejected(scaffold_error)
    if scaffold_error:
        return rejected("invalid_scaffold_attachment")

    if not isinstance(fragments, Mapping) or not fragments:
        return rejected("fragment_map_mismatch")
    requested_maps: set[int] = set()
    normalized_fragments: dict[int, str] = {}
    for raw_map, smiles in fragments.items():
        try:
            map_number = int(str(raw_map).strip())
        except (TypeError, ValueError):
            return rejected("fragment_map_mismatch")
        if map_number <= 0 or map_number in requested_maps:
            return rejected("duplicate_attachment_map")
        requested_maps.add(map_number)
        normalized_fragments[map_number] = str(smiles or "")

    if not scaffold_sites:
        return rejected("scaffold_attachment_map_not_found")
    if set(scaffold_sites) != requested_maps:
        return rejected("attachment_map_mismatch")

    fragment_molecules: dict[int, object] = {}
    fragment_sites: dict[int, dict[int, tuple[int, int, object]]] = {}
    for map_number, smiles in normalized_fragments.items():
        molecule = _mapped_smiles_molecule(smiles)
        if molecule is None:
            return rejected("invalid_fragment_structure")
        sites, error = _mapped_attachment_sites(molecule)
        if error == "duplicate_attachment_map":
            return rejected(error)
        if error:
            return rejected(
                "unresolved_fragment_attachment"
                if error == "attachment_atom_neighbor_invalid"
                else "invalid_fragment_attachment"
            )
        if set(sites) != {map_number}:
            has_direct_dummy_bond = any(
                atom.GetAtomicNum() == 0
                and any(neighbor.GetAtomicNum() == 0 for neighbor in atom.GetNeighbors())
                for atom in molecule.GetAtoms()
            )
            return rejected(
                "unresolved_fragment_attachment"
                if has_direct_dummy_bond else "fragment_map_mismatch"
            )
        fragment_molecules[map_number] = molecule
        fragment_sites[map_number] = sites

    from rdkit import Chem, rdBase

    combined = scaffold
    offsets: dict[int, int] = {}
    for map_number in sorted(normalized_fragments):
        offsets[map_number] = combined.GetNumAtoms()
        combined = Chem.CombineMols(combined, fragment_molecules[map_number])
    attachment_mapping: list[dict[str, object]] = []
    for map_number in sorted(normalized_fragments):
        scaffold_dummy, scaffold_neighbor, scaffold_bond = scaffold_sites[map_number]
        fragment_dummy, fragment_neighbor, fragment_bond = fragment_sites[map_number][map_number]
        fragment_dummy += offsets[map_number]
        fragment_neighbor += offsets[map_number]
        if scaffold_bond != fragment_bond and scaffold_bond != Chem.BondType.SINGLE and fragment_bond != Chem.BondType.SINGLE:
            return rejected("attachment_bond_type_mismatch")
        bond_type = (
            scaffold_bond
            if scaffold_bond != Chem.BondType.SINGLE
            else fragment_bond
        )
        attachment_mapping.append({
            "map": str(map_number),
            "scaffold_neighbor_atom": scaffold_neighbor,
            "fragment_neighbor_atom": fragment_neighbor,
            "bond_type": _bond_type_name(bond_type),
        })

    try:
        with rdBase.BlockLogs():
            molecule = Chem.molzip(combined)
            Chem.SanitizeMol(molecule)
    except Exception:
        return rejected("attachment_bond_addition_failed")
    if any(atom.GetAtomicNum() == 0 for atom in molecule.GetAtoms()):
        return rejected("unresolved_assembled_attachment")
    if len(Chem.GetMolFrags(molecule)) != 1:
        return rejected("disconnected_assembled_structure")
    return {
        "status": "assembled",
        "canonical_isomeric_smiles": Chem.MolToSmiles(
            molecule, canonical=True, isomericSmiles=True,
        ),
        "attachment_maps": [str(map_number) for map_number in sorted(normalized_fragments)],
        "attachment_mapping": attachment_mapping,
        "rejection_reason": "",
    }


def source_stereochemistry_status(smiles: object) -> str:
    """Report whether a source graph encodes its real potential stereo.

    RDKit can also report non-tetrahedral atom stereo such as square-planar
    possibilities for graphs where that is not a source-supported molecular
    claim.  The publication gate therefore only treats unassigned tetrahedral
    atoms and double bonds as actionable source ambiguity.
    """
    molecule = _mapped_smiles_molecule(smiles)
    if molecule is None:
        return "source_unspecified"

    from rdkit import Chem

    has_unassigned_real_stereo = any(
        stereo.specified == Chem.StereoSpecified.Unspecified
        and str(stereo.type) in {"Atom_Tetrahedral", "Bond_Double"}
        for stereo in Chem.FindPotentialStereo(
            molecule, cleanIt=True, flagPossible=True,
        )
    )
    return (
        "source_unspecified"
        if has_unassigned_real_stereo
        else "source_encoded"
    )


def validate_structure_candidate(
    candidate: Mapping[str, object],
) -> dict[str, object]:
    """Validate a work candidate without treating RDKit validity as review."""
    result: dict[str, object] = {
        "rdkit_status": "invalid",
        "canonical_isomeric_smiles": MISSING,
        "confirmation_eligible": False,
        "confirmation_reason": "invalid_structure",
    }
    raw_smiles = str(
        candidate.get("canonical_isomeric_smiles")
        or candidate.get("canonical_smiles")
        or ""
    ).strip()
    molecule = _mapped_smiles_molecule(raw_smiles)
    if molecule is None:
        return result

    from rdkit import Chem

    result["rdkit_status"] = "valid"
    result["canonical_isomeric_smiles"] = Chem.MolToSmiles(
        molecule, canonical=True, isomericSmiles=True,
    )
    if any(atom.GetAtomicNum() == 0 for atom in molecule.GetAtoms()):
        result["confirmation_reason"] = "unresolved_dummy_atom"
        return result
    if any(atom.GetNumRadicalElectrons() for atom in molecule.GetAtoms()):
        result["confirmation_reason"] = "unresolved_radical"
        return result
    if len(Chem.GetMolFrags(molecule)) != 1:
        result["confirmation_reason"] = (
            "mixture_or_salt_requires_component_selection"
        )
        return result
    if str(candidate.get("record_status") or "") != "parsed":
        result["confirmation_reason"] = "source_record_not_parsed"
        return result
    reconstruction_method = str(
        candidate.get("reconstruction_method") or ""
    )
    if reconstruction_method in {"mapped_fragment_assembly", "r_group_expansion"}:
        if str(candidate.get("reconstruction_status") or "") not in {
            "assembled", "confirmed",
        }:
            result["confirmation_reason"] = "reconstruction_not_completed"
            return result
        audit_fields = (
            "scaffold_smiles", "r_group_assignments", "attachment_mapping",
        )
        if any(
            str(candidate.get(field) or "").strip() in {"", MISSING}
            for field in audit_fields
        ):
            result["confirmation_reason"] = "reconstruction_audit_incomplete"
            return result
    if reconstruction_method in {
        "direct_source_structure",
        "direct_external_identifier_structure",
        "reviewed_complete_structure",
        "r_group_expansion",
        "source_error_correction",
    }:
        raw_structure = str(candidate.get("raw_structure_text") or "").strip()
        raw_canonical, _ = _canonicalize_smiles(raw_structure)
        if not raw_canonical and "M  END" in raw_structure:
            parse_text = raw_structure
            if not parse_text.endswith(("\n", "\r")):
                parse_text += "\n"
            with rdBase.BlockLogs():
                source_molecule = Chem.MolFromMolBlock(
                    parse_text, sanitize=True, removeHs=True,
                    strictParsing=True,
                )
            if source_molecule is not None:
                raw_canonical = Chem.MolToSmiles(
                    source_molecule, canonical=True, isomericSmiles=True,
                )
        if raw_canonical != result["canonical_isomeric_smiles"]:
            result["confirmation_reason"] = "source_structure_mismatch"
            return result
    elif reconstruction_method == "explicit_component_selection":
        if str(candidate.get("component_selection_status") or "") != (
            "explicit_component_selected"
        ):
            result["confirmation_reason"] = "component_selection_not_explicit"
            return result
        source_molecule = _mapped_smiles_molecule(
            candidate.get("raw_structure_text")
        )
        if source_molecule is None or len(Chem.GetMolFrags(source_molecule)) < 2:
            result["confirmation_reason"] = "source_structure_mismatch"
            return result
        source_components = {
            Chem.MolToSmiles(
                component, canonical=True, isomericSmiles=True,
            )
            for component in Chem.GetMolFrags(source_molecule, asMols=True)
        }
        if result["canonical_isomeric_smiles"] not in source_components:
            result["confirmation_reason"] = "source_structure_mismatch"
            return result
    if str(candidate.get("source_match_status") or "") == (
        "source_structure_mismatch"
    ):
        result["confirmation_reason"] = "source_structure_mismatch"
        return result
    if str(candidate.get("binding_status") or "") != "matched":
        result["confirmation_reason"] = "unambiguous_entity_binding_required"
        return result
    stereochemistry_status = str(
        candidate.get("stereochemistry_status") or ""
    )
    if stereochemistry_status in {
        "unsupported", "ambiguous", "inferred_without_source",
    }:
        result["confirmation_reason"] = "unsupported_stereochemistry"
        return result
    if (
        stereochemistry_status == "source_unspecified"
        and reconstruction_method == "direct_source_structure"
        and source_stereochemistry_status(
            result["canonical_isomeric_smiles"]
        ) == "source_unspecified"
    ):
        result["confirmation_reason"] = "unsupported_stereochemistry"
        return result
    if str(candidate.get("candidate_status") or "") != "candidate_ready":
        result["confirmation_reason"] = "candidate_not_ready"
        return result
    if not str(candidate.get("compound_entity_id") or "").strip() or str(
        candidate.get("compound_entity_id")
    ).strip() == MISSING:
        result["confirmation_reason"] = "compound_entity_id_required"
        return result
    source_file = str(candidate.get("structure_source_file") or "").strip()
    source_locator = str(candidate.get("structure_source_locator") or "").strip()
    if source_file in {"", MISSING} or source_locator in {"", MISSING}:
        result["confirmation_reason"] = "source_locator_incomplete"
        return result
    if str(candidate.get("source_match_status") or "") not in _CONFIRMABLE_SOURCE_MATCHES:
        result["confirmation_reason"] = "source_graph_match_required"
        return result
    if str(candidate.get("review_decision") or "") != "accept":
        result["confirmation_reason"] = "explicit_acceptance_required"
        return result
    result["confirmation_eligible"] = True
    result["confirmation_reason"] = "eligible"
    return result


def _confirmed_structure_key(row: Mapping[str, object]) -> tuple[str, str]:
    paper_id = str(row.get("paper_id") or "").strip()
    normalized_label = normalize_compound_label(
        row.get("normalized_label") or row.get("compound_label")
    )
    return paper_id, normalized_label


def _confirmed_row_from_candidate(
    candidate: Mapping[str, object], validated: Mapping[str, object],
) -> dict[str, str]:
    from rdkit import rdBase

    paper_id, normalized_label = _confirmed_structure_key(candidate)
    return {
        "confirmed_structure_id": f"CONF-{paper_id}-{normalized_label}",
        "paper_id": paper_id,
        "compound_entity_id": str(candidate.get("compound_entity_id") or MISSING),
        "compound_label": str(candidate.get("compound_label") or normalized_label),
        "normalized_label": normalized_label,
        "canonical_isomeric_smiles": str(validated["canonical_isomeric_smiles"]),
        "confirmation_status": "structure_confirmed",
        "structure_review_status": "structure_confirmed",
        "structure_source_type": str(candidate.get("structure_source_type") or MISSING),
        "structure_source_file": str(candidate.get("structure_source_file") or MISSING),
        "structure_source_locator": str(candidate.get("structure_source_locator") or MISSING),
        "reconstruction_method": str(candidate.get("reconstruction_method") or MISSING),
        "scaffold_smiles": str(candidate.get("scaffold_smiles") or MISSING),
        "r_group_assignments": str(candidate.get("r_group_assignments") or MISSING),
        "attachment_mapping": str(candidate.get("attachment_mapping") or MISSING),
        "rdkit_version": rdBase.rdkitVersion,
        "accepted_work_row_id": str(candidate.get("work_row_id") or MISSING),
    }


def select_confirmed_structures(
    work_rows: Iterable[Mapping[str, object]],
    *,
    existing_rows: Iterable[Mapping[str, object]] = (),
) -> list[dict[str, str]]:
    """Select authoritative structures while preserving existing confirmations."""
    current_work_rows = list(work_rows)
    current_work_ids = {
        str(row.get("work_row_id") or "").strip()
        for row in current_work_rows
        if str(row.get("work_row_id") or "").strip()
    }
    existing_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in existing_rows:
        if str(row.get("confirmation_status") or "") != "structure_confirmed":
            continue
        molecule = _mapped_smiles_molecule(
            row.get("canonical_isomeric_smiles")
            or row.get("canonical_smiles")
        )
        if molecule is None:
            continue
        from rdkit import Chem
        if (
            len(Chem.GetMolFrags(molecule)) != 1
            or any(
                atom.GetAtomicNum() == 0 or atom.GetNumRadicalElectrons()
                for atom in molecule.GetAtoms()
            )
        ):
            continue
        key = _confirmed_structure_key(row)
        if not all(key):
            continue
        normalized = {str(field): str(value) for field, value in row.items()}
        previous = existing_by_key.get(key)
        if previous is not None and previous != normalized:
            raise ValueError(
                "conflicting existing confirmed structures for "
                f"{key[0]}/{key[1]}"
            )
        existing_by_key[key] = normalized

    candidates_by_key: dict[
        tuple[str, str], list[tuple[Mapping[str, object], dict[str, object]]]
    ] = defaultdict(list)
    for row in current_work_rows:
        key = _confirmed_structure_key(row)
        if not all(key):
            continue
        validated = validate_structure_candidate(row)
        if validated["confirmation_eligible"]:
            candidates_by_key[key].append((row, validated))

    output: dict[tuple[str, str], dict[str, str]] = dict(existing_by_key)
    for key, candidates in candidates_by_key.items():
        existing = existing_by_key.get(key)
        by_smiles: dict[
            str, list[tuple[Mapping[str, object], dict[str, object]]]
        ] = defaultdict(list)
        for candidate, validated in candidates:
            by_smiles[str(validated["canonical_isomeric_smiles"])].append(
                (candidate, validated)
            )

        explicit_replacements = [
            pair
            for pair in candidates
            if str(pair[0].get("replacement_decision") or "")
            == "explicit_replace"
        ]
        selected: tuple[Mapping[str, object], dict[str, object]] | None = None
        if existing is not None:
            if explicit_replacements:
                replacement_smiles = {
                    str(validated["canonical_isomeric_smiles"])
                    for _, validated in explicit_replacements
                }
                if len(replacement_smiles) == 1:
                    selected = sorted(
                        explicit_replacements,
                        key=lambda pair: str(pair[0].get("work_row_id") or ""),
                    )[0]
            elif str(existing.get("accepted_work_row_id") or "") not in (
                current_work_ids
            ):
                same_structure_candidates = by_smiles.get(
                    str(existing.get("canonical_isomeric_smiles") or ""), []
                )
                if same_structure_candidates:
                    selected = sorted(
                        same_structure_candidates,
                        key=lambda pair: str(pair[0].get("work_row_id") or ""),
                    )[0]
            if selected is None:
                continue
        elif len(by_smiles) == 1:
            same_structure_candidates = next(iter(by_smiles.values()))
            selected = sorted(
                same_structure_candidates,
                key=lambda pair: str(pair[0].get("work_row_id") or ""),
            )[0]
        if selected is not None:
            output[key] = _confirmed_row_from_candidate(*selected)
    return [output[key] for key in sorted(output)]


def _source_locator_text(locator: object) -> str:
    if isinstance(locator, Mapping):
        return ";".join(
            f"{key}={value}"
            for key, value in locator.items()
            if str(value).strip()
        ) or MISSING
    value = str(locator or "").strip()
    return value or MISSING


def _entity_label(row: Mapping[str, object]) -> str:
    return normalize_compound_label(
        row.get("normalized_label")
        or row.get("compound_label")
        or row.get("display_label")
    )


def bind_structure_records(
    *,
    paper_id: str,
    entity_rows: Iterable[Mapping[str, object]],
    source_records: Iterable[Mapping[str, object]],
    source_id: str = "",
    source_file: str = "",
    source_type: str = "machine_readable_structure_source",
) -> list[dict[str, str]]:
    """Bind inspected source records to unique entities in one Paper namespace.

    This function deliberately emits a row for every source record. A parsed
    SMILES is only a candidate when its source label maps one-to-one and the
    source record itself is valid; no confirmation decision is made here.
    """
    local_paper_id = str(paper_id or "").strip()
    entities_by_label: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for entity in entity_rows:
        if str(entity.get("paper_id") or "").strip() != local_paper_id:
            continue
        label = _entity_label(entity)
        if label:
            entities_by_label[label].append(entity)

    materialized_records = [dict(record) for record in source_records]
    source_counts: Counter[str] = Counter(
        normalize_compound_label(record.get("source_label"))
        for record in materialized_records
        if normalize_compound_label(record.get("source_label"))
    )
    output: list[dict[str, str]] = []
    for record in materialized_records:
        source_label = str(record.get("source_label") or "").strip()
        normalized_label = normalize_compound_label(source_label)
        record_status = str(record.get("record_status") or "").strip()
        rejection_reason = str(record.get("rejection_reason") or "").strip()
        canonical = str(record.get("canonical_isomeric_smiles") or "").strip()
        matching_entities = entities_by_label.get(normalized_label, [])
        binding_status = "matched"
        binding_method = "exact_label"
        binding_reason = "exact_label_match"
        candidate_status = "candidate_ready"
        compound_entity_id = MISSING
        compound_label = normalized_label or MISSING

        if not normalized_label:
            binding_status = "missing_source_label"
            binding_method = MISSING
            binding_reason = "source_label_not_found"
            candidate_status = "not_ready"
        elif record_status != "parsed" or not canonical:
            binding_status = "invalid_structure"
            binding_method = MISSING
            binding_reason = rejection_reason or "source_record_not_parsed"
            candidate_status = "not_ready"
        elif len(matching_entities) == 0:
            binding_status = "unmatched_label"
            binding_method = MISSING
            binding_reason = "source_label_not_found_in_paper"
            candidate_status = "not_ready"
        elif len(matching_entities) > 1:
            binding_status = "duplicate_entity_label"
            binding_method = MISSING
            binding_reason = "multiple_entities_for_source_label"
            candidate_status = "not_ready"
        elif source_counts[normalized_label] > 1:
            binding_status = "duplicate_source_records"
            binding_method = MISSING
            binding_reason = "multiple_source_records_for_label"
            candidate_status = "not_ready"
        else:
            entity = matching_entities[0]
            compound_entity_id = str(entity.get("compound_entity_id") or MISSING)
            compound_label = str(
                entity.get("normalized_label") or normalized_label
            )
            if source_label.casefold() != normalized_label:
                binding_method = "qualified_label_normalized"
                binding_reason = "normalized_label_match"

        locator = _source_locator_text(record.get("source_locator"))
        output.append({
            "paper_id": local_paper_id,
            "compound_entity_id": compound_entity_id,
            "compound_label": compound_label,
            "source_label": source_label or MISSING,
            "normalized_label": normalized_label or MISSING,
            "canonical_isomeric_smiles": canonical or MISSING,
            "raw_structure_text": str(record.get("raw_structure_text") or MISSING),
            "source_id": str(source_id or MISSING),
            "source_file": str(source_file or MISSING),
            "source_locator": locator,
            "record_status": record_status or MISSING,
            "rejection_reason": rejection_reason or MISSING,
            "binding_status": binding_status,
            "binding_method": binding_method,
            "binding_reason": binding_reason,
            "candidate_status": candidate_status,
            "structure_source_type": source_type or MISSING,
            "structure_source_file": str(source_file or MISSING),
            "structure_source_locator": locator,
            "confirmation_status": "pending",
            "reconstruction_status": "not_started",
            "reconstruction_reason": MISSING,
        })
    return output


def normalize_doi(value: object) -> str:
    """Return a lowercase DOI only when the complete value is DOI-shaped."""
    raw = str(value or "").strip()
    normalized = _DOI_PREFIX.sub("", raw, count=1).strip().lower()
    return normalized if _DOI.fullmatch(normalized) else ""


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Calculate the SHA-256 checksum of a local file."""
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
        raise TypeError("chunk_size must be an integer")
    if chunk_size < 1:
        raise ValueError("chunk_size must be greater than zero")
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_csv(
    path: Path,
    rows: Iterable[Mapping[str, object]],
    *,
    fieldnames: Sequence[str] = MANIFEST_FIELDS,
) -> None:
    """Replace a CSV only after its complete temporary file is written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            writer = csv.DictWriter(
                handle,
                fieldnames=list(fieldnames),
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def atomic_write_json(path: Path, value: object) -> None:
    """Replace a JSON file only after serialization completes successfully."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _search_results(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, Mapping):
        payload = payload.get("items", payload.get("results", []))
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        return []
    return [item for item in payload if isinstance(item, Mapping)]


def _safe_source_name(value: object, file_id: str) -> str:
    raw_name = _optional_text(value).replace("\\", "/").rsplit("/", 1)[-1]
    name = _INVALID_FILENAME.sub("_", raw_name).rstrip(". ")
    if not name or name in {".", ".."}:
        name = f"figshare_file_{file_id}"
    suffix = Path(name).suffix
    stem = name[:-len(suffix)] if suffix else name
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    maximum_stem_length = max(1, _MAX_SOURCE_NAME_LENGTH - len(suffix))
    return f"{stem[:maximum_stem_length]}{suffix}"


def _optional_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _safe_component(value: object, *, numeric: bool = False) -> str:
    component = _optional_text(value)
    pattern = _NUMERIC_ID if numeric else _SAFE_COMPONENT
    if component in {"", ".", ".."} or pattern.fullmatch(component) is None:
        return ""
    return component


def _source_md5(file_payload: Mapping[str, object]) -> str:
    for candidate in (
        file_payload.get("computed_md5"),
        file_payload.get("supplied_md5"),
    ):
        value = _optional_text(candidate).lower()
        if _MD5.fullmatch(value):
            return value
    return ""


def _sort_key(row: Mapping[str, object]) -> tuple[str, ...]:
    paper_id = _optional_text(row.get("paper_id"))
    source_file = _optional_text(row.get("source_file"))
    article_id = _optional_text(row.get("article_id"))
    file_id = _optional_text(row.get("file_id"))
    return (
        paper_id.casefold(), paper_id,
        _optional_text(row.get("doi")),
        article_id.zfill(20), article_id,
        source_file.casefold(), source_file,
        file_id.zfill(20), file_id,
    )


def _contained_local_path(
    root: Path, paper_id: str, article_id: str, local_name: str,
) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / paper_id / article_id / local_name).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("source local path escapes download root") from error
    return candidate


def build_source_manifest_rows(
    papers: Iterable[Mapping[str, object]],
    search_payloads: Mapping[object, object],
    article_detail_payloads: Mapping[object, Mapping[str, object]],
    *,
    download_root: Path = DEFAULT_DOWNLOAD_ROOT,
) -> list[dict[str, str]]:
    """Convert injected Figshare payloads into deterministic pending rows."""
    searches_by_doi: dict[str, list[Mapping[str, object]]] = {}
    for raw_doi, payload in search_payloads.items():
        doi = normalize_doi(raw_doi)
        if doi:
            searches_by_doi.setdefault(doi, []).extend(_search_results(payload))

    details_by_id: dict[str, Mapping[str, object]] = {}
    for raw_article_id, detail in article_detail_payloads.items():
        article_id = _safe_component(raw_article_id, numeric=True)
        if not article_id or not isinstance(detail, Mapping):
            continue
        previous_detail = details_by_id.get(article_id)
        if previous_detail is not None and previous_detail != detail:
            raise ValueError(
                f"conflicting duplicate article detail identifier: {article_id}"
            )
        details_by_id[article_id] = detail
    root = Path(download_root)
    rows_by_key: dict[tuple[str, str, str], dict[str, str]] = {}

    for paper in papers:
        paper_id = _safe_component(paper.get("paper_id"))
        doi = normalize_doi(paper.get("doi"))
        if not paper_id or not doi:
            continue
        for search_result in searches_by_doi.get(doi, []):
            result_doi_value = search_result.get("resource_doi")
            if result_doi_value and normalize_doi(result_doi_value) != doi:
                continue
            article_id = _safe_component(search_result.get("id"), numeric=True)
            detail = details_by_id.get(article_id)
            if not article_id or detail is None:
                continue
            files = detail.get("files", [])
            if not isinstance(files, Sequence) or isinstance(files, (str, bytes)):
                continue
            for file_payload in files:
                if not isinstance(file_payload, Mapping):
                    continue
                file_id = _safe_component(file_payload.get("id"), numeric=True)
                if not file_id:
                    continue
                source_file = _safe_source_name(file_payload.get("name"), file_id)
                extension = Path(source_file).suffix.lower().lstrip(".")
                local_name = f"{file_id}_{source_file}"
                local_path = _contained_local_path(
                    root, paper_id, article_id, local_name,
                )
                row = {
                    "source_id": f"figshare:{article_id}:{file_id}",
                    "paper_id": paper_id,
                    "doi": doi,
                    "article_id": article_id,
                    "file_id": file_id,
                    "source_file": source_file,
                    "download_url": _optional_text(file_payload.get("download_url")),
                    "extension": extension,
                    "content_class": "uninspected",
                    "size_bytes": _optional_text(file_payload.get("size")),
                    "source_md5": _source_md5(file_payload),
                    "local_path": str(local_path),
                    "sha256": "",
                    "download_status": "pending",
                    "inspection_status": "pending",
                }
                row_key = (paper_id, article_id, file_id)
                previous = rows_by_key.get(row_key)
                if previous is not None and previous != row:
                    raise ValueError(
                        "conflicting duplicate Figshare source identifier: "
                        f"{paper_id}/{article_id}/{file_id}"
                    )
                rows_by_key[row_key] = row

    return sorted(rows_by_key.values(), key=_sort_key)


def _post_json(url: str, payload: Mapping[str, object]) -> object:
    import urllib.request

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "lineage-structure-reconstruction/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def _get_json(url: str) -> object:
    import urllib.request

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "lineage-structure-reconstruction/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def _fetch_bytes(url: str) -> bytes:
    import urllib.request

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "lineage-structure-reconstruction/1.0"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def discover_figshare_source_rows(
    papers: Iterable[Mapping[str, object]],
    *,
    post_json=None,
    get_json=None,
    download_root: Path = DEFAULT_DOWNLOAD_ROOT,
) -> list[dict[str, str]]:
    """Discover every exact DOI-matched Figshare article and attachment."""
    paper_rows = [dict(paper) for paper in papers]
    post = post_json or _post_json
    get = get_json or _get_json
    search_payloads: dict[str, object] = {}
    article_details: dict[str, Mapping[str, object]] = {}
    dois = sorted({
        normalize_doi(paper.get("doi"))
        for paper in paper_rows
        if normalize_doi(paper.get("doi"))
    })
    for doi in dois:
        search_result = post(
            FIGSHARE_SEARCH_URL,
            {"resource_doi": doi, "limit": 100},
        )
        search_payloads[doi] = search_result
        exact_articles = sorted(
            (
                item for item in _search_results(search_result)
                if normalize_doi(item.get("resource_doi")) == doi
                and _safe_component(item.get("id"), numeric=True)
            ),
            key=lambda item: int(str(item["id"])),
        )
        for article in exact_articles:
            article_id = str(article["id"])
            if article_id in article_details:
                continue
            detail_url = str(
                article.get("url")
                or f"https://api.figshare.com/v2/articles/{article_id}"
            )
            detail = get(detail_url)
            if isinstance(detail, Mapping):
                article_details[article_id] = detail
    return build_source_manifest_rows(
        paper_rows,
        search_payloads,
        article_details,
        download_root=download_root,
    )


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def download_source_manifest_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    fetch_bytes=None,
    download_root: Path = DEFAULT_DOWNLOAD_ROOT,
    eligible_extensions: Iterable[str] = _MACHINE_SOURCE_EXTENSIONS,
) -> list[dict[str, str]]:
    """Download machine-readable candidates and verify size and checksum."""
    fetch = fetch_bytes or _fetch_bytes
    root = Path(download_root).resolve()
    eligible = {
        str(extension).casefold().lstrip(".")
        for extension in eligible_extensions
    }
    output: list[dict[str, str]] = []
    for raw_row in rows:
        row = {
            field: _optional_text(raw_row.get(field))
            for field in MANIFEST_FIELDS
        }
        if row["extension"].casefold() not in eligible:
            if row["download_status"] == "pending":
                row["download_status"] = "deferred"
            output.append(row)
            continue
        local_path = Path(row["local_path"]).resolve()
        try:
            local_path.relative_to(root)
        except ValueError:
            row["download_status"] = "invalid_local_path"
            output.append(row)
            continue
        if not row["download_url"]:
            row["download_status"] = "missing_download_url"
            output.append(row)
            continue
        try:
            data = fetch(row["download_url"])
        except Exception as error:
            row["download_status"] = f"download_failed:{type(error).__name__}"
            output.append(row)
            continue
        if not isinstance(data, bytes):
            row["download_status"] = "download_failed:non_bytes_response"
            output.append(row)
            continue
        if row["size_bytes"]:
            try:
                expected_size = int(row["size_bytes"])
            except ValueError:
                expected_size = -1
            if expected_size >= 0 and len(data) != expected_size:
                row["download_status"] = "size_mismatch"
                output.append(row)
                continue
        if (
            row["source_md5"]
            and hashlib.md5(data).hexdigest() != row["source_md5"]
        ):
            row["download_status"] = "checksum_mismatch"
            output.append(row)
            continue
        _atomic_write_bytes(local_path, data)
        row["sha256"] = sha256_file(local_path)
        row["download_status"] = "downloaded"
        output.append(row)
    return sorted(output, key=_sort_key)


def _work_row_id(
    paper_id: str, source_id: str, locator: str, record_index: int,
) -> str:
    digest = hashlib.sha256(
        f"{paper_id}\0{source_id}\0{locator}\0{record_index}".encode("utf-8")
    ).hexdigest()[:16]
    return f"WORK-{paper_id}-{digest}"


def inspect_and_bind_source_rows(
    manifest_rows: Iterable[Mapping[str, object]],
    entity_rows: Iterable[Mapping[str, object]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Inspect downloaded sources and emit auditable Paper-local work rows."""
    entities = [dict(entity) for entity in entity_rows]
    inspected_manifest: list[dict[str, str]] = []
    work_rows: list[dict[str, str]] = []
    for raw_manifest in manifest_rows:
        manifest = {
            field: _optional_text(raw_manifest.get(field))
            for field in MANIFEST_FIELDS
        }
        if manifest["download_status"] != "downloaded":
            inspected_manifest.append(manifest)
            continue
        inspection = inspect_structure_source(Path(manifest["local_path"]))
        manifest["content_class"] = str(inspection["content_class"])
        manifest["inspection_status"] = str(inspection["inspection_status"])
        inspected_manifest.append(manifest)
        if inspection["content_class"] != "machine_readable_structure_table":
            continue
        bound_rows = bind_structure_records(
            paper_id=manifest["paper_id"],
            entity_rows=entities,
            source_records=inspection["records"],
            source_id=manifest["source_id"],
            source_file=manifest["source_file"],
            source_type="machine_readable_structure_source",
        )
        for record_index, bound in enumerate(bound_rows, start=1):
            work = dict(bound)
            work.update({
                "work_row_id": _work_row_id(
                    manifest["paper_id"], manifest["source_id"],
                    bound["source_locator"], record_index,
                ),
                "source_match_status": (
                    "exact_machine_readable_match"
                    if bound["binding_status"] == "matched"
                    else "not_matched"
                ),
                "review_decision": (
                    "accept"
                    if bound["candidate_status"] == "candidate_ready"
                    else "pending"
                ),
                "replacement_decision": "preserve_existing",
                "reconstruction_method": "direct_source_structure",
                "scaffold_smiles": MISSING,
                "r_group_assignments": MISSING,
                "attachment_mapping": MISSING,
                "component_selection_status": "not_needed",
                "stereochemistry_status": source_stereochemistry_status(
                    bound["canonical_isomeric_smiles"]
                ),
            })
            validation = validate_structure_candidate(work)
            work["rdkit_status"] = str(validation["rdkit_status"])
            work["confirmation_reason"] = str(validation["confirmation_reason"])
            if not validation["confirmation_eligible"]:
                work["review_decision"] = "pending"
                if validation["confirmation_reason"] in {
                    "invalid_structure",
                    "unresolved_dummy_atom",
                    "mixture_or_salt_requires_component_selection",
                }:
                    work["candidate_status"] = "not_ready"
            work_rows.append({
                field: _optional_text(work.get(field)) or MISSING
                for field in STRUCTURE_WORK_FIELDS
            })
    return (
        sorted(inspected_manifest, key=_sort_key),
        sorted(work_rows, key=lambda row: (
            row["paper_id"], row["normalized_label"], row["source_id"],
            row["source_locator"], row["work_row_id"],
        )),
    )


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not Path(path).is_file():
        return []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _merge_work_rows(
    existing_rows: Iterable[Mapping[str, object]],
    candidate_rows: Iterable[Mapping[str, object]],
) -> list[dict[str, str]]:
    """Merge work rows by immutable ID and reject conflicting rewrites."""
    merged: dict[str, dict[str, str]] = {}
    for raw_row in [*existing_rows, *candidate_rows]:
        row = {
            field: _optional_text(raw_row.get(field)) or MISSING
            for field in STRUCTURE_WORK_FIELDS
        }
        work_row_id = row["work_row_id"]
        if work_row_id == MISSING:
            raise ValueError("structure work row has no work_row_id")
        previous = merged.get(work_row_id)
        if previous is not None and previous != row:
            raise ValueError(f"conflicting structure work row: {work_row_id}")
        merged[work_row_id] = row
    return sorted(
        merged.values(),
        key=lambda row: (
            row["paper_id"], row["normalized_label"], row["source_id"],
            row["source_locator"], row["work_row_id"],
        ),
    )


def _revalidate_work_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, str]]:
    hard_rejections = {
        "invalid_structure",
        "unresolved_dummy_atom",
        "unresolved_radical",
        "mixture_or_salt_requires_component_selection",
        "source_record_not_parsed",
        "source_structure_mismatch",
        "reconstruction_not_completed",
        "reconstruction_audit_incomplete",
    }
    output: list[dict[str, str]] = []
    for raw_row in rows:
        row = {
            field: _optional_text(raw_row.get(field)) or MISSING
            for field in STRUCTURE_WORK_FIELDS
        }
        prior_confirmation_reason = row["confirmation_reason"]
        validation = validate_structure_candidate(row)
        row["rdkit_status"] = str(validation["rdkit_status"])
        row["confirmation_reason"] = str(validation["confirmation_reason"])
        if (
            prior_confirmation_reason == "candidate_conflict"
            and row["confirmation_reason"] == "candidate_not_ready"
        ):
            # Conflict resolution deliberately makes superseded candidates
            # not-ready.  Preserve that more specific audit reason when the
            # immutable work table is revalidated on an idempotent rerun.
            row["confirmation_reason"] = "candidate_conflict"
        if validation["rdkit_status"] == "valid":
            row["canonical_isomeric_smiles"] = str(
                validation["canonical_isomeric_smiles"]
            )
        if (
            str(validation["confirmation_reason"]) in hard_rejections
            and row.get("review_decision") != "reject"
        ):
            row["candidate_status"] = "not_ready"
            row["review_decision"] = "pending"
        output.append(row)
    return output


def _mark_candidate_conflicts(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, str]]:
    output = [dict(row) for row in rows]
    smiles_by_key: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in output:
        if row.get("confirmation_reason") != "eligible":
            continue
        key = _confirmed_structure_key(row)
        if all(key):
            smiles_by_key[key].add(row["canonical_isomeric_smiles"])
    conflicting_keys = {
        key for key, smiles in smiles_by_key.items() if len(smiles) > 1
    }
    replacement_smiles_by_key: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in output:
        key = _confirmed_structure_key(row)
        if (
            key in conflicting_keys
            and row.get("confirmation_reason") == "eligible"
            and row.get("replacement_decision") == "explicit_replace"
            and row.get("review_decision") == "accept"
        ):
            replacement_smiles_by_key[key].add(row["canonical_isomeric_smiles"])
    for row in output:
        key = _confirmed_structure_key(row)
        replacement_smiles = replacement_smiles_by_key.get(key, set())
        unique_replacement = (
            next(iter(replacement_smiles)) if len(replacement_smiles) == 1 else None
        )
        if (
            row.get("confirmation_reason") == "eligible"
            and key in conflicting_keys
            and row.get("canonical_isomeric_smiles") != unique_replacement
        ):
            row["confirmation_reason"] = "candidate_conflict"
            row["candidate_status"] = "not_ready"
            row["review_decision"] = "pending"
    return output


def build_external_identifier_work_row(
    *,
    paper_id: str,
    compound_entity_id: str,
    compound_label: str,
    query_name: str,
    canonical_isomeric_smiles: str,
    source_url: str,
    source_locator: str,
) -> dict[str, str]:
    """Build an accepted candidate from an exact external identifier match."""
    normalized_label = normalize_compound_label(compound_label)
    locator = _source_locator_text(source_locator)
    source = str(source_url or "").strip()
    raw_smiles = str(canonical_isomeric_smiles or "").strip()
    if not str(paper_id or "").strip() or not normalized_label:
        raise ValueError("paper_id and compound_label are required")
    if not str(compound_entity_id or "").strip():
        raise ValueError("compound_entity_id is required")
    if not str(query_name or "").strip():
        raise ValueError("query_name is required")
    if source in {"", MISSING} or locator == MISSING:
        raise ValueError("external source URL and locator are required")

    row: dict[str, object] = {
        "work_row_id": _work_row_id(
            str(paper_id).strip(), source, locator, 1,
        ),
        "paper_id": str(paper_id).strip(),
        "compound_entity_id": str(compound_entity_id).strip(),
        "compound_label": str(compound_label).strip(),
        "source_label": str(query_name).strip(),
        "normalized_label": normalized_label,
        "canonical_isomeric_smiles": raw_smiles or MISSING,
        "raw_structure_text": raw_smiles or MISSING,
        "source_id": source,
        "source_file": source,
        "source_locator": locator,
        "record_status": "parsed",
        "rejection_reason": MISSING,
        "binding_status": "matched",
        "binding_method": "exact_external_identifier",
        "binding_reason": "exact_external_identifier_match",
        "candidate_status": "candidate_ready",
        "structure_source_type": "external_identifier_source",
        "structure_source_file": source,
        "structure_source_locator": locator,
        "confirmation_status": "pending",
        "reconstruction_status": "not_needed",
        "reconstruction_reason": MISSING,
        "reconstruction_method": "direct_external_identifier_structure",
        "scaffold_smiles": MISSING,
        "r_group_assignments": MISSING,
        "attachment_mapping": MISSING,
        "component_selection_status": "not_needed",
        "stereochemistry_status": "source_encoded",
        "source_match_status": "exact_external_identifier_match",
        "review_decision": "accept",
        "replacement_decision": "preserve_existing",
    }
    validation = validate_structure_candidate(row)
    row["canonical_isomeric_smiles"] = validation["canonical_isomeric_smiles"]
    row["rdkit_status"] = validation["rdkit_status"]
    row["confirmation_reason"] = validation["confirmation_reason"]
    if not validation["confirmation_eligible"]:
        raise ValueError(
            "external identifier candidate is not confirmable: "
            f"{validation['confirmation_reason']}"
        )
    return {
        field: _optional_text(row.get(field)) or MISSING
        for field in STRUCTURE_WORK_FIELDS
    }


def build_source_label_correction_work_row(
    source_work_row: Mapping[str, object],
    *,
    compound_entity_id: str,
    compound_label: str,
    decision_note: str,
) -> dict[str, str]:
    """Bind an Excel-corrupted scientific-notation label to its `e` label."""
    source = {
        field: _optional_text(source_work_row.get(field)) or MISSING
        for field in STRUCTURE_WORK_FIELDS
    }
    target_label = normalize_compound_label(compound_label)
    target_match = re.fullmatch(r"([1-9][0-9]*)e", target_label)
    source_label = source["source_label"]
    if not re.fullmatch(
        r"[0-9]+(?:\.[0-9]+)?[eE][+-]?[0-9]+", source_label,
    ) or target_match is None:
        raise ValueError("source label does not encode target label")
    try:
        source_number = Decimal(source_label)
        target_number = Decimal(target_match.group(1))
    except InvalidOperation as error:
        raise ValueError("source label does not encode target label") from error
    if source_number != target_number:
        raise ValueError("source label does not encode target label")
    if source["record_status"] != "parsed":
        raise ValueError("label correction requires a parsed source row")
    if source["binding_status"] != "unmatched_label":
        raise ValueError("label correction requires an unmatched source label")
    if source["structure_source_type"] != "machine_readable_structure_source":
        raise ValueError("label correction requires a machine-readable source")
    if not str(compound_entity_id or "").strip():
        raise ValueError("compound_entity_id is required")
    if not str(decision_note or "").strip():
        raise ValueError("label correction requires a decision note")

    source["work_row_id"] = _work_row_id(
        source["paper_id"],
        f"{source['source_id']}:reviewed-label-correction-v1:{target_label}",
        source["source_locator"],
        1,
    )
    source.update({
        "compound_entity_id": str(compound_entity_id).strip(),
        "compound_label": str(compound_label).strip(),
        "normalized_label": target_label,
        "binding_status": "matched",
        "binding_method": "audited_source_label_correction",
        "binding_reason": "spreadsheet_scientific_notation_corruption",
        "candidate_status": "candidate_ready",
        "structure_source_type": "reviewed_source_label_correction",
        "confirmation_status": "pending",
        "reconstruction_status": "not_needed",
        "reconstruction_reason": str(decision_note).strip(),
        "reconstruction_method": "direct_source_structure",
        "component_selection_status": "not_needed",
        "source_match_status": "exact_machine_readable_match",
        "review_decision": "accept",
        "replacement_decision": "preserve_existing",
    })
    validation = validate_structure_candidate(source)
    source["canonical_isomeric_smiles"] = str(
        validation["canonical_isomeric_smiles"]
    )
    source["rdkit_status"] = str(validation["rdkit_status"])
    source["confirmation_reason"] = str(validation["confirmation_reason"])
    if not validation["confirmation_eligible"]:
        raise ValueError(
            "label-corrected candidate is not confirmable: "
            f"{validation['confirmation_reason']}"
        )
    return source


def _audit_text(value: object) -> str:
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, (list, tuple)):
        return json.dumps(value, separators=(",", ":"))
    return str(value or "").strip() or MISSING


def build_reviewed_structure_work_row(
    *,
    paper_id: str,
    compound_entity_id: str,
    compound_label: str,
    canonical_isomeric_smiles: str,
    source_id: str,
    source_file: str,
    source_locator: str,
    source_label: str,
    reconstruction_method: str,
    source_match_status: str,
    decision_note: str,
    stereochemistry_status: str = "source_encoded",
    scaffold_smiles: object = MISSING,
    r_group_assignments: object = MISSING,
    attachment_mapping: object = MISSING,
    replacement_decision: str = "preserve_existing",
) -> dict[str, str]:
    """Build an accepted, source-located candidate after graph review."""
    method_to_source_type = {
        "reviewed_complete_structure": "source_figure_reconstruction",
        "r_group_expansion": "r_group_expansion",
        "source_error_correction": "source_error_correction",
    }
    if reconstruction_method not in method_to_source_type:
        raise ValueError("unsupported reviewed reconstruction method")
    if source_match_status not in {
        "exact_complete_structure_match",
        "visual_graph_match",
        "reconstructed_source_graph_match",
    }:
        raise ValueError("unsupported reviewed source match status")
    if replacement_decision not in {"preserve_existing", "explicit_replace"}:
        raise ValueError("unsupported replacement decision")
    normalized_label = normalize_compound_label(compound_label)
    required = {
        "paper_id": paper_id,
        "compound_entity_id": compound_entity_id,
        "compound_label": normalized_label,
        "canonical_isomeric_smiles": canonical_isomeric_smiles,
        "source_id": source_id,
        "source_file": source_file,
        "source_locator": source_locator,
        "source_label": source_label,
        "decision_note": decision_note,
    }
    missing = [name for name, value in required.items() if not str(value or "").strip()]
    if missing:
        raise ValueError(f"reviewed candidate requires {', '.join(missing)}")

    raw_smiles = str(canonical_isomeric_smiles).strip()
    row: dict[str, object] = {
        "work_row_id": _work_row_id(
            str(paper_id).strip(),
            f"{str(source_id).strip()}:{reconstruction_method}:{normalized_label}",
            _source_locator_text(source_locator),
            1,
        ),
        "paper_id": str(paper_id).strip(),
        "compound_entity_id": str(compound_entity_id).strip(),
        "compound_label": str(compound_label).strip(),
        "source_label": str(source_label).strip(),
        "normalized_label": normalized_label,
        "canonical_isomeric_smiles": raw_smiles,
        "raw_structure_text": raw_smiles,
        "source_id": str(source_id).strip(),
        "source_file": str(source_file).strip(),
        "source_locator": _source_locator_text(source_locator),
        "record_status": "parsed",
        "rejection_reason": MISSING,
        "binding_status": "matched",
        "binding_method": "reviewed_paper_local_identity",
        "binding_reason": "source_label_and_locator_reviewed",
        "candidate_status": "candidate_ready",
        "structure_source_type": method_to_source_type[reconstruction_method],
        "structure_source_file": str(source_file).strip(),
        "structure_source_locator": _source_locator_text(source_locator),
        "confirmation_status": "pending",
        "reconstruction_status": "assembled",
        "reconstruction_reason": str(decision_note).strip(),
        "reconstruction_method": reconstruction_method,
        "scaffold_smiles": _audit_text(scaffold_smiles),
        "r_group_assignments": _audit_text(r_group_assignments),
        "attachment_mapping": _audit_text(attachment_mapping),
        "component_selection_status": "not_needed",
        "stereochemistry_status": str(stereochemistry_status).strip(),
        "source_match_status": source_match_status,
        "review_decision": "accept",
        "replacement_decision": replacement_decision,
    }
    validation = validate_structure_candidate(row)
    row["canonical_isomeric_smiles"] = validation["canonical_isomeric_smiles"]
    row["rdkit_status"] = validation["rdkit_status"]
    row["confirmation_reason"] = validation["confirmation_reason"]
    if not validation["confirmation_eligible"]:
        raise ValueError(
            "reviewed candidate is not confirmable: "
            f"{validation['confirmation_reason']}"
        )
    return {
        field: _optional_text(row.get(field)) or MISSING
        for field in STRUCTURE_WORK_FIELDS
    }


def build_component_selection_work_row(
    source_work_row: Mapping[str, object],
    *,
    selected_component_smiles: str,
    decision_note: str,
) -> dict[str, str]:
    """Create an auditable candidate selecting one explicit source component."""
    from rdkit import Chem

    source = {
        field: _optional_text(source_work_row.get(field)) or MISSING
        for field in STRUCTURE_WORK_FIELDS
    }
    if source["binding_status"] != "matched":
        raise ValueError("component selection requires a matched source row")
    if not str(decision_note or "").strip():
        raise ValueError("component selection requires a decision note")
    source_molecule = _mapped_smiles_molecule(source["raw_structure_text"])
    selected_molecule = _mapped_smiles_molecule(selected_component_smiles)
    if source_molecule is None or len(Chem.GetMolFrags(source_molecule)) < 2:
        raise ValueError("source structure is not multicomponent")
    if selected_molecule is None or len(Chem.GetMolFrags(selected_molecule)) != 1:
        raise ValueError("selected structure is not one complete component")
    selected_canonical = Chem.MolToSmiles(
        selected_molecule, canonical=True, isomericSmiles=True,
    )
    source_components = {
        Chem.MolToSmiles(component, canonical=True, isomericSmiles=True)
        for component in Chem.GetMolFrags(source_molecule, asMols=True)
    }
    if selected_canonical not in source_components:
        raise ValueError("selected structure is not an exact component of source")

    source["work_row_id"] = _work_row_id(
        source["paper_id"],
        f"{source['source_id']}:component:{selected_canonical}",
        source["source_locator"],
        1,
    )
    source.update({
        "canonical_isomeric_smiles": selected_canonical,
        "candidate_status": "candidate_ready",
        "structure_source_type": "explicit_component_selection",
        "confirmation_status": "pending",
        "reconstruction_status": "not_needed",
        "reconstruction_reason": str(decision_note).strip(),
        "reconstruction_method": "explicit_component_selection",
        "component_selection_status": "explicit_component_selected",
        "review_decision": "accept",
        "replacement_decision": "preserve_existing",
    })
    validation = validate_structure_candidate(source)
    source["rdkit_status"] = str(validation["rdkit_status"])
    source["confirmation_reason"] = str(validation["confirmation_reason"])
    if not validation["confirmation_eligible"]:
        raise ValueError(
            "component selection candidate is not confirmable: "
            f"{validation['confirmation_reason']}"
        )
    return source


def publish_reviewed_structure_exclusions(
    exclusions: Iterable[Mapping[str, object]],
    *,
    work_path: Path = DEFAULT_WORK_PATH,
    confirmed_path: Path = DEFAULT_CONFIRMED_PATH,
) -> dict[str, list[dict[str, str]]]:
    """Atomically reject source candidates that do not define one molecule.

    Exclusions are intentionally keyed by immutable work-row ID.  They are
    used after source review establishes that an otherwise parseable record is
    a racemate, stereoisomer mixture, or another non-unique experimental
    structure that must not remain in the authoritative single-molecule table.
    """
    requested: dict[str, tuple[str, str]] = {}
    allowed_statuses = {"unsupported", "ambiguous", "inferred_without_source"}
    for raw_exclusion in exclusions:
        work_row_id = str(raw_exclusion.get("work_row_id") or "").strip()
        stereochemistry_status = str(
            raw_exclusion.get("stereochemistry_status") or ""
        ).strip()
        decision_note = str(raw_exclusion.get("decision_note") or "").strip()
        if not work_row_id:
            raise ValueError("structure exclusion requires work_row_id")
        if work_row_id in requested:
            raise ValueError(f"duplicate structure exclusion: {work_row_id}")
        if stereochemistry_status not in allowed_statuses:
            raise ValueError(
                "structure exclusion requires an unsupported or ambiguous "
                "stereochemistry status"
            )
        if not decision_note:
            raise ValueError("structure exclusion requires a decision note")
        requested[work_row_id] = (stereochemistry_status, decision_note)

    work_path = Path(work_path)
    confirmed_path = Path(confirmed_path)
    lock_path = work_path.parent / ".structure-candidate-publication.lock"
    with _publication_lock(lock_path):
        existing_work = _read_csv_rows(work_path)
        rows_by_id = {
            str(row.get("work_row_id") or "").strip(): row
            for row in existing_work
        }
        missing = sorted(set(requested) - set(rows_by_id))
        if missing:
            raise ValueError(
                "structure exclusion work rows not found: " + ", ".join(missing)
            )

        excluded_keys: set[tuple[str, str]] = set()
        updated_rows: list[dict[str, str]] = []
        for raw_row in existing_work:
            row = {
                field: _optional_text(raw_row.get(field)) or MISSING
                for field in STRUCTURE_WORK_FIELDS
            }
            work_row_id = row["work_row_id"]
            if work_row_id in requested:
                stereochemistry_status, decision_note = requested[work_row_id]
                row.update({
                    "candidate_status": "not_ready",
                    "confirmation_status": "pending",
                    "review_decision": "reject",
                    "stereochemistry_status": stereochemistry_status,
                    "reconstruction_reason": decision_note,
                })
                excluded_keys.add(_confirmed_structure_key(row))
            updated_rows.append(row)

        work_rows = _mark_candidate_conflicts(_revalidate_work_rows(updated_rows))
        retained_existing = [
            row for row in _read_csv_rows(confirmed_path)
            if _confirmed_structure_key(row) not in excluded_keys
        ]
        confirmed_rows = select_confirmed_structures(
            work_rows,
            existing_rows=retained_existing,
        )
        atomic_write_csv(
            work_path, work_rows, fieldnames=STRUCTURE_WORK_FIELDS,
        )
        atomic_write_csv(
            confirmed_path,
            confirmed_rows,
            fieldnames=CONFIRMED_STRUCTURE_FIELDS,
        )
    return {"work_rows": work_rows, "confirmed_rows": confirmed_rows}


def publish_reviewed_structure_mismatches(
    mismatches: Iterable[Mapping[str, object]],
    *,
    work_path: Path = DEFAULT_WORK_PATH,
    confirmed_path: Path = DEFAULT_CONFIRMED_PATH,
) -> dict[str, list[dict[str, str]]]:
    """Atomically reject exact rows whose graph conflicts with its source.

    This decision is distinct from an unsupported stereochemical assignment:
    the candidate's molecular connectivity or substituent identity is wrong
    for the paper-local label, even if RDKit can parse the candidate.
    """
    requested: dict[str, tuple[str, str]] = {}
    allowed_statuses = {"unsupported", "ambiguous", "inferred_without_source"}
    for raw_mismatch in mismatches:
        work_row_id = str(raw_mismatch.get("work_row_id") or "").strip()
        stereochemistry_status = str(
            raw_mismatch.get("stereochemistry_status") or ""
        ).strip()
        decision_note = str(raw_mismatch.get("decision_note") or "").strip()
        if not work_row_id:
            raise ValueError("structure mismatch requires work_row_id")
        if work_row_id in requested:
            raise ValueError(f"duplicate structure mismatch: {work_row_id}")
        if stereochemistry_status not in allowed_statuses:
            raise ValueError(
                "structure mismatch requires an unsupported or ambiguous "
                "stereochemistry status"
            )
        if not decision_note:
            raise ValueError("structure mismatch requires a decision note")
        requested[work_row_id] = (stereochemistry_status, decision_note)

    work_path = Path(work_path)
    confirmed_path = Path(confirmed_path)
    lock_path = work_path.parent / ".structure-candidate-publication.lock"
    with _publication_lock(lock_path):
        existing_work = _read_csv_rows(work_path)
        rows_by_id = {
            str(row.get("work_row_id") or "").strip(): row
            for row in existing_work
        }
        missing = sorted(set(requested) - set(rows_by_id))
        if missing:
            raise ValueError(
                "structure mismatch work rows not found: " + ", ".join(missing)
            )

        rejected_keys: set[tuple[str, str]] = set()
        updated_rows: list[dict[str, str]] = []
        for raw_row in existing_work:
            row = {
                field: _optional_text(raw_row.get(field)) or MISSING
                for field in STRUCTURE_WORK_FIELDS
            }
            work_row_id = row["work_row_id"]
            if work_row_id in requested:
                stereochemistry_status, decision_note = requested[work_row_id]
                row.update({
                    "candidate_status": "not_ready",
                    "confirmation_status": "pending",
                    "review_decision": "reject",
                    "stereochemistry_status": stereochemistry_status,
                    "source_match_status": "source_structure_mismatch",
                    "reconstruction_reason": decision_note,
                })
                rejected_keys.add(_confirmed_structure_key(row))
            updated_rows.append(row)

        work_rows = _mark_candidate_conflicts(_revalidate_work_rows(updated_rows))
        retained_existing = [
            row for row in _read_csv_rows(confirmed_path)
            if _confirmed_structure_key(row) not in rejected_keys
        ]
        confirmed_rows = select_confirmed_structures(
            work_rows,
            existing_rows=retained_existing,
        )
        atomic_write_csv(
            work_path, work_rows, fieldnames=STRUCTURE_WORK_FIELDS,
        )
        atomic_write_csv(
            confirmed_path,
            confirmed_rows,
            fieldnames=CONFIRMED_STRUCTURE_FIELDS,
        )
    return {"work_rows": work_rows, "confirmed_rows": confirmed_rows}


def publish_reviewed_structure_candidates(
    candidate_rows: Iterable[Mapping[str, object]],
    *,
    work_path: Path = DEFAULT_WORK_PATH,
    confirmed_path: Path = DEFAULT_CONFIRMED_PATH,
) -> dict[str, list[dict[str, str]]]:
    """Atomically merge reviewed work and rebuild authoritative structures."""
    work_path = Path(work_path)
    confirmed_path = Path(confirmed_path)
    lock_path = work_path.parent / ".structure-candidate-publication.lock"
    with _publication_lock(lock_path):
        work_rows = _mark_candidate_conflicts(_revalidate_work_rows(
            _merge_work_rows(_read_csv_rows(work_path), candidate_rows)
        ))
        confirmed_rows = select_confirmed_structures(
            work_rows,
            existing_rows=_read_csv_rows(confirmed_path),
        )
        atomic_write_csv(
            work_path, work_rows, fieldnames=STRUCTURE_WORK_FIELDS,
        )
        atomic_write_csv(
            confirmed_path,
            confirmed_rows,
            fieldnames=CONFIRMED_STRUCTURE_FIELDS,
        )
    return {"work_rows": work_rows, "confirmed_rows": confirmed_rows}


def run_structure_source_batch(
    papers: Iterable[Mapping[str, object]],
    entity_rows: Iterable[Mapping[str, object]],
    *,
    post_json=None,
    get_json=None,
    fetch_bytes=None,
    reuse_manifest: bool = False,
    download_root: Path = DEFAULT_DOWNLOAD_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    snapshot_path: Path = DEFAULT_SNAPSHOT_PATH,
    work_path: Path = DEFAULT_WORK_PATH,
    confirmed_path: Path = DEFAULT_CONFIRMED_PATH,
    summary_path: Path = DEFAULT_RECONSTRUCTION_SUMMARY_PATH,
) -> dict[str, object]:
    """Serialize publication of the manifest, work, confirmed, and summary snapshot."""
    lock_path = Path(work_path).parent / ".structure-candidate-publication.lock"
    with _publication_lock(lock_path):
        return _run_structure_source_batch_unlocked(
            papers,
            entity_rows,
            post_json=post_json,
            get_json=get_json,
            fetch_bytes=fetch_bytes,
            reuse_manifest=reuse_manifest,
            download_root=download_root,
            manifest_path=manifest_path,
            snapshot_path=snapshot_path,
            work_path=work_path,
            confirmed_path=confirmed_path,
            summary_path=summary_path,
        )


def _run_structure_source_batch_unlocked(
    papers: Iterable[Mapping[str, object]],
    entity_rows: Iterable[Mapping[str, object]],
    *,
    post_json=None,
    get_json=None,
    fetch_bytes=None,
    reuse_manifest: bool = False,
    download_root: Path = DEFAULT_DOWNLOAD_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    snapshot_path: Path = DEFAULT_SNAPSHOT_PATH,
    work_path: Path = DEFAULT_WORK_PATH,
    confirmed_path: Path = DEFAULT_CONFIRMED_PATH,
    summary_path: Path = DEFAULT_RECONSTRUCTION_SUMMARY_PATH,
) -> dict[str, object]:
    """Run source discovery through conservative structure confirmation."""
    paper_rows = [dict(paper) for paper in papers]
    entities = [dict(entity) for entity in entity_rows]
    selected_paper_ids = {
        str(paper.get("paper_id") or "") for paper in paper_rows
        if paper.get("paper_id")
    }
    prior_manifest_rows = _read_csv_rows(manifest_path)
    if reuse_manifest:
        verify_source_manifest_snapshot(
            csv_path=manifest_path, json_path=snapshot_path,
        )
        downloaded = [
            row for row in prior_manifest_rows
            if str(row.get("paper_id") or "") in selected_paper_ids
        ]
        for row in downloaded:
            if str(row.get("download_status") or "") != "downloaded":
                continue
            source_path = Path(str(row.get("local_path") or ""))
            expected_checksum = str(row.get("sha256") or "").strip()
            if (
                not expected_checksum
                or not source_path.is_file()
                or sha256_file(source_path) != expected_checksum
            ):
                raise ValueError(
                    "source file checksum mismatch: "
                    f"{row.get('source_id') or source_path}"
                )
    else:
        discovered = discover_figshare_source_rows(
            paper_rows,
            post_json=post_json,
            get_json=get_json,
            download_root=download_root,
        )
        downloaded = download_source_manifest_rows(
            discovered,
            fetch_bytes=fetch_bytes,
            download_root=download_root,
        )
    inspected_selected_manifest, machine_work_rows = inspect_and_bind_source_rows(
        downloaded, entities,
    )
    preserved_manifest = [
        {
            field: _optional_text(row.get(field))
            for field in MANIFEST_FIELDS
        }
        for row in prior_manifest_rows
        if str(row.get("paper_id") or "") not in selected_paper_ids
    ]
    inspected_manifest = sorted(
        [*preserved_manifest, *inspected_selected_manifest], key=_sort_key,
    )
    prior_work_rows = _read_csv_rows(work_path)
    reviewed_work_rows = [
        row for row in prior_work_rows
        if (
            str(row.get("paper_id") or "") not in selected_paper_ids
            or str(row.get("structure_source_type") or "")
            != "machine_readable_structure_source"
        )
    ]
    work_rows = _mark_candidate_conflicts(_revalidate_work_rows(
        _merge_work_rows(reviewed_work_rows, machine_work_rows)
    ))
    existing_confirmed = _read_csv_rows(confirmed_path)
    confirmed_rows = select_confirmed_structures(
        work_rows,
        existing_rows=existing_confirmed,
    )

    manifest_snapshot = write_source_manifest_snapshot(
        inspected_manifest,
        csv_path=manifest_path,
        json_path=snapshot_path,
    )
    atomic_write_csv(work_path, work_rows, fieldnames=STRUCTURE_WORK_FIELDS)
    atomic_write_csv(
        confirmed_path,
        confirmed_rows,
        fieldnames=CONFIRMED_STRUCTURE_FIELDS,
    )

    confirmed_keys = {
        _confirmed_structure_key(row)
        for row in confirmed_rows
        if str(row.get("confirmation_status") or "") == "structure_confirmed"
    }
    per_paper: dict[str, dict[str, int]] = {}
    for paper_id in sorted(selected_paper_ids):
        local_entities = [
            entity for entity in entities
            if str(entity.get("paper_id") or "") == paper_id
        ]
        local_work = [row for row in work_rows if row["paper_id"] == paper_id]
        local_sources = [
            row for row in inspected_manifest if row["paper_id"] == paper_id
        ]
        confirmed_count = sum(key[0] == paper_id for key in confirmed_keys)
        per_paper[paper_id] = {
            "entity_rows": len(local_entities),
            "source_rows": len(local_sources),
            "work_rows": len(local_work),
            "matched_work_rows": sum(
                row["binding_status"] == "matched" for row in local_work
            ),
            "confirmed_entities": confirmed_count,
            "unresolved_entities": max(0, len(local_entities) - confirmed_count),
        }

    summary: dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paper_rows": len(selected_paper_ids),
        "entity_rows": len(entities),
        "source_rows": len(inspected_manifest),
        "download_status_counts": dict(Counter(
            row["download_status"] for row in inspected_manifest
        )),
        "content_class_counts": dict(Counter(
            row["content_class"] for row in inspected_manifest
        )),
        "inspection_status_counts": dict(Counter(
            row["inspection_status"] for row in inspected_manifest
        )),
        "work_rows": len(work_rows),
        "binding_status_counts": dict(Counter(
            row["binding_status"] for row in work_rows
        )),
        "candidate_status_counts": dict(Counter(
            row["candidate_status"] for row in work_rows
        )),
        "confirmation_reason_counts": dict(Counter(
            row["confirmation_reason"] for row in work_rows
        )),
        "confirmed_rows": len(confirmed_rows),
        "confirmed_selected_entity_rows": sum(
            key[0] in selected_paper_ids for key in confirmed_keys
        ),
        "confirmed_selected_paper_rows": len({
            key[0] for key in confirmed_keys if key[0] in selected_paper_ids
        }),
        "per_paper": per_paper,
    }
    atomic_write_json(summary_path, summary)
    return {
        "manifest": inspected_manifest,
        "manifest_snapshot": manifest_snapshot,
        "work_rows": work_rows,
        "confirmed_rows": confirmed_rows,
        "summary": summary,
    }


@contextmanager
def _publication_lock(path: Path) -> Iterator[None]:
    """Serialize publication; checksum verification detects hard-crash windows."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _staging_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".stage",
    )
    os.close(descriptor)
    Path(name).unlink()
    return Path(name)


def _restore_bytes(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(previous)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def verify_source_manifest_snapshot(
    *, csv_path: Path = DEFAULT_MANIFEST_PATH,
    json_path: Path = DEFAULT_SNAPSHOT_PATH,
) -> dict[str, object]:
    """Load a snapshot only when its recorded CSV checksum still matches."""
    try:
        snapshot = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("source manifest snapshot is unreadable") from error
    if not isinstance(snapshot, dict):
        raise ValueError("source manifest snapshot must be a JSON object")
    recorded_checksum = snapshot.get("manifest_sha256")
    if not isinstance(recorded_checksum, str) or not recorded_checksum:
        raise ValueError("source manifest snapshot has no checksum")
    try:
        actual_checksum = sha256_file(Path(csv_path))
    except OSError as error:
        raise ValueError("source manifest CSV is unreadable") from error
    if actual_checksum != recorded_checksum:
        raise ValueError("source manifest checksum mismatch")
    return snapshot


def write_source_manifest_snapshot(
    rows: Iterable[Mapping[str, object]],
    *,
    csv_path: Path = DEFAULT_MANIFEST_PATH,
    json_path: Path = DEFAULT_SNAPSHOT_PATH,
) -> dict[str, object]:
    """Write a deterministic CSV manifest and its checksummed JSON snapshot."""
    normalized_rows = [
        {field: _optional_text(row.get(field)) for field in MANIFEST_FIELDS}
        for row in rows
    ]
    normalized_rows.sort(key=_sort_key)
    csv_path = Path(csv_path)
    json_path = Path(json_path)
    staged_csv = _staging_path(csv_path)
    staged_json = _staging_path(json_path)
    try:
        atomic_write_csv(staged_csv, normalized_rows, fieldnames=MANIFEST_FIELDS)
        snapshot: dict[str, object] = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "manifest_fields": list(MANIFEST_FIELDS),
            "row_count": len(normalized_rows),
            "manifest_sha256": sha256_file(staged_csv),
            "rows": normalized_rows,
        }
        atomic_write_json(staged_json, snapshot)
        verify_source_manifest_snapshot(csv_path=staged_csv, json_path=staged_json)

        lock_path = csv_path.parent / f".{csv_path.name}.lock"
        with _publication_lock(lock_path):
            previous_csv = csv_path.read_bytes() if csv_path.exists() else None
            previous_json = json_path.read_bytes() if json_path.exists() else None
            try:
                os.replace(staged_csv, csv_path)
                os.replace(staged_json, json_path)
                verify_source_manifest_snapshot(csv_path=csv_path, json_path=json_path)
            except BaseException:
                _restore_bytes(csv_path, previous_csv)
                _restore_bytes(json_path, previous_json)
                raise
        return snapshot
    finally:
        staged_csv.unlink(missing_ok=True)
        staged_json.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--paper-id", action="append", required=True,
        help="Paper ID to process; repeat for each Paper.",
    )
    parser.add_argument(
        "--entities", type=Path,
        default=DEFAULT_AUTO_FILL_DIR / "compound_entities.csv",
    )
    parser.add_argument("--download-root", type=Path, default=DEFAULT_DOWNLOAD_ROOT)
    parser.add_argument(
        "--reuse-manifest", action="store_true",
        help="Reinspect already-downloaded rows without network discovery.",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT_PATH)
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK_PATH)
    parser.add_argument("--confirmed", type=Path, default=DEFAULT_CONFIRMED_PATH)
    parser.add_argument(
        "--summary", type=Path, default=DEFAULT_RECONSTRUCTION_SUMMARY_PATH,
    )
    args = parser.parse_args(argv)

    requested = set(args.paper_id)
    all_entities = _read_csv_rows(args.entities)
    entities = [
        row for row in all_entities if str(row.get("paper_id") or "") in requested
    ]
    found = {str(row.get("paper_id") or "") for row in entities}
    missing = sorted(requested - found)
    if missing:
        parser.error(f"Paper IDs not found in entity table: {', '.join(missing)}")
    papers_by_id: dict[str, dict[str, str]] = {}
    for entity in entities:
        paper_id = str(entity.get("paper_id") or "")
        doi = normalize_doi(entity.get("doi"))
        if not doi:
            parser.error(f"Paper {paper_id} has no valid DOI")
        previous = papers_by_id.get(paper_id)
        paper = {"paper_id": paper_id, "doi": doi}
        if previous is not None and previous != paper:
            parser.error(f"Paper {paper_id} has conflicting DOI values")
        papers_by_id[paper_id] = paper

    result = run_structure_source_batch(
        [papers_by_id[paper_id] for paper_id in sorted(papers_by_id)],
        entities,
        reuse_manifest=args.reuse_manifest,
        download_root=args.download_root,
        manifest_path=args.manifest,
        snapshot_path=args.snapshot,
        work_path=args.work,
        confirmed_path=args.confirmed,
        summary_path=args.summary,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
