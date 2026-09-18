from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID

import pymupdf
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.activities.models import Activity
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.extractor import ProtectedPdfReference
from app.ai_prefill.legacy_adapter import LegacyPipelineAdapter
from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
from app.ai_prefill.service import AiPrefillService
from app.assets.models import Asset
from app.audit.service import AuditService
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.compounds.models import Compound
from app.config import Settings, get_settings
from app.database import bootstrap_database
from app.evidence.models import EdgeEvidenceLink, Evidence, EvidenceRole
from app.lineages.models import Lineage, LineageEdge, LineageMember
from app.papers.models import Paper
from app.publications.models import AdminDecision, PublishedPaperVersion
from app.structure_images.models import StructureSourceImage
from app.structures.models import Structure, StructureInputMethod
from app.users.models import User, UserRole
from app.workspaces.assignment import AssignmentService
from app.workspaces.models import (
    ChangeActorKind,
    ChangeEvent,
    PaperSectionReview,
    PaperSectionState,
    PaperSubmission,
    PaperWorkspace,
    ReviewTask,
    ReviewTaskState,
    WorkspaceState,
)
from leadtrace.ops.backup.verify_backup import verify_backup


class ProductionPrefillError(RuntimeError):
    """Raised before commit when a production prefill invariant is not met."""


@dataclass(frozen=True, slots=True)
class TargetPaper:
    source_key: str
    legacy_paper_id: str


@dataclass(frozen=True, slots=True)
class PreparedPaper:
    paper_id: UUID
    source_id: UUID
    source_sha256: str
    page_count: int
    payload: AiPrefillPayload
    payload_sha256: str
    counts: dict[str, int]


TARGETS: dict[str, TargetPaper] = {
    "LT-JMC-2024-67-05-004": TargetPaper(
        source_key=(
            "volume67 issue5/gilleran-et-al-2024-structure-activity-"
            "relationship-of-a-pyrrole-based-series-of-pfpkg-inhibitors-as-"
            "anti-malarials.pdf"
        ),
        legacy_paper_id="9b9e5d0c40bc",
    ),
    "LT-JMC-2024-67-05-005": TargetPaper(
        source_key=(
            "volume67 issue5/giovannuzzi-et-al-2024-dual-inhibitors-of-brain-"
            "carbonic-anhydrases-and-monoamine-oxidase-b-efficiently-protect-"
            "against.pdf"
        ),
        legacy_paper_id="387473d95eba",
    ),
    "LT-JMC-2024-67-05-010": TargetPaper(
        source_key=(
            "volume67 issue5/kesteleyn-et-al-2024-discovery-of-jnj-1802-a-"
            "first-in-class-pan-serotype-dengue-virus-ns4b-inhibitor.pdf"
        ),
        legacy_paper_id="548156debd90",
    ),
    "LT-JMC-2024-67-05-013": TargetPaper(
        source_key=(
            "volume67 issue5/lin-et-al-2024-design-synthesis-and-biological-"
            "evaluation-of-pierardine-derivatives-as-novel-brain-penetrant-"
            "and-in.pdf"
        ),
        legacy_paper_id="5c2d23f2662b",
    ),
}


EXPECTED_PAYLOAD_COUNTS: dict[str, dict[str, int]] = {
    "LT-JMC-2024-67-05-004": {
        "compounds": 11,
        "structures": 11,
        "structure_locators": 0,
        "lineages": 1,
        "edges": 6,
        "evidence": 6,
        "edge_evidence_links": 6,
        "activities": 0,
    },
    "LT-JMC-2024-67-05-005": {
        "compounds": 41,
        "structures": 41,
        "structure_locators": 0,
        "lineages": 5,
        "edges": 35,
        "evidence": 35,
        "edge_evidence_links": 35,
        "activities": 0,
    },
    "LT-JMC-2024-67-05-010": {
        "compounds": 6,
        "structures": 6,
        "structure_locators": 0,
        "lineages": 1,
        "edges": 5,
        "evidence": 5,
        "edge_evidence_links": 5,
        "activities": 0,
    },
    "LT-JMC-2024-67-05-013": {
        "compounds": 10,
        "structures": 10,
        "structure_locators": 0,
        "lineages": 1,
        "edges": 8,
        "evidence": 8,
        "edge_evidence_links": 8,
        "activities": 0,
    },
}

APPLY_CONFIRMATION = "APPLY-FOUR-PRODUCTION-PREFILLS"
OPERATION_VERSION = "four-production-prefill-20260918-v1"


@dataclass(frozen=True, slots=True)
class ReviewedEvidence:
    ref_markers: tuple[str, ...]
    page_number: int
    caption: str
    quoted_text: str


