"""Offline producer handoff checks. A passed report is never scientific approval."""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import hashlib
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai_prefill.assistance_contracts import CandidateEnvelope, computed_hashes
from app.ai_prefill.assistance_coverage import CompoundInventory, check_compound_coverage
from app.ai_prefill.assistance_validation import validate_candidate
from app.ai_prefill.assistance_lineage import diagnose_lineages

SOURCE_REVIEW_CHECKS = (
    'compound_scope', 'measurement_coverage', 'activity_semantics',
    'structure_identity', 'source_crops', 'sar_reasoning', 'synthesis_paths',
)


class SourceReviewItem(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    check_id: Literal['compound_scope', 'measurement_coverage', 'activity_semantics',
                      'structure_identity', 'source_crops', 'sar_reasoning', 'synthesis_paths']
    status: Literal['checked', 'unresolved', 'not_checked', 'not_applicable']
    details: str = Field(min_length=1)
    source_locations: list[str] = Field(default_factory=list)
    checked_edge_refs: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def check_locations(self):
        if any(not x.strip() for x in [*self.source_locations, *self.checked_edge_refs]):
            raise ValueError('source locations and edge refs must be nonblank')
        if self.status == 'checked' and not self.source_locations:
            raise ValueError('checked source review requires actual source locations')
        return self


class SourceSelfReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    self_review_version: Literal[1]
    candidate_file_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    reviewer_type: Literal['producer_self_check']
    checks: list[SourceReviewItem]

    @model_validator(mode='after')
    def unique_checks(self):
        keys = [x.check_id for x in self.checks]
        if len(keys) != len(set(keys)):
            raise ValueError('self-review contains duplicate check IDs')
        return self


def _norm(text: str | None) -> str:
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text or '')).strip().casefold()


