"""Read-only approval rounds. Technical supplements never become human attestations."""
from copy import deepcopy
from dataclasses import replace
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.audit.service import canonical_content_hash
from app.papers.metadata import ARTICLE_METADATA_DEFAULTS, ArticleMetadata, validate_article_evidence_sources
from app.papers.filters import PaperFilters
from app.papers.models import Paper
from app.publications.models import AdminDecision
from app.publications.schemas import (
    AdminDecisionResponse, AdminSubmissionListItem, ChangeEventResponse,
    ReviewerRoundsResponse, ReviewerRoundVersion, SubmissionComparisonResponse,
    SupplementComparison,
)
from app.publications.service import PublicationService, SubmissionReview
from app.publications.reviewer_projection import reviewer_only_baseline, verified_repairs
from app.users.models import User
from app.workspaces.models import (
    ChangeActorKind, ChangeEvent, PaperSubmission, PaperWorkspace, ReviewTask,
    ReviewTaskState, WorkspaceState,
)
from app.workspaces.snapshot import canonical_snapshot_hash


def is_reviewer_submission(submission: PaperSubmission, boundary: ChangeEvent | None) -> bool:
    after = boundary.after_value or {} if boundary else {}
    return bool(boundary and boundary.actor_kind is ChangeActorKind.REVIEWER
        and boundary.actor_id == submission.submitted_by_id
        and boundary.workspace_id == submission.workspace_id
        and boundary.paper_id == submission.paper_id
        and after.get('submission_id') == str(submission.id)
        and after.get('content_hash') == submission.content_hash
        and after.get('metadata_supplement') is not True
        and canonical_snapshot_hash(submission.snapshot) == submission.content_hash)


def _event(event: ChangeEvent) -> ChangeEventResponse:
    return ChangeEventResponse.model_validate(event, from_attributes=True)


def _metadata_only(parent: PaperSubmission, child: PaperSubmission) -> bool:
    """Only known article metadata and its review section may be supplemented."""
    def science(snapshot):
        result = deepcopy(snapshot)
        result.pop('workspace_version', None)
        result['paper'] = {k: v for k, v in result['paper'].items() if k not in ARTICLE_METADATA_DEFAULTS}
        result['sections'] = [r for r in result['sections'] if r['section_key'] != 'bibliography']
        return result
    return (canonical_snapshot_hash(child.snapshot) == child.content_hash
        and canonical_snapshot_hash(parent.snapshot) == parent.content_hash
        and science(parent.snapshot) == science(child.snapshot))


def _path_value(paper, path):
    value = paper
    for key in path:
        if isinstance(value, dict):
            value = value.get(key, ARTICLE_METADATA_DEFAULTS.get(key, []))
        elif isinstance(value, list) and isinstance(key, int) and key < len(value):
            value = value[key]
        else:
            return None
    return value


def _set_path(paper, path, value):
    for key in path[:-1]:
        paper = paper.setdefault(key, {}) if isinstance(paper, dict) else paper[key]
    paper[path[-1]] = deepcopy(value)


def _apply_metadata_paths(paper, changes):
    if any(_path_value(paper, path) not in (before, after) for path, before, after in changes):
        return False
    # Evidence may only be appended if the historical entry still has the same
    # identity. Its path is checked separately by the caller's audited delta.
    for path, _before, after in changes:
        _set_path(paper, path, after)
    return True