REVIEWED_EVIDENCE: dict[str, tuple[ReviewedEvidence, ...]] = {
    "LT-JMC-2024-67-05-004": (
        ReviewedEvidence(
            ref_markers=("-001-13-", "-002-15a-", "-003-15b-"),
            page_number=4,
            caption="Results and Scheme 3",
            quoted_text=(
                "The late-stage bromide intermediates with a methyl-substituted "
                "piperidine, 12a-b, proved to be versatile starting points for "
                "further elaboration. 12a was converted to an amino group in the "
                "presence of copper(I) oxide and ammonium hydroxide to afford target "
                "aminopyridine analog 13. In palladium catalyzed transformations, "
                "bromide analogs 12a-b were converted to methyl analogs 15a-b with "
                "trimethylboroxine (Scheme 3)."
            ),
        ),
        ReviewedEvidence(
            ref_markers=("-004-58-",),
            page_number=5,
            caption="Results and Scheme 4",
            quoted_text=(
                "Under Stille coupling conditions, the bromide of 11a was "
                "successfully converted to an acetyl group (58) that was reduced to "
                "a secondary alcohol with sodium borohydride to give analog 20."
            ),
        ),
        ReviewedEvidence(
            ref_markers=("-005-33-",),
            page_number=6,
            caption="Results and Scheme 8",
            quoted_text=(
                "underwent a Paal-Knorr pyrrole condensation with methylamine in hot "
                "acetic acid and ethanol to afford N-methyl analog 33 (Scheme 8)."
            ),
        ),
        ReviewedEvidence(
            ref_markers=("-006-61-",),
            page_number=5,
            caption="Results and Scheme 6",
            quoted_text=(
                "Under Vilsmeier-Haack reaction conditions with phosphorus "
                "oxychloride and DMF, an aldehyde is installed on 11g to give "
                "compound 61."
            ),
        ),
    ),
    "LT-JMC-2024-67-05-005": (
        ReviewedEvidence(
            ref_markers=tuple(f"-01-{number:03d}-" for number in range(1, 14)),
            page_number=6,
            caption="Results; subset 1 SAR; Table 1",
            quoted_text=(
                "Among these, compound 11, bearing a 3-F-sulfanilamide scaffold "
                "linked to an unsubstituted coumarin fragment, showed the homogeneous "
                "activity against target hCAs, such as II, VA, VB, and VII (KIs from "
                "10.8 to 25.5 nM). Substitution of the fluorine atom with hydrogen or "
                "other halogens (compounds 10, 12, and 13) generally decreased the "
                "ligand CA inhibitory action, and similarly did the elongation of the "
                "spacer between the amide linker and the CAI portion (compounds 14 "
                "and 15), or substitution at the coumarin scaffold with a 3-Cl-4-CH3 "
                "pattern (20-23). In contrast, a substitution at the coumarin 3 "
                "position with a carboxyethyl group allowed to maintain a generally "
                "good inhibitory trend against hCAs VA, VB, and VII and increased the "
                "ligand hCA II inhibitory efficacy (KIs from 0.8 to 12.7 nM), "
                "regardless of substitutions at the benzene ring bearing the SO2NH2 "
                "group or spacer length."
            ),
        ),
        ReviewedEvidence(
            ref_markers=tuple(f"-02-{number:03d}-" for number in range(14, 25)),
            page_number=6,
            caption="Results; subset 2 SAR; Table 1",
            quoted_text=(
                "Again, with obvious exceptions, substitution of the fluorine atom "
                "with hydrogen or other halogens (compounds 32, 34, and 35) decreased "
                "the ligand CA inhibitory action, such as the elongation of the "
                "spacer between the amide linker and the CAI portion (36 and 37) or "
                "substitution at the coumarin scaffold with a 7-OCH3 group (38-43)."
            ),
        ),
        ReviewedEvidence(
            ref_markers=("-03-025-",),
            page_number=6,
            caption="Results; subset 3 SAR; Table 1",
            quoted_text=(
                "Introduction of a COOEt group in position 3 of the coumarin "
                "generally lowered the hCA inhibition performance of compound 46, "
                "compared to 45"
            ),
        ),
        ReviewedEvidence(
            ref_markers=("-03-026-",),
            page_number=6,
            caption="Results; subset 3 SAR; Table 1",
            quoted_text=(
                "Substitution at the coumarin scaffold with a 3-Cl-4-CH3 pattern "
                "made compound 47 an equally potent inhibitor of hCAs II, VII, and "
                "XII"
            ),
        ),
        ReviewedEvidence(
            ref_markers=tuple(f"-04-{number:03d}-" for number in range(27, 30)),
            page_number=6,
            caption="Results; subset 4 SAR; Table 1",
            quoted_text=(
                "The substitution of the fluorine atom with hydrogen or other "
                "halogens (compounds 49, 51, and 52) did not alter substantially the "
                "ligand efficacy against the aforementioned CA isoforms."
            ),
        ),
        ReviewedEvidence(
            ref_markers=("-04-030-", "-04-031-"),
            page_number=6,
            caption="Results; subset 4 SAR; Table 1",
            quoted_text=(
                "Instead, the elongation of the amide-CAI spacer, as in derivatives "
                "53 and 54, increased the inhibitory performance of hCAs II and VB"
            ),
        ),
        ReviewedEvidence(
            ref_markers=("-03-032-97-",),
            page_number=10,
            caption="Results; compound 97 comparison",
            quoted_text=(
                "The only 7-benzyloxy-substituted chromone derivative of the series, "
                "which is 97, did not stand out among other compounds neither for CA "
                "inhibition (KIs in the range of 19.4-255.7 nM) nor for efficacy "
                "against hMAO-B (IC50 of 667.8 nM) and, specifically, was clearly "
                "worse than the corresponding coumarin analog 45."
            ),
        ),
        ReviewedEvidence(
            ref_markers=("-06-052-93-", "-06-053-94-", "-06-054-95-"),
            page_number=7,
            caption="Results; Scheme 6",
            quoted_text=(
                "The ethyl ester group of compound 46 was hydrolyzed under alkaline "
                "conditions, yielding the corresponding carboxylic acid 93 (Scheme "
                "6). Moreover, N-Boc piperazinyl derivatives 82 and 88 were "
                "deprotected with TFA, yielding piperazine derivatives 94 and 95, "
                "respectively (Scheme 6)."
            ),
        ),
    ),
    "LT-JMC-2024-67-05-010": (
        ReviewedEvidence(
            ref_markers=("-01-001-8a-",),
            page_number=3,
            caption="Results; Table 2",
            quoted_text=(
                "The chiral stability of the sulfone-substituted derivative was "
                "improved following the introduction of an ortho-methoxy substituent "
                "at the top phenyl moiety: the chiral stability of the "
                "ortho-methoxy-substituted sulfone-derivative 8a was established in a "
                "racemization experiment using a buffered solution at pH 7.4 at "
                "elevated temperatures."
            ),
        ),
        ReviewedEvidence(
            ref_markers=(
                "-01-002-10a-",
                "-01-003-11a-",
                "-01-004-12a-",
                "-01-005-13a-",
            ),
            page_number=3,
            caption="Results; indole SAR; Table 1",
            quoted_text=(
                "Transferring these indole substitution patterns to the sulfone "
                "series, either in combination with the para-fluorine substituent "
                "(compounds 10a and 12a) or with the para-chlorine substituent "
                "(compounds 11a and 13a), resulted in a further increase in the in "
                "vitro antiviral potency against all four DENV serotypes when "
                "compared to compound 8a."
            ),
        ),
    ),
    "LT-JMC-2024-67-05-013": (
        ReviewedEvidence(
            ref_markers=("-001-23-", "-002-27-", "-003-29-", "-004-34-"),
            page_number=3,
            caption="Results; N-phenyl SAR; Table 2",
            quoted_text=(
                "When fluorine (23), hydroxyl (27), methyl (28), methoxy (29), and "
                "isopropyl (34) groups were introduced at the para position of the "
                "phenyl moiety, the competitive activity was significantly improved "
                "with Ki values at the single-digit nanomolar level."
            ),
        ),
        ReviewedEvidence(
            ref_markers=("-005-48-", "-006-49-", "-007-50-"),
            page_number=5,
            caption="Results; terminal phenyl SAR; Table 3",
            quoted_text=(
                "While the counterpart bearing a trifluoromethyl (48; Ki = 2.60 +/- "
                "0.38 nM) group at the para position exhibited activity comparable "
                "to that of 44 (Ki = 1.34 +/- 0.15 nM), a p-chlorine (49) or "
                "p-fluorine replacement (50) sharply decreased the potency."
            ),
        ),
        ReviewedEvidence(
            ref_markers=("-008-66-",),
            page_number=6,
            caption="Results; isobenzofuranone SAR; Table 4",
            quoted_text=(
                "The introduction of a hydroxyl group at position 6 of the "
                "isobenzofuran-1(3H)-one scaffold culminated in a dramatic decrease "
                "in potency according to the data of 66 versus 44 as well as 67 "
                "versus 48."
            ),
        ),
    ),
}