def self_check_candidate(
    candidate: CandidateEnvelope, inventory: CompoundInventory | None, *,
    candidate_file_bytes: bytes, self_review: SourceSelfReview | None = None,
) -> dict:
    # Bind the report to the actual file, not caller-supplied detached content.
    if CandidateEnvelope.model_validate_json(candidate_file_bytes) != candidate:
        raise ValueError('candidate file bytes differ from parsed candidate')
    file_hash = hashlib.sha256(candidate_file_bytes).hexdigest()
    validation = validate_candidate(candidate)
    coverage = check_compound_coverage(candidate, inventory) if inventory is not None else {
        "status": "unknown", "required_count": None, "covered_count": None, "missing_labels": []}
    lineage_diagnostics = diagnose_lineages(candidate)
    issues: list[dict] = list(lineage_diagnostics['issues'])

    def add(code, severity, path, message, **details):
        issues.append(dict(code=code, severity=severity, path=path, message=message, details=details))

    for item in validation.issues:
        add(item.code, 'blocking' if item.severity == 'error' else 'review',
            item.path, item.message, **item.details)
    if coverage['status'] == 'incomplete':
        add('COMPOUND_COVERAGE_INCOMPLETE', 'blocking', 'payload.compounds',
            'Required inventory identities are missing or ambiguous; omission notes do not satisfy coverage.',
            missing_labels=coverage['missing_labels'], ambiguous_matches=coverage['ambiguous_matches'])

    activities = candidate.payload.activities
    seen = {}
    for i, a in enumerate(activities):
        path = f'payload.activities[{i}]'
        metric = _norm(a.metric)
        if re.fullmatch(r'(?:(?:oral|iv|i\.v\.|po|p\.o\.|administered|administered oral) )?dose|给药剂量|剂量', metric):
            add('DOSE_AS_ENDPOINT', 'blocking', path,
                'Administered dose is a condition; retain it on the measured PK/efficacy observations. ED50/MTD remain valid endpoints.')
        # Narrow metric semantics, not assay/context keyword matching.
        ratio = bool(re.match(r'^(?:selectivity (?:index|ratio)|s\.?i\.?(?=$|\s|\())', metric))
        if ratio and _norm(a.unit) not in {'', '1', 'dimensionless', 'unitless', 'ratio', '无量纲'}:
            add('DIMENSIONLESS_METRIC_UNIT', 'blocking', path + '.unit',
                'A selectivity ratio has no concentration unit; verify the source column.', unit=a.unit)
        key = (a.compound_ref, _norm(a.assay_name), metric, a.operator, a.value,
               _norm(a.unit), _norm(a.context), a.evidence_ref)
        if key in seen:
            add('DUPLICATE_ACTIVITY', 'blocking', path,
                'Same compound, assay, endpoint, value, condition and evidence repeated; reconcile before handoff.',
                first_index=seen[key])
        else:
            seen[key] = i

    edge_refs = set()
    for i, lineage in enumerate(candidate.payload.lineages):
        if lineage.lineage_type == 'unspecified':
            add('LINEAGE_TYPE_MISSING', 'blocking', f'payload.lineages[{i}]',
                'Classify SAR or synthesis explicitly; do not infer synthesis from numbering.')
        edge_refs.update(e.ref for e in lineage.edges)
    activity_refs = {a.compound_ref for a in activities}
    no_activity = [c.compound_label for c in candidate.payload.compounds if c.ref not in activity_refs]
    if no_activity:
        add('COMPOUNDS_WITHOUT_ACTIVITY', 'review', 'payload.compounds',
            'Check source and distinguish no reported data from extraction omission; do not invent measurements.', labels=no_activity)

    if self_review is None:
        add('SELF_REVIEW_MISSING', 'blocking', 'self_review',
            'Source self-review not supplied; this is a preflight report, not a completed delivery check.')
    else:
        if self_review.candidate_file_sha256 != file_hash:
            add('SELF_REVIEW_STALE', 'blocking', 'self_review.candidate_file_sha256',
                'Candidate changed after source review; recheck affected sections and bind to final file.')
        present = {x.check_id for x in self_review.checks}
        missing = sorted(set(SOURCE_REVIEW_CHECKS) - present)
        if missing:
            add('SELF_REVIEW_INCOMPLETE', 'blocking', 'self_review.checks', 'Required source-review sections absent.', missing=missing)
        for x in self_review.checks:
            path = f'self_review.checks.{x.check_id}'
            if x.status in {'not_checked', 'unresolved'}:
                add('SOURCE_REVIEW_UNRESOLVED', 'blocking', path, x.details, status=x.status)
            unknown = sorted(set(x.checked_edge_refs) - edge_refs)
            if unknown:
                add('SELF_REVIEW_UNKNOWN_EDGE', 'blocking', path,
                    'Checked edge references must exist; a grouped or route-local summary is not a candidate edge.', refs=unknown)
            # Always-applicable scope reviews cannot be waived.
            if x.status == 'not_applicable' and x.check_id in {'compound_scope', 'measurement_coverage', 'structure_identity'}:
                add('SELF_REVIEW_INVALID_WAIVER', 'blocking', path, 'This source review applies to every compound extraction.')
            relevant = {'sar_reasoning':'sar', 'synthesis_paths':'synthesis'}.get(x.check_id)
            if x.status == 'not_applicable' and relevant and any(l.lineage_type == relevant and l.edges for l in candidate.payload.lineages):
                add('SELF_REVIEW_INVALID_WAIVER', 'blocking', path, 'Candidate contains edges of this type.')
            if x.status == 'not_applicable' and ((x.check_id == 'activity_semantics' and activities) or (x.check_id == 'source_crops' and candidate.payload.structure_locators)):
                add('SELF_REVIEW_INVALID_WAIVER', 'blocking', path, 'Candidate contains data requiring this review.')
    counts = Counter(x['severity'] for x in issues)
    return {
        'self_check_version': 1, 'generated_at': datetime.now(UTC).isoformat(),
        'candidate_id': candidate.candidate_id, 'candidate_file_sha256': file_hash,
        'canonical_candidate_sha256': computed_hashes(candidate).candidate_sha256,
        'status': 'needs_revision' if counts['blocking'] else 'ready_for_independent_review',
        'scientific_approval': False, 'whole_population_accuracy': None,
        'issue_counts': {'blocking': counts['blocking'], 'review': counts['review']},
        'issues': issues, 'compound_coverage': coverage,
        'lineage_diagnostics': lineage_diagnostics,
        'self_review_counts': dict(Counter(x.status for x in self_review.checks)) if self_review else {},
        'limitations': [
            'Offline: no original source text/images read; declared source review is not independently verified.',
            'No whole-paper measurement or edge completeness denominator is inferred.',
            'Structure/SD/SEM/ND/transformation correctness still requires source review.',
            'SAR without text evidence is allowed; missing evidence warnings are not blocking.',
            'This command neither edits candidates nor applies/approves Preview data.',
        ],
    }