class RoundHistory:
    def __init__(self, session: Session, workspace_id: UUID):
        self.session = session
        self.submissions = list(session.scalars(select(PaperSubmission).where(
            PaperSubmission.workspace_id == workspace_id).order_by(PaperSubmission.submission_number)))
        self.events = tuple(session.scalars(select(ChangeEvent).where(
            ChangeEvent.workspace_id == workspace_id).order_by(ChangeEvent.occurred_at, ChangeEvent.id)))
        self.boundaries = {e.entity_id: e for e in self.events
            if e.entity_type == 'paper_submission' and e.action == 'workspace.submit'}
        self.indices = {e.id: i for i, e in enumerate(self.events)}
        self.reviewer = [s for s in self.submissions if is_reviewer_submission(s, self.boundaries.get(s.id))]
        self.supplements: dict[UUID, list[PaperSubmission]] = {}
        self.origins: dict[UUID, PaperSubmission] = {}
        self.warnings: list[str] = []
        self.metadata_audits = list(session.scalars(select(AuditEvent).where(
            AuditEvent.action == 'paper.article_metadata_supplement',
            AuditEvent.details['workspace_id'].astext == str(workspace_id))))
        for submission in self.submissions:
            boundary = self.boundaries.get(submission.id)
            if not boundary or (boundary.after_value or {}).get('metadata_supplement') is not True:
                if submission not in self.reviewer:
                    self.warnings.append('A submission boundary is unverified; it is not counted as a Reviewer submission.')
                continue
            end = self.indices[boundary.id] + 1
            origin = PublicationService._supplement_origin(session, submission, self.events[:end])
            chain = [s for s in self.submissions if origin and
                origin[0].submission_number <= s.submission_number <= submission.submission_number]
            if (not origin or origin[0] not in self.reviewer
                    or not all(_metadata_only(a, b) for a, b in zip(chain, chain[1:]))):
                self.warnings.append('Metadata supplement history cannot be verified; no additions have been hidden.')
                continue
            self.origins[submission.id] = origin[0]
            self.supplements.setdefault(origin[0].id, []).append(submission)
        self.decisions = {d.submission_id: d for d in session.scalars(select(AdminDecision).where(
            AdminDecision.submission_id.in_([s.id for s in self.submissions])))}
        self.workspace = session.get(PaperWorkspace, workspace_id)
        self.task = session.get(ReviewTask, self.submissions[-1].review_task_id) if self.submissions else None

    def can_decide(self, submission):
        return bool(self.submissions and self.submissions[-1].id == submission.id
            and submission in self.reviewer and submission.id not in self.decisions
            and self.workspace and self.workspace.state is WorkspaceState.SUBMITTED
            and self.task and self.task.status is ReviewTaskState.SUBMITTED)

    def versions(self) -> list[ReviewerRoundVersion]:
        authors = {u.id: u.display_name for u in self.session.scalars(select(User).where(
            User.id.in_([s.submitted_by_id for s in self.reviewer])))}
        result = []
        for index, submission in enumerate(self.reviewer):
            decision = self.decisions.get(submission.id)
            children = self.supplements.get(submission.id, [])
            followup = self.decisions.get(children[-1].id) if children else None
            if self.supplements.get(submission.id):
                # The linked supplement service closed this record administratively.
                status = 'awaiting_reviewer' if index == len(self.reviewer) - 1 else 'supplemented'
                decision = None
            elif decision:
                status = decision.action.value
            else:
                status = 'pending' if self.can_decide(submission) else 'superseded'
            result.append(ReviewerRoundVersion(
                **{field: getattr(submission, field) for field in (
                    'id', 'paper_id', 'workspace_id', 'submission_number', 'submitted_by_id',
                    'submitted_at', 'content_hash', 'reviewer_note')},
                round_number=index + 1, submitted_by_name=authors.get(submission.submitted_by_id, ''),
                status=status, decision=AdminDecisionResponse.model_validate(decision, from_attributes=True) if decision else None,
                followup_decision=AdminDecisionResponse.model_validate(followup, from_attributes=True) if followup else None))
        return result

    def supplement_projection(self, origin: PaperSubmission, phase: str) -> SupplementComparison | None:
        children = self.supplements.get(origin.id, [])
        if not children:
            return None
        last = children[-1]
        start = self.indices[self.boundaries[origin.id].id] + 1
        end = self.indices[self.boundaries[last.id].id] + 1
        return SupplementComparison(phase=phase, count=len(children), submitted_at=last.submitted_at,
            snapshot=last.snapshot, comparison=SubmissionComparisonResponse(kind='previous_submission',
                baseline_submission_number=None, baseline_snapshot=origin.snapshot,
                events=[_event(e) for e in self.events[start:end]], warnings=[]))

    def metadata_delta(self, event, source):
        """An AI label alone is never authority to hide a recorded change."""
        from app.publications.draft_metadata import additive_metadata_delta, validated_runtime_provenance
        try:
            audits = [a for a in self.metadata_audits if a.details.get('change_event_id') == str(event.id)]
            if len(audits) != 1:
                raise ValueError('missing or ambiguous audit binding')
            audit = audits[0]
            details = audit.details
            identity = details.get('request_identity', {})
            if (event.actor_kind is not ChangeActorKind.AI or event.actor_id is not None
                    or event.entity_type != 'paper' or event.entity_id != event.paper_id
                    or audit.target_type != 'paper' or audit.target_id != event.paper_id
                    or audit.paper_id != event.paper_id or audit.result != 'success'
                    or details.get('source_sha256') != source['sha256']
                    or details.get('workspace_id') != str(event.workspace_id)
                    or details.get('event_payload_sha256') != canonical_content_hash({'before': event.before_value, 'after': event.after_value})
                    or details.get('request_payload_sha256') != canonical_content_hash(identity)
                    or identity.get('actor_id') != str(audit.actor_id)
                    or identity.get('request_id') != audit.request_id
                    or identity.get('workspace_id') != str(event.workspace_id)
                    or identity.get('expected_snapshot_hash') != audit.before_hash
                    or identity.get('provenance') != details.get('provenance')):
                raise ValueError('audit identity or content mismatch')
            validated_runtime_provenance(details['provenance'], source['sha256'])
            changes = additive_metadata_delta(event.before_value, event.after_value)
            # Use partial validation for the changed fields: an abstract/status
            # companion can already exist outside this particular event.
            class PartialMetadata(ArticleMetadata):
                partial_metadata = True
            PartialMetadata.model_validate(event.after_value)
            validate_article_evidence_sources(event.after_value, page_count=source['page_count'], sha256=source['sha256'])
            return changes
        except (ValueError, TypeError, KeyError, AttributeError):
            warning = f'Metadata supplement {event.id} cannot be verified; inspect its additions in the full submission or main comparison.'
            if warning not in self.warnings:
                self.warnings.append(warning)
            return None

    def rewind_metadata_before_review(self, baseline, events):
        """Recover the AI-only start before the earliest human edit.

        The ordinary reconstruction starts at that human edit and therefore
        already contains earlier fills. Reverse their verified chain first so
        chronological replay can show every evidence addition exactly once.
        An unbound older event cannot be silently inherited into that baseline.
        """
        if baseline is None:
            return None
        result = deepcopy(baseline)
        for event in reversed(events):
            if event.action != 'bibliography.ai_supplement':
                continue
            changes = self.metadata_delta(event, baseline['source'])
            if changes is None:
                return None
            if any(_path_value(result['paper'], path) != after for path, _, after in changes):
                self.warnings.append(f'Metadata supplement {event.id} predates the Reviewer boundary but cannot be reversed safely; the comparison is unavailable.')
                return None
            for path, before, _after in reversed(changes):
                _set_path(result['paper'], path, before)
        return result

    def draft_supplement_projection(self, events, phase, baseline, existing=None):
        """Merge additive paths into a comparison baseline and one folded phase."""
        if baseline is None:
            # Still validate attribution so unavailable histories remain explicit.
            for event in events:
                if event.action == 'bibliography.ai_supplement':
                    self.metadata_delta(event, self.submissions[0].snapshot['source'])
            return None
        starting = deepcopy(existing.comparison.baseline_snapshot if existing else baseline)
        adjusted = deepcopy(baseline)
        count = existing.count if existing else 0
        projected_events = list(existing.comparison.events) if existing else []
        latest_time = existing.submitted_at if existing else None
        for event in events:
            if event.action != 'bibliography.ai_supplement':
                continue
            changes = self.metadata_delta(event, baseline['source'])
            if changes is None:
                continue
            # For evidence deltas, also check all non-evidence fields of the
            # referenced historical entry before applying to a human baseline.
            identity_ok = all(
                {k: v for k, v in (_path_value(adjusted['paper'], path[:-1]) or {}).items() if k != 'evidence'}
                == {k: v for k, v in (_path_value(event.before_value, path[:-1]) or {}).items() if k != 'evidence'}
                for path, _, _ in changes if path[-1] == 'evidence')
            if not identity_ok or not _apply_metadata_paths(adjusted['paper'], changes):
                self.warnings.append(f'Metadata supplement {event.id} overlaps a prior human change; the original comparison is retained.')
                continue
            # A fill before the earliest Reviewer edit is already in the human
            # starting state. Show its original empty value only in the folded
            # supplement comparison, never remove it from the human baseline.
            if not existing:
                for path, before, after in changes:
                    if _path_value(starting['paper'], path) == after:
                        _set_path(starting['paper'], path, before)
            count += 1
            projected_events.append(_event(event))
            latest_time = event.occurred_at
        if count == 0:
            return None
        baseline['paper'] = deepcopy(adjusted['paper'])
        return SupplementComparison(phase=phase, count=count, submitted_at=latest_time,
            snapshot=adjusted, comparison=SubmissionComparisonResponse(kind='previous_submission',
                baseline_submission_number=None, baseline_snapshot=starting,
                events=projected_events, warnings=[]))


