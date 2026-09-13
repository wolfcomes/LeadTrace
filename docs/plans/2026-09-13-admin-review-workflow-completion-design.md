# LeadTrace Admin Review Workflow Completion Design

**Status:** Approved on 2026-09-13

## Goal

Complete the browser workflow needed to turn the imported 672-Paper corpus into
assigned, traceable human review work. The website must distinguish machine
extraction from human verification, let an Admin inspect the imported corpus
before its first publication, manage account roles, and assign review tasks.

## Product terminology

The website must not describe the two dataset states only as `v1` and `v2`.
Those numbers are ambiguous because they do not explain the evidence quality.

- **AI-extracted baseline** (`AI 提取基线`): the initial imported corpus. Its
  images and structured records were extracted by automated processing and have
  not been independently verified Paper by Paper.
- **Human-verified dataset** (`人工核验数据集`): a later Release containing
  changes that passed the Reviewer submission and Admin approval workflow.

Release keys remain immutable technical identifiers. The new terminology is
stored in generated default titles and shown in the Admin and published user
interfaces. User-provided titles remain allowed, but the interface always shows
the dataset class separately so a custom title cannot hide its review status.

## AI-extracted baseline preview

Add an Admin-only, candidate-scoped preview under the import workflow. It reads
the immutable revisions associated with the selected import candidate rather
than the current published Release. This keeps unpublished material out of the
Visitor API and prevents later edits from changing what an Admin approved.

The preview provides:

- paginated access to all 672 imported Papers;
- title and DOI search;
- filters for Lineage presence, structure state, review state, and unresolved
  asset references;
- a compact quality summary for each Paper;
- a Paper detail view using the candidate revisions and registered assets;
- an explicit `AI 提取 / 未经人工核验 / 未发布` status treatment; and
- links back to the candidate approval action.

The candidate manifest and the preview query must agree on corpus count and
revision ownership. A Paper not present in the candidate snapshot must return
404 even if a Paper with the same stable identity exists elsewhere.

## Admin Paper workflow states

The Admin Paper library derives one human-review workflow state for every
Paper. These states describe scientific processing and assignment progress;
they do not describe publication visibility:

```text
initial
-> ai_baseline_unassigned
-> ai_baseline_in_review
-> human_review_pending_approval
-> admin_approved
```

The Chinese labels are:

- `initial`: `初始状态` - the Paper is registered, but it has no usable AI
  image/structure extraction baseline in the selected candidate or Release;
- `ai_baseline_unassigned`: `AI 提取基线（未分配）` - AI-extracted content is
  available and no active human-review task has been assigned;
- `ai_baseline_in_review`: `AI 提取基线（已分配，人工核验进行中）` - an active
  task or editable changeset exists for the Paper;
- `human_review_pending_approval`: `人工核验结束（待批）` - the Reviewer has
  submitted a frozen changeset and an Admin decision is pending; and
- `admin_approved`: `Admin 已批准` - an Admin approved the submitted human
  verification, whether or not the successor Release has been published yet.

Publication is an independent `unpublished` or `published` dimension. An
`ai_baseline_unassigned` Paper may be published immediately as part of the
AI-extracted baseline. Every interface that exposes such a Paper must retain a
visible `未验证` badge. Assignment or later review does not retroactively
change the classification of an immutable historical Release. A subsequent
Release created from Admin-approved human changes is classified as the
`人工核验数据集`.

## Account role management

The existing Admin user page will expose the backend account capabilities that
already exist:

- create Visitor, Reviewer, or Admin accounts;
- change an existing account role;
- enable or disable an account;
- revoke active sessions; and
- reset an account to the server-configured local default password.

Role changes and other critical actions continue to require recent Admin
reauthentication. The backend protection that prevents disabling or demoting
the last enabled Admin remains authoritative. This phase does not introduce
custom teams or organizational groups; for 5-20 users, the three roles and
direct task assignment are sufficient.

## Review task assignment

Add an Admin assignment workspace that uses the existing task create and
reassign APIs. It shows the published Paper library beside enabled Reviewers and
their active workloads. Admins can:

- filter and select one or more Papers;
- assign the selection to one Reviewer with a priority;
- see active task counts per Reviewer;
- reassign an existing active task with optimistic concurrency protection; and
- inspect task state without impersonating the Reviewer.

The first review tasks are created only after the AI-extracted baseline becomes
the current Release. Changesets therefore have a stable `base_release_id`, and
human-verified publications remain normal successor Releases. Bulk assignment
is a sequence of individually audited task creations: one failure does not
silently report the entire batch as successful, and the UI reports per-Paper
results.

## Password policy

Local passwords require at least six characters and no character-class mix.
Any six-character single-class value is valid. Empty and shorter values remain
invalid.

Password changes are voluntary after login. The public login page remains
login-only, while every signed-in role can open the password-change page from
the account area. The legacy `must_change_password` field remains for API and
database compatibility but no longer gates navigation or authorization.

The relaxation does not change the rest of the authentication boundary:

- Argon2id hashes remain the only stored password representation;
- managed account creation and reset use a server-configured default that is
  never returned by APIs or rendered in the browser;
- the existing Admin credential is excluded when the approved one-time bulk
  reset updates existing Reviewer and Visitor accounts;
- login attempt throttling remains enabled;
- session cookies, CSRF protection, session rotation, and session revocation
  remain enabled; and
- critical Admin operations still require recent reauthentication.

Backend validation is authoritative. Browser password inputs also use
`minlength=6` so users receive immediate feedback, but they do not replace
server validation.

The focused behavior and rollout boundary are defined in
`2026-09-13-optional-password-change-default-accounts-design.md`.

## API and data boundaries

Candidate preview endpoints live under the Admin/import namespace and require
the account-management permission. They return presentation-safe snapshots and
never expose source filesystem paths. Existing published endpoints remain
Release-scoped and unchanged for Visitors.

Account mutations continue through `/api/v1/users`. Review task creation and
reassignment continue through `/api/v1/review/tasks`; the frontend adds missing
typed client methods instead of creating duplicate Admin-only APIs.

No schema change is needed for roles, task assignment, or password policy. The
candidate preview will use the explicit import-batch-to-revision association
required to make rejected-candidate re-import safe. That association must be
implemented before the preview can truthfully claim candidate isolation.

## Error handling and audit

- Candidate status changes during preview return a conflict and trigger a
  refresh instead of showing stale approval controls.
- Missing candidate assets are shown as missing metadata; protected source
  paths are never returned.
- Role and password-reset failures preserve the current user row and show the
  request identifier.
- Assignment conflicts identify the affected Paper and leave already-created
  tasks visible.
- Role changes, password resets, task creation, reassignment, candidate
  approval, and publication remain auditable server-side actions.

## Verification

Backend tests cover six-character password acceptance, shorter-password
rejection, Argon2id storage, candidate isolation, pagination and filters,
permission denial, task creation, reassignment, workload counts, and audit
events.

Frontend tests cover the terminology, the 672-Paper candidate preview states,
role and password controls, assignment and reassignment, per-Paper bulk errors,
and Visitor/Reviewer route denial. Type checking and the production build must
pass.

The acceptance smoke sequence is:

```text
Admin login
-> inspect AI-extracted baseline candidate
-> approve and publish AI-extracted baseline
-> create or update Reviewer accounts
-> assign Papers
-> Reviewer submits verified changes
-> Admin approves
-> publish human-verified dataset
```

The old Dashboard remains available as a read-only comparison surface until
this sequence passes against the acceptance database.
