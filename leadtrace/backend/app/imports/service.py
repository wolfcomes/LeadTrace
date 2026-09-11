from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import secrets
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.assets.scanner import classify_source_asset
from app.assets.storage import AssetMimeMismatchError, LocalAssetStore
from app.compounds.models import Compound, normalize_local_label
from app.evidence.models import Evidence
from app.imports.models import (
    ImportAssetLink,
    ImportBatch,
    ImportReleaseCandidate,
    ImportStagingRecord,
)
from app.imports.readers.manifest import StagedSourceRecord
from app.imports.reconcile import (
    DEFAULT_SOURCE_MANIFEST,
    BaselineSourceData,
    ReconciliationReport,
    ResolvedAssetReference,
    load_baseline_source,
    reconcile_baseline,
    reconcile_loaded_baseline,
    source_snapshot_is_unchanged,
)
from app.lineages.models import Lineage, LineageEdge
from app.papers.models import Paper
from app.revisions.models import (
    ActivityState,
    EvidenceState,
    ObjectRevision,
    RevisionedObject,
    StructureState,
)
from app.security.passwords import hash_password
from app.security.policies import WorkflowState
from app.structures.models import Structure
from app.users.models import User, UserRole
from app.visual_objects.models import VisualObject


SYSTEM_IMPORT_USERNAME = "system.baseline-import"


class ImportValidationError(ValueError):
    """Raised before commit when authoritative baseline validation fails."""


@dataclass(frozen=True, slots=True)
class ImportApplyResult:
    batch_id: UUID
    release_candidate_id: UUID
    created: bool


def _required(record: StagedSourceRecord, field_name: str) -> str:
    value = record.normalized_values.get(field_name)
    if not isinstance(value, str) or not value:
        raise ImportValidationError(
            f"{record.record_type} {record.original_id!r} requires {field_name}"
        )
    return value


def _optional(record: StagedSourceRecord, field_name: str) -> str | None:
    value = record.normalized_values.get(field_name)
    return value if isinstance(value, str) and value else None


def _safe_snapshot(record: StagedSourceRecord) -> dict[str, object]:
    return {
        "record_type": record.record_type,
        "original_id": record.original_id,
        "source": {
            "file": record.source_file,
            "row_locator": record.source_row_locator,
            "sha256": record.source_hash,
        },
        "raw_values": record.raw_values,
        "normalized_values": record.normalized_values,
    }


def _snapshot_hash(snapshot: dict[str, object]) -> str:
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _search_text(record: StagedSourceRecord) -> str:
    return " ".join(
        value
        for value in record.normalized_values.values()
        if isinstance(value, str) and value
    )


def _asset_summary(report: ReconciliationReport) -> dict[str, object]:
    linkage = report.asset_linkage
    return {
        "resolved_references": linkage.resolved_references,
        "unique_resolved_assets": len(
            {item.manifest_path for item in linkage.resolved}
        ),
        "missing_references": linkage.missing_references,
        "ambiguous_references": linkage.ambiguous_references,
        "corrupt_references": linkage.corrupt_references,
    }