def get_reviewer_round_review(session: Session, *, submission_id: UUID, actor
        ) -> tuple[SubmissionReview, ReviewerRoundsResponse]:
    service = PublicationService()
    requested = service.get_submission_review(session, submission_id=submission_id, actor=actor)
    history = RoundHistory(session, requested.submission.workspace_id)
    selected = history.origins.get(submission_id, requested.submission)
    versions = history.versions()
    if selected not in history.reviewer:
        warning = 'This is not a verified Reviewer submission. Review the complete immutable history.'
        return replace(requested, comparison_kind='unavailable', baseline_snapshot=None,
            comparison_warnings=(*requested.comparison_warnings, warning)), ReviewerRoundsResponse(
                requested_submission_id=submission_id, selected_round_number=None, versions=versions,
                can_decide=False, supplements=[], warnings=[*history.warnings, warning])
    index = history.reviewer.index(selected)
    review = service.get_submission_review(session, submission_id=selected.id, actor=actor)
    supplements = []
    selected_end = history.indices[history.boundaries[selected.id].id] + 1
    if index:
        previous = history.reviewer[index - 1]
        baseline = deepcopy(previous.snapshot)
        prefill = history.supplement_projection(previous, 'before_submission')
        if prefill:
            # Use only verified metadata additions as the human-edit starting point.
            # The real preceding snapshot remains accessible through version navigation.
            for field in ARTICLE_METADATA_DEFAULTS:
                if field in prefill.snapshot['paper']:
                    baseline['paper'][field] = deepcopy(prefill.snapshot['paper'][field])
                else:
                    baseline['paper'].pop(field, None)
            section = next((s for s in prefill.snapshot['sections'] if s['section_key'] == 'bibliography'), None)
            if section:
                baseline['sections'] = [deepcopy(section) if s['section_key'] == 'bibliography' else s for s in baseline['sections']]
        start = history.indices[history.boundaries[previous.id].id] + 1
        events = history.events[start:selected_end]
        prefill = history.draft_supplement_projection(events, 'before_submission', baseline, prefill)
        if prefill:
            supplements.append(prefill)
        human_events = tuple(e for e in events if e.actor_kind is ChangeActorKind.REVIEWER)
        review = replace(review, comparison_kind='previous_submission',
            baseline_submission_number=index, baseline_snapshot=baseline,
            comparison_events=human_events,
            reviewer_diff=tuple(e for e in human_events if e.action != 'workspace.submit'),
            comparison_warnings=tuple(history.warnings), reviewer_submission=None, supplement_count=0)
    else:
        baseline = deepcopy(review.baseline_snapshot)
        first_human = next((i for i, e in enumerate(history.events[:selected_end])
            if e.actor_kind is ChangeActorKind.REVIEWER and e.action != 'workspace.submit'), selected_end)
        baseline = history.rewind_metadata_before_review(baseline, history.events[:first_human])
        prefill = history.draft_supplement_projection(history.events[:selected_end], 'before_submission', baseline)
        if prefill:
            supplements.append(prefill)
        review = replace(review, baseline_snapshot=baseline,
            comparison_kind=review.comparison_kind if baseline is not None else 'unavailable',
            comparison_events=tuple(e for e in review.comparison_events if e.actor_kind is ChangeActorKind.REVIEWER),
            comparison_warnings=tuple([*review.comparison_warnings, *history.warnings]))
    # Filter the scientific comparison itself, not just its displayed events.
    start = (history.indices[history.boundaries[history.reviewer[index - 1].id].id] + 1
             if index else next((i for i, e in enumerate(history.events[:selected_end])
                 if e.actor_kind is ChangeActorKind.REVIEWER and e.action != 'workspace.submit'), selected_end))
    round_events = history.events[start:selected_end]
    if any('.repair_' in e.action for e in round_events):
        baseline, warnings = reviewer_only_baseline(selected.snapshot, round_events,
            verified_repair_ids=verified_repairs(session, round_events, selected.snapshot['source']),
            expected_start=history.reviewer[index - 1].snapshot if index else None)
        if any(e.action == 'bibliography.ai_supplement'
               and history.metadata_delta(e, selected.snapshot['source']) is None for e in round_events):
            baseline = None
            warnings.append('Unverified metadata additions; Reviewer-only comparison is unavailable.')
        review = replace(review, baseline_snapshot=baseline,
            comparison_kind=('previous_submission' if index else 'reviewer_start') if baseline is not None else 'unavailable',
            comparison_warnings=tuple([*warnings, *history.warnings]))
    after = history.supplement_projection(selected, 'after_submission')
    after_end = history.indices[history.boundaries[history.reviewer[index + 1].id].id] if index + 1 < len(history.reviewer) else len(history.events)
    after_baseline = deepcopy(after.snapshot if after else selected.snapshot)
    after = history.draft_supplement_projection(history.events[selected_end:after_end],
        'after_submission', after_baseline, after)
    if after:
        supplements.append(after)
    review = replace(review, comparison_warnings=tuple(dict.fromkeys([*review.comparison_warnings, *history.warnings])))
    return review, ReviewerRoundsResponse(requested_submission_id=submission_id,
        selected_round_number=index + 1, versions=versions, can_decide=history.can_decide(selected),
        supplements=supplements, warnings=history.warnings)