def canonical_payload_bytes(payload: AiPrefillPayload) -> bytes:
    value = payload.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_payload_hash(payload: AiPrefillPayload) -> str:
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


def payload_counts(payload: AiPrefillPayload) -> dict[str, int]:
    return {
        "compounds": len(payload.compounds),
        "structures": len(payload.compounds),
        "structure_locators": len(payload.structure_locators),
        "lineages": len(payload.lineages),
        "edges": sum(len(lineage.edges) for lineage in payload.lineages),
        "evidence": len(payload.evidence),
        "edge_evidence_links": len(payload.edge_evidence_links),
        "activities": len(payload.activities),
    }


def assert_expected_counts(paper_key: str, payload: AiPrefillPayload) -> None:
    actual = payload_counts(payload)
    expected = EXPECTED_PAYLOAD_COUNTS.get(paper_key)
    if actual != expected:
        raise ProductionPrefillError(
            f"{paper_key} payload counts changed: expected={expected} actual={actual}"
        )


def _normalized_source_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def apply_reviewed_evidence(
    paper_key: str,
    payload: AiPrefillPayload,
) -> AiPrefillPayload:
    groups = REVIEWED_EVIDENCE.get(paper_key)
    if groups is None:
        raise ProductionPrefillError(f"No reviewed Evidence for {paper_key}")
    raw = payload.model_dump(mode="json")
    for evidence in raw["evidence"]:
        matches = [
            group
            for group in groups
            if any(marker in evidence["ref"] for marker in group.ref_markers)
        ]
        if len(matches) != 1:
            raise ProductionPrefillError(
                f"Evidence {evidence['ref']} has {len(matches)} reviewed source matches"
            )
        review = matches[0]
        evidence["page_number"] = review.page_number
        evidence["quoted_text"] = review.quoted_text
        evidence["caption"] = review.caption
    return AiPrefillPayload.model_validate(raw)