class BaselineImporter:
    def __init__(
        self,
        source_root: Path,
        *,
        managed_asset_root: Path,
        expected: dict[str, object] | None = None,
        expected_path: Path | None = None,
        source_manifest_path: Path = DEFAULT_SOURCE_MANIFEST,
    ) -> None:
        self.source_root = source_root.resolve()
        self.managed_asset_root = managed_asset_root.resolve()
        self.expected = expected
        self.expected_path = expected_path
        self.source_manifest_path = source_manifest_path.resolve()

    def reconcile(self) -> ReconciliationReport:
        return reconcile_baseline(
            self.source_root,
            expected=self.expected,
            expected_path=self.expected_path,
            source_manifest_path=self.source_manifest_path,
        )

    def apply(self, session: Session) -> ImportApplyResult:
        data = load_baseline_source(self.source_root)
        report = reconcile_loaded_baseline(
            self.source_root,
            data,
            expected=self.expected,
            expected_path=self.expected_path,
            source_manifest_path=self.source_manifest_path,
        )
        if not report.matches_expected or any(report.integrity.values()):
            raise ImportValidationError(
                "Baseline reconcile failed; no import records were written"
            )
        existing_batch = session.scalar(
            select(ImportBatch).where(
                ImportBatch.source_fingerprint == report.source_fingerprint
            )
        )
        if existing_batch is not None:
            candidate = session.scalar(
                select(ImportReleaseCandidate).where(
                    ImportReleaseCandidate.import_batch_id == existing_batch.id
                )
            )
            if candidate is None:
                raise ImportValidationError(
                    "Existing import batch has no release candidate"
                )
            return ImportApplyResult(
                batch_id=existing_batch.id,
                release_candidate_id=candidate.id,
                created=False,
            )

        batch = ImportBatch(
            id=uuid4(),
            source_fingerprint=report.source_fingerprint,
            status="staging",
            counts=report.counts,
            integrity=report.integrity,
            asset_linkage=_asset_summary(report),
        )
        session.add(batch)
        session.flush()
        self._stage_records(session, batch.id, data)
        actor = self._system_actor(session)
        objects = self._create_domain_objects(session, data)
        revisions = self._create_revisions(data, objects, actor.id)
        session.add_all(revisions)
        assets = self._register_assets(session, batch.id, report)
        self._link_assets(session, batch.id, report, assets)
        candidate = ImportReleaseCandidate(
            id=uuid4(),
            import_batch_id=batch.id,
            status="imported_baseline",
            manifest={
                "schema_version": 1,
                "source_fingerprint": report.source_fingerprint,
                "status": "imported_baseline",
                "is_current": False,
                "counts": report.counts,
                "integrity": report.integrity,
                "asset_linkage": _asset_summary(report),
                "revision_count": len(revisions),
            },
            is_current=False,
        )
        session.add(candidate)
        batch.status = "completed"
        batch.completed_at = datetime.now(UTC)
        if not source_snapshot_is_unchanged(
            self.source_root,
            data,
            self.source_manifest_path,
            report.source_fingerprint,
        ):
            raise ImportValidationError(
                "Baseline source facts changed during import; transaction rolled back"
            )
        session.flush()
        return ImportApplyResult(
            batch_id=batch.id,
            release_candidate_id=candidate.id,
            created=True,
        )

    @staticmethod
    def _stage_records(
        session: Session,
        batch_id: UUID,
        data: BaselineSourceData,
    ) -> None:
        session.add_all(
            [
                ImportStagingRecord(
                    id=uuid4(),
                    import_batch_id=batch_id,
                    record_type=record.record_type,
                    original_id=record.original_id,
                    source_file=record.source_file,
                    source_row_locator=record.source_row_locator,
                    source_hash=record.source_hash,
                    raw_values=record.raw_values,
                    normalized_values=record.normalized_values,
                )
                for record in data.fingerprint_records
            ]
        )
        session.flush()

    @staticmethod
    def _system_actor(session: Session) -> User:
        actor = session.scalar(
            select(User).where(User.normalized_username == SYSTEM_IMPORT_USERNAME)
        )
        if actor is not None:
            if actor.is_enabled:
                raise ImportValidationError(
                    "The baseline import system actor must remain disabled"
                )
            return actor
        discarded_password = secrets.token_urlsafe(48) + "Aa1!"
        actor = User(
            id=uuid4(),
            username=SYSTEM_IMPORT_USERNAME,
            normalized_username=SYSTEM_IMPORT_USERNAME,
            display_name="Baseline Import System",
            role=UserRole.ADMIN,
            is_enabled=False,
            password_hash=hash_password(discarded_password),
            must_change_password=True,
        )
        session.add(actor)
        session.flush()
        return actor

    @staticmethod
    def _create_domain_objects(
        session: Session,
        data: BaselineSourceData,
    ) -> dict[tuple[str, str], RevisionedObject]:
        doi_by_paper: dict[str, str] = {}
        for compound_record in data.compounds:
            paper_key = _required(compound_record, "paper_id")
            doi = _optional(compound_record, "doi")
            if doi is None:
                continue
            previous = doi_by_paper.setdefault(paper_key, doi)
            if previous != doi:
                raise ImportValidationError(
                    f"Paper {paper_key!r} has conflicting DOI values"
                )

        papers = {
            record.original_id: Paper(
                id=uuid4(),
                paper_key=record.original_id,
                doi=doi_by_paper.get(record.original_id),
            )
            for record in data.papers
        }
        session.add_all(papers.values())
        session.flush()

        compounds: dict[str, Compound] = {}
        for record in data.compounds:
            paper_key = _required(record, "paper_id")
            paper = papers.get(paper_key)
            if paper is None:
                raise ImportValidationError(
                    f"Compound {record.original_id!r} references unknown paper"
                )
            display_label = normalize_local_label(_required(record, "display_label"))
            normalized_label = normalize_local_label(
                _optional(record, "normalized_label") or display_label
            )
            compounds[record.original_id] = Compound(
                id=uuid4(),
                paper_id=paper.id,
                local_identity=record.original_id,
                display_label=display_label,
                normalized_label=normalized_label,
            )
        session.add_all(compounds.values())
        session.flush()

        lineages: dict[str, Lineage] = {}
        for record in data.lineages:
            paper = papers.get(_required(record, "paper_id"))
            if paper is None:
                raise ImportValidationError(
                    f"Lineage {record.original_id!r} references unknown paper"
                )
            lineages[record.original_id] = Lineage(
                id=uuid4(),
                paper_id=paper.id,
                lineage_key=record.original_id,
            )
        session.add_all(lineages.values())
        session.flush()

        structures: dict[str, Structure] = {}
        for record in data.structures:
            paper = papers.get(_required(record, "paper_id"))
            compound = compounds.get(_required(record, "compound_entity_id"))
            if paper is None or compound is None:
                raise ImportValidationError(
                    f"Structure {record.original_id!r} has an unknown reference"
                )
            if compound.paper_id != paper.id:
                raise ImportValidationError(
                    f"Structure {record.original_id!r} crosses Paper boundaries"
                )
            structures[record.original_id] = Structure(
                id=uuid4(),
                paper_id=paper.id,
                compound_id=compound.id,
                structure_key=record.original_id,
            )

        evidence: dict[str, Evidence] = {}
        for record in data.evidence:
            paper = papers.get(_required(record, "paper_id"))
            if paper is None:
                raise ImportValidationError(
                    f"Evidence {record.original_id!r} references unknown paper"
                )
            evidence[record.original_id] = Evidence(
                id=uuid4(),
                paper_id=paper.id,
                evidence_key=record.original_id,
            )

        activities: dict[str, Activity] = {}
        for record in data.activities:
            paper = papers.get(_required(record, "paper_id"))
            compound = compounds.get(_required(record, "compound_entity_id"))
            if paper is None or compound is None:
                raise ImportValidationError(
                    f"Activity {record.original_id!r} has an unknown reference"
                )
            if compound.paper_id != paper.id:
                raise ImportValidationError(
                    f"Activity {record.original_id!r} crosses Paper boundaries"
                )
            activities[record.original_id] = Activity(
                id=uuid4(),
                paper_id=paper.id,
                compound_id=compound.id,
                activity_key=record.original_id,
            )

        edges: dict[str, LineageEdge] = {}
        for record in data.edges:
            paper = papers.get(_required(record, "paper_id"))
            lineage = lineages.get(_required(record, "lineage_id"))
            parent_key = _optional(record, "parent_entity_id")
            parent = compounds.get(parent_key) if parent_key is not None else None
            derived = compounds.get(_required(record, "derived_entity_id"))
            if paper is None or lineage is None or derived is None:
                raise ImportValidationError(
                    f"Edge {record.original_id!r} has an unknown reference"
                )
            if parent_key is not None and parent is None:
                raise ImportValidationError(
                    f"Edge {record.original_id!r} references an unknown parent"
                )
            if (
                lineage.paper_id != paper.id
                or derived.paper_id != paper.id
                or (parent is not None and parent.paper_id != paper.id)
            ):
                raise ImportValidationError(
                    f"Edge {record.original_id!r} crosses Paper boundaries"
                )
            edges[record.original_id] = LineageEdge(
                id=uuid4(),
                paper_id=paper.id,
                lineage_id=lineage.id,
                edge_key=record.original_id,
                parent_compound_id=parent.id if parent is not None else None,
                derived_compound_id=derived.id,
            )

        visuals: dict[str, VisualObject] = {}
        for record in data.visual_objects:
            paper = papers.get(_required(record, "paper_id"))
            if paper is None:
                raise ImportValidationError(
                    f"Visual object {record.original_id!r} references unknown paper"
                )
            visuals[record.original_id] = VisualObject(
                id=uuid4(),
                paper_id=paper.id,
                object_key=record.original_id,
            )

        session.add_all(
            [
                *structures.values(),
                *evidence.values(),
                *activities.values(),
                *edges.values(),
                *visuals.values(),
            ]
        )
        session.flush()
        return {
            **{("paper", key): value for key, value in papers.items()},
            **{("compound", key): value for key, value in compounds.items()},
            **{("lineage", key): value for key, value in lineages.items()},
            **{("structure", key): value for key, value in structures.items()},
            **{("evidence", key): value for key, value in evidence.items()},
            **{("activity", key): value for key, value in activities.items()},
            **{("lineage_edge", key): value for key, value in edges.items()},
            **{("visual_object", key): value for key, value in visuals.items()},
        }

    @staticmethod
    def _create_revisions(
        data: BaselineSourceData,
        objects: dict[tuple[str, str], RevisionedObject],
        actor_id: UUID,
    ) -> list[ObjectRevision]:
        revisions: list[ObjectRevision] = []
        for record in data.object_records:
            domain_object = objects.get((record.record_type, record.original_id))
            if domain_object is None:
                raise ImportValidationError(
                    f"No stable identity was created for {record.record_type} "
                    f"{record.original_id!r}"
                )
            snapshot = _safe_snapshot(record)
            revision = ObjectRevision(
                id=uuid4(),
                object_id=domain_object.id,
                revision_number=1,
                predecessor_id=None,
                changeset_id=None,
                actor_id=actor_id,
                reason="Authoritative baseline import",
                content_hash=_snapshot_hash(snapshot),
                search_text=_search_text(record),
                snapshot=snapshot,
                workflow_state=WorkflowState.APPROVED,
                is_current_published=False,
                is_tombstone=False,
            )
            if record.record_type == "structure":
                confirmed = (
                    _optional(record, "confirmation_status")
                    == "structure_confirmed"
                )
                revision.structure_state = (
                    StructureState.STRUCTURE_CONFIRMED
                    if confirmed
                    else StructureState.SOURCE_BOUND_CANDIDATE
                )
                revision.canonical_smiles = _optional(
                    record, "canonical_isomeric_smiles"
                )
            elif record.record_type == "evidence":
                revision.evidence_state = EvidenceState.SOURCE_BOUND
                revision.evidence_text = _optional(record, "evidence_text")
            elif record.record_type == "activity":
                revision.activity_state = ActivityState.SOURCE_BOUND
                revision.activity_metric = _optional(record, "metric")
                revision.activity_value = _optional(record, "value")
                revision.activity_unit = _optional(record, "unit")
            elif record.record_type == "lineage_edge":
                revision.relation_type = _optional(record, "relation_type")
                revision.relation_status = _optional(record, "relation_status")
            revisions.append(revision)
        return revisions

    def _register_assets(
        self,
        session: Session,
        batch_id: UUID,
        report: ReconciliationReport,
    ) -> dict[str, Asset]:
        manifest_payload = json.loads(
            self.source_manifest_path.read_text(encoding="utf-8")
        )
        workspace_root_value = manifest_payload.get("workspace_root")
        if not isinstance(workspace_root_value, str):
            raise ImportValidationError("Source manifest workspace_root is invalid")
        workspace_root = Path(workspace_root_value).resolve()
        store = LocalAssetStore(
            self.managed_asset_root,
            source_roots={"baseline": workspace_root},
        )
        references_by_path: dict[str, list[ResolvedAssetReference]] = {}
        for reference in report.asset_linkage.resolved:
            references_by_path.setdefault(reference.manifest_path, []).append(reference)
        storage_keys = {
            path: store.source_storage_key("baseline", path)
            for path in references_by_path
        }
        existing_by_key: dict[tuple[str, str], Asset] = {}
        if storage_keys:
            existing_assets = session.scalars(
                select(Asset).where(Asset.storage_key.in_(storage_keys.values()))
            )
            existing_by_key = {
                (asset.storage_key, asset.sha256): asset for asset in existing_assets
            }
        assets: dict[str, Asset] = {}
        for manifest_path, references in references_by_path.items():
            storage_key = storage_keys[manifest_path]
            expected_hashes = {reference.sha256 for reference in references}
            if len(expected_hashes) != 1:
                raise ImportValidationError(
                    f"Manifest path {manifest_path!r} has conflicting hashes"
                )
            expected_hash = next(iter(expected_hashes))
            category, normal_access_level = self._asset_policy(
                manifest_path,
                references,
            )
            try:
                inspected = store.inspect(storage_key)
                expected_state = AssetIntegrityState.VERIFIED
            except AssetMimeMismatchError:
                inspected = store.inspect(
                    storage_key,
                    validate_extension=False,
                    validate_content=False,
                )
                expected_state = AssetIntegrityState.QUARANTINED
            expected_access_level = (
                AssetAccessLevel.ADMIN
                if expected_state is AssetIntegrityState.QUARANTINED
                else normal_access_level
            )
            existing = existing_by_key.get((storage_key, expected_hash))
            if existing is not None:
                if (
                    inspected.sha256 != expected_hash
                    or inspected.byte_size != existing.byte_size
                    or inspected.mime_type != existing.mime_type
                ):
                    raise ImportValidationError(
                        f"Existing asset content failed integrity verification: "
                        f"{manifest_path}"
                    )
                if existing.integrity_state is not expected_state:
                    raise ImportValidationError(
                        f"Existing asset has an unacceptable integrity state: "
                        f"{manifest_path}"
                    )
                if (
                    existing.category is not category
                    or existing.access_level is not expected_access_level
                ):
                    raise ImportValidationError(
                        "Existing asset policy does not match the resolved "
                        f"reference: {manifest_path}"
                    )
                assets[manifest_path] = existing
                continue
            if inspected.sha256 != expected_hash:
                raise ImportValidationError(
                    f"Source asset changed after reconciliation: {manifest_path}"
                )
            for prior in existing_by_key.values():
                if (
                    prior.storage_key == storage_key
                    and prior.integrity_state
                    in {
                        AssetIntegrityState.REGISTERED,
                        AssetIntegrityState.VERIFIED,
                    }
                ):
                    prior.integrity_state = AssetIntegrityState.SUPERSEDED
            asset = Asset(
                id=uuid4(),
                storage_key=storage_key,
                original_filename=PurePosixPath(manifest_path).name,
                sha256=inspected.sha256,
                byte_size=inspected.byte_size,
                mime_type=inspected.mime_type,
                width=inspected.width,
                height=inspected.height,
                page_count=inspected.page_count,
                category=category,
                access_level=expected_access_level,
                integrity_state=expected_state,
                import_batch_id=batch_id,
                derivation_metadata={},
                source_metadata={
                    "source_root_key": "baseline",
                    "manifest_path": manifest_path,
                    **(
                        {"reason": "mime_mismatch"}
                        if expected_state is AssetIntegrityState.QUARANTINED
                        else {}
                    ),
                },
                verified_at=(
                    datetime.now(UTC)
                    if expected_state is AssetIntegrityState.VERIFIED
                    else None
                ),
            )
            session.add(asset)
            assets[manifest_path] = asset
        session.flush()
        return assets

    @staticmethod
    def _asset_policy(
        manifest_path: str,
        references: list[ResolvedAssetReference],
    ) -> tuple[AssetCategory, AssetAccessLevel]:
        roles = {reference.link_role for reference in references}
        if roles & {"article_pdf", "visual_source_pdf"}:
            return AssetCategory.ARTICLE_PDF, AssetAccessLevel.REVIEWER
        if "visual_crop" in roles:
            return AssetCategory.REVIEWED_CROP, AssetAccessLevel.REVIEWER
        if "visual_source_crop" in roles:
            return AssetCategory.OCSR_INPUT, AssetAccessLevel.REVIEWER
        try:
            category = classify_source_asset(PurePosixPath(manifest_path))
        except ValueError:
            category = AssetCategory.EXTERNAL_SOURCE
        access_level = (
            AssetAccessLevel.REVIEWER
            if category
            in {
                AssetCategory.ARTICLE_PDF,
                AssetCategory.SI_PDF,
                AssetCategory.SI_TABLE,
                AssetCategory.SI_ARCHIVE,
                AssetCategory.PAGE_RENDER,
                AssetCategory.PAGE_THUMBNAIL,
                AssetCategory.OCSR_INPUT,
                AssetCategory.REVIEWED_CROP,
            }
            else AssetAccessLevel.ADMIN
        )
        return category, access_level

    @staticmethod
    def _link_assets(
        session: Session,
        batch_id: UUID,
        report: ReconciliationReport,
        assets: dict[str, Asset],
    ) -> None:
        links: list[ImportAssetLink] = []
        seen: set[tuple[str, str, str, UUID]] = set()
        for reference in report.asset_linkage.resolved:
            asset = assets.get(reference.manifest_path)
            if asset is None:
                raise ImportValidationError(
                    f"Resolved asset was not registered: {reference.manifest_path}"
                )
            key = (
                reference.record_type,
                reference.original_id,
                reference.link_role,
                asset.id,
            )
            if key in seen:
                continue
            seen.add(key)
            links.append(
                ImportAssetLink(
                    id=uuid4(),
                    import_batch_id=batch_id,
                    record_type=reference.record_type,
                    original_id=reference.original_id,
                    asset_id=asset.id,
                    link_role=reference.link_role,
                    source_reference=reference.manifest_path,
                )
            )
        session.add_all(links)
        session.flush()