def list_reviewer_rounds(session: Session, *, actor, article_filters: PaperFilters | None = None) -> list[AdminSubmissionListItem]:
    PublicationService._require_admin(actor)
    # Fetch only identities, submit boundaries and status. Never load scientific
    # snapshots or the article's full edit history just to render the directory.
    rows = session.execute(select(
        PaperSubmission.id, PaperSubmission.paper_id, PaperSubmission.workspace_id,
        PaperSubmission.review_task_id, PaperSubmission.submission_number,
        PaperSubmission.content_hash, PaperSubmission.submitted_by_id, PaperSubmission.submitted_at,
        PaperSubmission.snapshot['paper']['paper_key'].astext.label('paper_key'),
        PaperSubmission.snapshot['paper']['title'].astext.label('title'),
        PaperSubmission.snapshot.has_key('problem_report').label('problem_report'),
        User.display_name, ChangeEvent.id.label('event_id'), ChangeEvent.actor_kind,
        ChangeEvent.actor_id, ChangeEvent.before_value, ChangeEvent.after_value,
        ChangeEvent.occurred_at, AdminDecision.action.label('decision_action'),
        PaperWorkspace.state.label('workspace_state'), ReviewTask.status.label('task_status'),
    ).join(Paper, Paper.id == PaperSubmission.paper_id)
        .join(PaperWorkspace, PaperWorkspace.id == PaperSubmission.workspace_id)
        .join(ReviewTask, ReviewTask.id == PaperSubmission.review_task_id)
        .outerjoin(User, User.id == PaperSubmission.submitted_by_id)
        .outerjoin(AdminDecision, AdminDecision.submission_id == PaperSubmission.id)
        .outerjoin(ChangeEvent, and_(ChangeEvent.entity_id == PaperSubmission.id,
            ChangeEvent.entity_type == 'paper_submission', ChangeEvent.action == 'workspace.submit',
            ChangeEvent.workspace_id == PaperSubmission.workspace_id, ChangeEvent.paper_id == PaperSubmission.paper_id))
        .where(*(article_filters or PaperFilters()).predicates())
        .order_by(PaperSubmission.workspace_id, PaperSubmission.submission_number)).all()
    workspaces: dict[UUID, list] = {}
    for row in rows:
        workspaces.setdefault(row.workspace_id, []).append(row)
    items = []
    for history in workspaces.values():
        actual, origins, by_id = [], {}, {}
        for row in history:
            after, before = row.after_value or {}, row.before_value or {}
            valid = bool(row.event_id and after.get('submission_id') == str(row.id)
                and after.get('content_hash') == row.content_hash and row.actor_id == row.submitted_by_id)
            if valid and row.actor_kind is ChangeActorKind.REVIEWER and after.get('metadata_supplement') is not True:
                actual.append(row)
                origins[str(row.id)] = row
            elif valid and row.actor_kind is ChangeActorKind.ADMIN and after.get('metadata_supplement') is True:
                parent = by_id.get(before.get('submission_id'))
                if (parent and str(parent.id) in origins and before.get('content_hash') == parent.content_hash
                        and parent.submission_number == row.submission_number - 1
                        and parent.review_task_id == row.review_task_id
                        and (parent.occurred_at, parent.event_id) < (row.occurred_at, row.event_id)):
                    origins[str(row.id)] = origins[str(parent.id)]
            by_id[str(row.id)] = row
        latest = history[-1]
        selected = origins.get(str(latest.id), latest)
        verified = str(latest.id) in origins
        if not verified:
            status = 'unavailable'
        elif selected.id != latest.id:
            status = 'awaiting_reviewer'
        elif latest.decision_action:
            status = latest.decision_action.value
        else:
            status = 'pending' if latest.workspace_state is WorkspaceState.SUBMITTED and latest.task_status is ReviewTaskState.SUBMITTED else 'superseded'
        items.append(AdminSubmissionListItem(submission_id=selected.id, paper_id=selected.paper_id,
            submission_kind='problem_report' if selected.problem_report else 'standard',
            workspace_id=selected.workspace_id, submission_number=selected.submission_number,
            content_hash=selected.content_hash, submitted_by_id=selected.submitted_by_id,
            submitted_at=selected.submitted_at, paper_key=selected.paper_key, title=selected.title,
            reviewer_round_number=next((i + 1 for i, r in enumerate(actual) if r.id == selected.id), None) if verified else None,
            review_status=status, submitted_by_name=selected.display_name, review_entry_id=latest.id,
            review_warning=None if verified else 'Latest submission history is unverified; open the read-only record to inspect it.'))
    return sorted(items, key=lambda item: (item.submitted_at, item.submission_id), reverse=True)