def validate_payload(
    payload: AiPrefillPayload,
    *,
    expected_doi: str | None,
    page_count: int,
    page_texts: dict[int, str],
) -> None:
    if payload.bibliography.doi != expected_doi:
        raise ProductionPrefillError("Payload DOI does not match the Paper DOI")
    if not payload.compounds or not payload.lineages:
        raise ProductionPrefillError("Payload must contain Compounds and Lineages")
    if AiPrefillService._parse_structures(payload) is None:
        raise ProductionPrefillError("Payload failed Structure validation")

    supported_edges = {
        link.edge_ref
        for link in payload.edge_evidence_links
        if link.role == "supports"
    }
    edge_refs = {
        edge.ref for lineage in payload.lineages for edge in lineage.edges
    }
    missing_support = sorted(edge_refs - supported_edges)
    if missing_support:
        raise ProductionPrefillError(
            "Every Edge requires supporting Evidence: " + ", ".join(missing_support)
        )

    for evidence in payload.evidence:
        if evidence.page_number > page_count:
            raise ProductionPrefillError(
                f"Evidence {evidence.ref} page exceeds the Source PDF"
            )
        quote = evidence.quoted_text or ""
        page_text = page_texts.get(evidence.page_number, "")
        if not quote or _normalized_source_text(quote) not in _normalized_source_text(
            page_text
        ):
            raise ProductionPrefillError(
                f"Evidence {evidence.ref} not found on PDF page "
                f"{evidence.page_number}"
            )

    for activity in payload.activities:
        if activity.evidence_ref is None:
            raise ProductionPrefillError("Every Activity requires Evidence")


def require_apply_success(paper_key: str, result: Any) -> None:
    status = getattr(result.run.status, "value", result.run.status)
    if not result.applied or status != AiExtractionRunStatus.SUCCEEDED.value:
        summary = result.run.error_summary or status
        raise ProductionPrefillError(f"{paper_key} prefill failed: {summary}")


def compare_reviewed_manifest(
    reviewed: dict[str, Any],
    current: dict[str, dict[str, Any]],
) -> None:
    if reviewed.get("schema_version") != 1 or reviewed.get("mode") != "dry-run":
        raise ProductionPrefillError("Reviewed manifest is not a dry-run manifest")
    reviewed_papers = reviewed.get("papers")
    if not isinstance(reviewed_papers, dict) or set(reviewed_papers) != set(current):
        raise ProductionPrefillError("Reviewed manifest Paper set changed")
    for paper_key, current_entry in current.items():
        reviewed_entry = reviewed_papers[paper_key]
        if reviewed_entry.get("payload_sha256") != current_entry["payload_sha256"]:
            raise ProductionPrefillError(f"{paper_key} payload hash changed")
        if reviewed_entry.get("counts") != current_entry["counts"]:
            raise ProductionPrefillError(f"{paper_key} payload counts changed")
        for field in ("source_sha256", "page_count"):
            if field in reviewed_entry and (
                reviewed_entry[field] != current_entry[field]
            ):
                raise ProductionPrefillError(
                    f"{paper_key} reviewed {field} changed"
                )


def _utc_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ProductionPrefillError(f"{field} timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProductionPrefillError(f"{field} timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProductionPrefillError(f"{field} timestamp has no UTC offset")
    return parsed.astimezone(UTC)


def validate_backup_for_apply(
    metadata_path: Path,
    reviewed_manifest: dict[str, Any],
) -> dict[str, Any]:
    try:
        verification = verify_backup(metadata_path)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ProductionPrefillError("Database backup verification failed") from error
    if verification.backup_scope != "database":
        raise ProductionPrefillError("Apply requires a database backup")
    backup_completed = _utc_timestamp(metadata.get("completed_at"), "backup")
    dry_run_generated = _utc_timestamp(
        reviewed_manifest.get("generated_at"), "dry-run"
    )
    if backup_completed < dry_run_generated:
        raise ProductionPrefillError("Database backup predates the reviewed dry-run")
    dump = metadata["artifacts"]["database_dump"]
    return {
        "backup_id": verification.backup_id,
        "completed_at": metadata["completed_at"],
        "metadata_path": str(metadata_path.resolve(strict=True)),
        "database_dump_sha256": dump["sha256"],
        "database_dump_size_bytes": dump["size_bytes"],
    }


def write_payload(path: Path, payload: AiPrefillPayload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_payload_bytes(payload) + b"\n")


def _count(session: Session, model: type[Any], *criteria: Any) -> int:
    return int(
        session.scalar(select(func.count()).select_from(model).where(*criteria)) or 0
    )


def _require_production(settings: Settings) -> None:
    if settings.environment != "production":
        raise ProductionPrefillError(
            "This operation requires LEADTRACE_ENVIRONMENT=production"
        )
    if settings.ai_prefill_legacy_root is None:
        raise ProductionPrefillError("AI prefill legacy root is not configured")


def _load_actor(
    session: Session,
    username: str,
    role: UserRole,
) -> User:
    users = list(session.scalars(select(User).where(User.username == username)))
    if len(users) != 1 or users[0].role is not role or not users[0].is_enabled:
        raise ProductionPrefillError(
            f"Enabled {role.value} account {username!r} was not found uniquely"
        )
    return users[0]


def _ensure_blank_paper(session: Session, paper: Paper) -> None:
    models = (
        ReviewTask,
        PaperWorkspace,
        AiExtractionRun,
        Compound,
        Structure,
        StructureSourceImage,
        Lineage,
        LineageMember,
        LineageEdge,
        Evidence,
        EdgeEvidenceLink,
        Activity,
        PaperSubmission,
        AdminDecision,
        PublishedPaperVersion,
    )
    nonempty = {
        model.__tablename__: _count(session, model, model.paper_id == paper.id)
        for model in models
    }
    nonempty = {name: count for name, count in nonempty.items() if count}
    if nonempty or paper.current_published_version_id is not None:
        raise ProductionPrefillError(
            f"{paper.paper_key} is not an untouched Paper: {nonempty}"
        )


def _read_pdf(
    settings: Settings,
    source: PaperSource,
) -> tuple[bytes, dict[int, str]]:
    source_root = settings.source_roots.get(source.source_root_key)
    if source_root is None:
        raise ProductionPrefillError(
            f"Source root {source.source_root_key!r} is not configured"
        )
    resolved_root = source_root.resolve(strict=True)
    source_path = (resolved_root / source.source_key).resolve(strict=True)
    if not source_path.is_relative_to(resolved_root) or not source_path.is_file():
        raise ProductionPrefillError("Source PDF path escaped its configured root")
    source_bytes = source_path.read_bytes()
    if len(source_bytes) != source.byte_size:
        raise ProductionPrefillError("Source PDF byte size changed")
    if hashlib.sha256(source_bytes).hexdigest() != source.sha256:
        raise ProductionPrefillError("Source PDF SHA-256 changed")
    with pymupdf.open(stream=source_bytes, filetype="pdf") as document:
        if document.page_count != source.page_count:
            raise ProductionPrefillError("Source PDF page count changed")
        page_texts = {
            page_number + 1: document[page_number].get_text("text")
            for page_number in range(document.page_count)
        }
    return source_bytes, page_texts


def prepare_payloads(
    session: Session,
    settings: Settings,
    *,
    require_blank: bool = True,
) -> dict[str, PreparedPaper]:
    papers = list(
        session.scalars(
            select(Paper)
            .where(Paper.paper_key.in_(tuple(TARGETS)))
            .order_by(Paper.paper_key)
        )
    )
    if [paper.paper_key for paper in papers] != list(TARGETS):
        raise ProductionPrefillError("Production catalog does not contain the four Papers")
    _load_actor(session, "admin", UserRole.ADMIN)
    _load_actor(session, "pilot-reviewer", UserRole.REVIEWER)
    assert settings.ai_prefill_legacy_root is not None
    adapter = LegacyPipelineAdapter(settings.ai_prefill_legacy_root)
    prepared: dict[str, PreparedPaper] = {}
    for paper in papers:
        target = TARGETS[paper.paper_key]
        if require_blank:
            _ensure_blank_paper(session, paper)
        source = session.get(PaperSource, paper.source_id)
        if (
            source is None
            or source.integrity_state is not PaperSourceIntegrityState.VERIFIED
            or source.source_key != target.source_key
        ):
            raise ProductionPrefillError(
                f"{paper.paper_key} does not have the expected verified Source PDF"
            )
        asset = session.get(Asset, source.asset_id)
        if (
            asset is None
            or asset.sha256 != source.sha256
            or asset.byte_size != source.byte_size
            or asset.page_count != source.page_count
        ):
            raise ProductionPrefillError(
                f"{paper.paper_key} Source Asset metadata is inconsistent"
            )
        _, page_texts = _read_pdf(settings, source)
        payload = adapter.extract(
            ProtectedPdfReference(
                paper_id=paper.id,
                source_root_key=source.source_root_key,
                source_key=source.source_key,
                sha256=source.sha256,
                page_count=source.page_count,
            )
        )
        payload = apply_reviewed_evidence(paper.paper_key, payload)
        validate_payload(
            payload,
            expected_doi=paper.doi,
            page_count=source.page_count,
            page_texts=page_texts,
        )
        assert_expected_counts(paper.paper_key, payload)
        prepared[paper.paper_key] = PreparedPaper(
            paper_id=paper.id,
            source_id=source.id,
            source_sha256=source.sha256,
            page_count=source.page_count,
            payload=payload,
            payload_sha256=canonical_payload_hash(payload),
            counts=payload_counts(payload),
        )
    return prepared


def _manifest_entries(
    prepared: dict[str, PreparedPaper],
) -> dict[str, dict[str, Any]]:
    return {
        paper_key: {
            "paper_id": str(item.paper_id),
            "source_id": str(item.source_id),
            "source_sha256": item.source_sha256,
            "page_count": item.page_count,
            "payload_sha256": item.payload_sha256,
            "counts": item.counts,
            "payload_file": f"payloads/{paper_key}.json",
        }
        for paper_key, item in prepared.items()
    }


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_dry_run_artifacts(
    output_dir: Path,
    prepared: dict[str, PreparedPaper],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink():
        raise ProductionPrefillError("Output directory must not be a symlink")
    for paper_key, item in prepared.items():
        write_payload(output_dir / "payloads" / f"{paper_key}.json", item.payload)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "operation_version": OPERATION_VERSION,
        "mode": "dry-run",
        "generated_at": datetime.now(UTC).isoformat(),
        "papers": _manifest_entries(prepared),
    }
    _atomic_json(output_dir / "dry-run-manifest.json", manifest)
    return manifest


def _read_reviewed_manifest(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "dry-run-manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProductionPrefillError("Reviewed dry-run manifest is unavailable") from error
    if not isinstance(value, dict):
        raise ProductionPrefillError("Reviewed dry-run manifest is invalid")
    return value


def apply_prepared_payloads(
    session_factory: sessionmaker[Session],
    prepared: dict[str, PreparedPaper],
) -> dict[str, dict[str, str]]:
    applied: dict[str, dict[str, str]] = {}
    for paper_key, item in prepared.items():
        with session_factory() as session:
            with session.begin():
                paper = session.scalar(
                    select(Paper)
                    .where(Paper.id == item.paper_id)
                    .with_for_update()
                )
                if paper is None or paper.paper_key != paper_key:
                    raise ProductionPrefillError(f"{paper_key} disappeared before apply")
                _ensure_blank_paper(session, paper)
                admin = _load_actor(session, "admin", UserRole.ADMIN)
                reviewer = _load_actor(
                    session, "pilot-reviewer", UserRole.REVIEWER
                )
                assignment = AssignmentService().assign(
                    session,
                    paper_id=paper.id,
                    reviewer_id=reviewer.id,
                    admin_id=admin.id,
                    request_id=f"{OPERATION_VERSION}:{paper_key}",
                    ip_address="127.0.0.1",
                )
                queue = AiPrefillService().queue(
                    session,
                    workspace_id=assignment.workspace.id,
                    requested_by_id=admin.id,
                    engine="reviewed-production-payload",
                    engine_version=(
                        f"{OPERATION_VERSION}:{item.payload_sha256[:16]}"
                    ),
                )
                if not queue.created:
                    raise ProductionPrefillError(
                        f"{paper_key} unexpectedly reused an AI run"
                    )
                result = AiPrefillService().apply(
                    session,
                    run_id=queue.run.id,
                    payload=item.payload,
                )
                require_apply_success(paper_key, result)
                session.flush()
                applied[paper_key] = {
                    "review_task_id": str(assignment.task.id),
                    "workspace_id": str(assignment.workspace.id),
                    "ai_run_id": str(result.run.id),
                }
    return applied


def _verify_science_creator(
    session: Session,
    model: type[Any],
    paper_id: UUID,
    expected: int,
) -> None:
    total = _count(session, model, model.paper_id == paper_id)
    ai_owned = _count(
        session,
        model,
        model.paper_id == paper_id,
        model.created_by_kind == ChangeActorKind.AI,
    )
    if total != expected or ai_owned != expected:
        raise ProductionPrefillError(
            f"{model.__tablename__} count/AI ownership mismatch: "
            f"total={total} ai={ai_owned} expected={expected}"
        )


def verify_paper(
    session: Session,
    *,
    paper_key: str,
    counts: dict[str, int],
) -> dict[str, Any]:
    paper = session.scalar(select(Paper).where(Paper.paper_key == paper_key))
    if paper is None or paper.current_published_version_id is not None:
        raise ProductionPrefillError(f"{paper_key} publication state is invalid")
    reviewer = _load_actor(session, "pilot-reviewer", UserRole.REVIEWER)
    tasks = list(session.scalars(select(ReviewTask).where(ReviewTask.paper_id == paper.id)))
    if (
        len(tasks) != 1
        or tasks[0].status is not ReviewTaskState.ASSIGNED
        or tasks[0].assigned_reviewer_id != reviewer.id
    ):
        raise ProductionPrefillError(f"{paper_key} assignment verification failed")
    workspaces = list(
        session.scalars(select(PaperWorkspace).where(PaperWorkspace.paper_id == paper.id))
    )
    if (
        len(workspaces) != 1
        or workspaces[0].state is not WorkspaceState.EDITING
        or workspaces[0].version != 2
    ):
        raise ProductionPrefillError(f"{paper_key} Workspace verification failed")
    workspace = workspaces[0]
    section_count = _count(
        session,
        PaperSectionReview,
        PaperSectionReview.workspace_id == workspace.id,
        PaperSectionReview.state == PaperSectionState.PENDING,
    )
    if section_count != 6:
        raise ProductionPrefillError(f"{paper_key} does not have six pending sections")
    runs = list(
        session.scalars(
            select(AiExtractionRun).where(AiExtractionRun.paper_id == paper.id)
        )
    )
    if (
        len(runs) != 1
        or runs[0].status is not AiExtractionRunStatus.SUCCEEDED
        or runs[0].workspace_id != workspace.id
    ):
        raise ProductionPrefillError(f"{paper_key} AI run verification failed")
    run = runs[0]

    model_counts = {
        Compound: counts["compounds"],
        Structure: counts["structures"],
        StructureSourceImage: counts["structure_locators"],
        Lineage: counts["lineages"],
        LineageEdge: counts["edges"],
        Evidence: counts["evidence"],
        EdgeEvidenceLink: counts["edge_evidence_links"],
        Activity: counts["activities"],
    }
    for model, expected in model_counts.items():
        _verify_science_creator(session, model, paper.id, expected)

    structure_count = _count(
        session,
        Structure,
        Structure.paper_id == paper.id,
        Structure.input_method == StructureInputMethod.AI_PREFILL,
        Structure.canonical_smiles.is_not(None),
    )
    if structure_count != counts["structures"]:
        raise ProductionPrefillError(f"{paper_key} Structure validation failed")
    source = session.get(PaperSource, paper.source_id)
    assert source is not None
    evidence_count = _count(
        session,
        Evidence,
        Evidence.paper_id == paper.id,
        Evidence.source_sha256 == source.sha256,
        Evidence.page_number <= source.page_count,
    )
    if evidence_count != counts["evidence"]:
        raise ProductionPrefillError(f"{paper_key} Evidence source validation failed")
    unsupported_edges = _count(
        session,
        LineageEdge,
        LineageEdge.paper_id == paper.id,
        ~exists().where(
            EdgeEvidenceLink.edge_id == LineageEdge.id,
            EdgeEvidenceLink.role == EvidenceRole.SUPPORTS,
        ),
    )
    if unsupported_edges:
        raise ProductionPrefillError(f"{paper_key} has unsupported Lineage Edges")
    if any(
        _count(session, model, model.paper_id == paper.id)
        for model in (PaperSubmission, AdminDecision, PublishedPaperVersion)
    ):
        raise ProductionPrefillError(f"{paper_key} was submitted or published")

    human_changes = _count(
        session,
        ChangeEvent,
        ChangeEvent.paper_id == paper.id,
        ChangeEvent.actor_kind.in_([ChangeActorKind.REVIEWER, ChangeActorKind.ADMIN]),
    )
    ai_changes_without_run = _count(
        session,
        ChangeEvent,
        ChangeEvent.paper_id == paper.id,
        ChangeEvent.actor_kind == ChangeActorKind.AI,
        ChangeEvent.ai_run_id != run.id,
    )
    if human_changes or ai_changes_without_run:
        raise ProductionPrefillError(f"{paper_key} Change Event provenance failed")
    return {
        "paper_id": str(paper.id),
        "review_task_id": str(tasks[0].id),
        "workspace_id": str(workspace.id),
        "workspace_version": workspace.version,
        "ai_run_id": str(run.id),
        "ai_run_status": run.status.value,
        "pending_sections": section_count,
        "counts": counts,
    }


def verify_all(
    session_factory: sessionmaker[Session],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    papers = manifest.get("papers")
    if not isinstance(papers, dict) or set(papers) != set(TARGETS):
        raise ProductionPrefillError("Verification manifest does not contain four Papers")
    with session_factory() as session:
        with session.begin():
            results = {
                paper_key: verify_paper(
                    session,
                    paper_key=paper_key,
                    counts=entry["counts"],
                )
                for paper_key, entry in papers.items()
            }
            audit = AuditService().verify_chain(session)
    if not audit.valid:
        raise ProductionPrefillError(
            f"Audit chain failed at sequence {audit.first_invalid_sequence}"
        )
    return {
        "schema_version": 1,
        "operation_version": OPERATION_VERSION,
        "verified_at": datetime.now(UTC).isoformat(),
        "audit": {
            "valid": audit.valid,
            "event_count": audit.event_count,
            "first_invalid_sequence": audit.first_invalid_sequence,
        },
        "papers": results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run, apply, or verify the four reviewed production prefills."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--confirm")
    parser.add_argument("--backup-metadata", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    _require_production(settings)
    output_dir = args.output_dir.resolve(strict=False)
    resources = bootstrap_database(settings)
    try:
        if args.verify_only:
            manifest = _read_reviewed_manifest(output_dir)
            report = verify_all(resources.session_factory, manifest)
            _atomic_json(output_dir / "verification-report.json", report)
            print(json.dumps(report, ensure_ascii=True, sort_keys=True))
            return 0

        with resources.session_factory() as session:
            with session.begin():
                prepared = prepare_payloads(session, settings)
        current_entries = _manifest_entries(prepared)
        if args.dry_run:
            manifest = write_dry_run_artifacts(output_dir, prepared)
            print(json.dumps(manifest, ensure_ascii=True, sort_keys=True))
            return 0

        if args.confirm != APPLY_CONFIRMATION:
            raise ProductionPrefillError(
                f"--apply requires --confirm {APPLY_CONFIRMATION}"
            )
        reviewed = _read_reviewed_manifest(output_dir)
        compare_reviewed_manifest(reviewed, current_entries)
        if args.backup_metadata is None:
            raise ProductionPrefillError("--apply requires --backup-metadata")
        backup = validate_backup_for_apply(args.backup_metadata, reviewed)
        applied = apply_prepared_payloads(resources.session_factory, prepared)
        report = verify_all(resources.session_factory, reviewed)
        report["applied"] = applied
        report["backup"] = backup
        _atomic_json(output_dir / "apply-report.json", report)
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return 0
    finally:
        resources.close()


__all__ = [
    "EXPECTED_PAYLOAD_COUNTS",
    "ProductionPrefillError",
    "TARGETS",
    "apply_prepared_payloads",
    "apply_reviewed_evidence",
    "assert_expected_counts",
    "canonical_payload_hash",
    "compare_reviewed_manifest",
    "main",
    "payload_counts",
    "prepare_payloads",
    "require_apply_success",
    "validate_backup_for_apply",
    "validate_payload",
    "verify_all",
    "write_payload",
]


if __name__ == "__main__":
    raise SystemExit(main())
