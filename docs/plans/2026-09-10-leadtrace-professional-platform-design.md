# LeadTrace Professional Platform Design

**Date:** 2026-09-10  
**Status:** Approved design baseline  
**Working product name:** LeadTrace（先导寻迹）  
**Scope:** Replace the current local Dashboard with a professional, stable,
versioned review and publication platform while preserving the existing
scientific pipeline and source data.

## 1. Decision Summary

LeadTrace will be a LAN-only web application exposed through one fixed port.
Accounts are created by administrators; there is no self-registration. The
application distinguishes three roles:

- `visitor`: reads only the current published release and approved evidence
  crops;
- `reviewer`: reads assigned full PDFs, creates versioned review drafts, edits
  scientific records and image annotations, and submits changes for approval;
- `admin`: manages users and tasks, reviews changes, publishes releases, rolls
  back published data, and operates imports, files, backups, and audits.

Reviewer changes never update visitor-visible data directly. They enter an
approval workflow. An Admin must approve and publish a changeset before it
becomes the current release.

The selected architecture is a modular monolith:

```text
LAN browser
    |
    v
Nginx on one fixed HTTPS port
    |-- Vue 3 + TypeScript frontend
    |-- FastAPI application
    |-- protected internal file transfer
             |
             |-- PostgreSQL 16
             |-- Redis + Celery worker
             `-- controlled local asset storage
```

The existing extraction and chemistry scripts remain a separate upstream
pipeline. Their CSV/JSON/PDF/PNG outputs are imported as immutable, traceable
source snapshots. They are not allowed to overwrite human review or a
published release.

## 2. Goals and Non-goals

### 2.1 Goals

The first production version must:

1. provide a professional visitor experience for the current corpus and
   compound-optimization lineage data;
2. provide secure LAN authentication and role-based authorization;
3. support 5-20 simultaneous users and 2-5 simultaneous editors;
4. show complete source PDFs only to Reviewers and Admins;
5. make every human change traceable, reviewable, reversible, and attributable;
6. isolate drafts, submitted changes, approved changes, and published data;
7. support non-destructive PDF region editing and molecule-object annotation;
8. support one image for multiple compound labels, multiple semantic objects
   over one image, and multiple images for one object;
9. keep scientific concepts in separate domains: compounds, structures,
   evidence, activities, lineage relations, visual regions, and source files;
10. retain the current scientific quality boundaries and integrity tests;
11. classify and locate every backend file through a controlled asset registry;
12. provide transactional publication, release exports, rollback, audit logs,
    monitoring, backups, and tested recovery;
13. migrate the existing 672-Paper corpus without changing its meaning; and
14. keep the old Dashboard available as a read-only fallback during migration.

### 2.2 Non-goals for the first version

The first version will not include:

- user self-registration;
- public Internet access, OAuth, enterprise SSO, or email password recovery;
- full-PDF access for Visitors;
- Photoshop-style pixel editing;
- a full ChemDraw-style chemical editor;
- real-time collaborative editing of the same field;
- partial approval of a changeset;
- a microservice architecture;
- Elasticsearch;
- mobile PDF-region editing;
- automatic publication of OCSR or RDKit-parseable proposals;
- automatic lineage inference based only on numbering or similarity; or
- physical deletion of business revisions and audit history.

## 3. Existing System and Migration Boundary

The current workspace is not a Git repository. The existing Dashboard uses a
single Python HTTP server and static JavaScript/CSS. Its data comes directly
from CSV, JSON, PDF, and PNG files under:

```text
source_pdfs/分子修改提取_2024_JMC/
```

The current authoritative aggregate, after the 2026-09-10 Batch05/06
source-audit repair, is:

| Metric | Baseline |
|---|---:|
| Corpus Papers | 672 |
| Lineage Papers | 138 |
| Lineages | 193 |
| Compound entities | 4,301 |
| Lineage edges | 4,144 |
| Activity rows | 620 |
| Complete structures | 4,012 |
| `structure_confirmed` | 4,011 |
| Missing/non-unique structures | 289 |
| Pair-ready edges | 1,730 |
| Papers with pair-ready edges | 131 |

This aggregate and the original source files are migration inputs, not mutable
web-application tables. Initial migration will register files in place and
compute hashes. It will not immediately move the approximately 6.3 GB source
tree.

Before implementation begins, production data and tests must be isolated. Test
runs must write only to temporary directories and must be able to prove that
the production-source manifest did not change.

## 4. Architecture

### 4.1 Modular monolith

The new application lives under a new `leadtrace/` directory. The existing
`dashboard/` directory remains unchanged until cutover.

```text
leadtrace/
|-- backend/
|   |-- app/
|   |   |-- security/
|   |   |-- auth/
|   |   |-- users/
|   |   |-- papers/
|   |   |-- assets/
|   |   |-- compounds/
|   |   |-- structures/
|   |   |-- evidence/
|   |   |-- activities/
|   |   |-- lineages/
|   |   |-- visual_objects/
|   |   |-- reviews/
|   |   |-- approvals/
|   |   |-- releases/
|   |   |-- imports/
|   |   |-- audit/
|   |   |-- jobs/
|   |   `-- health/
|   |-- migrations/
|   `-- tests/
|-- frontend/
|-- deploy/
|-- ops/
`-- docs/
```

HTTP routers perform transport validation and call services. Services own
business rules. Repositories own persistence. Permissions are checked in the
backend for every resource; hiding frontend controls is only a usability
measure.

### 4.2 Technology choices

- Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, Alembic, Psycopg 3;
- PostgreSQL 16;
- Vue 3, TypeScript, Vite, Vue Router, Pinia, TanStack Query, Zod;
- PDF.js plus an SVG overlay or Konva for PDF annotations;
- RDKit for structure parsing, canonicalization, and drawing;
- Celery with Redis for rendering, imports, validation, and export jobs;
- Nginx for TLS termination, static frontend delivery, and protected file
  transfer;
- Docker Compose as the supported deployment topology;
- Pytest, Vitest, and Playwright for testing.

The application is deliberately not split into microservices. The selected
topology is easier to deploy and recover while comfortably supporting the
expected concurrency.

## 5. Identity, Authentication, and Authorization

### 5.1 Accounts

Admins create all accounts. Each user has a unique username, display name,
role, enabled state, creation metadata, password-change timestamp, and last
login timestamp. Accounts are disabled rather than deleted so historical audit
records retain their actor.

Passwords are hashed with Argon2id. Initial passwords are one-time credentials,
and first login requires a password change. Admins can reset a password but
cannot retrieve it. The system must prevent removal or disablement of the last
active Admin.

### 5.2 Sessions

Authentication uses server-side sessions. The browser receives only an opaque
session identifier in an `HttpOnly`, `SameSite=Strict` cookie. Sessions rotate
at login, expire after eight hours of inactivity, and have a 24-hour maximum
lifetime. Password changes, user disablement, role changes, and explicit
revocation invalidate affected sessions.

All state-changing requests use CSRF protection. Login attempts are rate
limited. Error messages do not reveal whether a username exists. Passwords,
session IDs, CSRF values, and secrets never enter application or audit logs.

### 5.3 Permission matrix

| Capability | Visitor | Reviewer | Admin |
|---|:---:|:---:|:---:|
| Read current published data | Yes | Yes | Yes |
| Read approved evidence crops | Yes | Yes | Yes |
| Read full source/SI PDFs | No | Assigned scope | Yes |
| Create/edit drafts | No | Assigned scope | Yes |
| Submit changesets | No | Yes | Yes |
| Approve/reject/publish | No | No | Yes |
| Roll back releases | No | No | Yes |
| Manage accounts | No | No | Yes |
| Read full audit log | No | Own activity only | Yes |
| Export unpublished data | No | Assigned scope | Yes |

## 6. Review, Approval, Revision, and Release Model

### 6.1 Changesets

A changeset is the atomic review unit and normally belongs to one Paper. It may
contain coordinated changes to Paper metadata, evidence, regions, molecule
objects, compound bindings, structures, activities, and lineage edges.

Every changeset records a title, reason, owner, Paper, base release, base
revisions, validation results, comments, and approval history.

### 6.2 State machine

```text
draft --> submitted --> approved --> published --> superseded
            |              |
            |              `-- publish failure leaves current release unchanged
            |
            |-- changes_requested --> revised draft --> submitted
            `-- rejected
```

- Drafts are editable and autosaved.
- Submitted content is immutable.
- A request for changes creates a subsequent draft revision; it does not reopen
  and mutate the submitted record.
- Approval and publication remain separate internally, even if the UI offers
  an "approve and publish" action.
- Visitor reads are always resolved through the current published release.

### 6.3 Revisions

Business objects have stable IDs and immutable content revisions. A revision
stores its object, sequence number, predecessor, changeset, author, timestamp,
reason, content hash, searchable fields, and a full JSONB snapshot. Full
snapshots are preferred over patch-only history because the current data scale
is modest and deterministic recovery is more important than storage savings.

Deletion creates a tombstone revision. It never erases prior revisions.

### 6.4 Publication

Long-running render and export work completes before the final publication
transaction. The final transaction locks affected Papers in a stable order,
revalidates base revisions and scientific constraints, registers prepared
assets, creates release items, writes audit events, and changes the single
current-release pointer last. Failure leaves the previous release current.

### 6.5 Rollback

Rollback creates a new changeset and release whose content matches a selected
historical release. It never deletes or rewrites history. A rollback records
the operator, source release, replaced release, reason, object impact, and
before/after hashes.

### 6.6 Concurrency

Draft writes carry an expected version or base revision. A stale update returns
`409 REVISION_CONFLICT`; the application never silently applies last-writer
wins. Rebase uses a three-way comparison between base, Reviewer draft, and
current published content. Region coordinates, SMILES, compound bindings, and
lineage edges require explicit conflict resolution rather than automatic
merging.

## 7. Data Domains

### 7.1 Source and scientific layers

The system preserves four independent layers:

1. immutable original sources;
2. automated extraction and model proposals;
3. human review revisions;
4. Admin-approved published releases.

Automated reruns may update layer 2 through an import batch. They cannot mutate
layers 3 or 4.

### 7.2 Core domains

The first schema includes:

- identity: users, roles, sessions, login attempts;
- sources: Papers, source documents, document pages, external identifiers;
- assets: file identity, hashes, classification, derivation, access, integrity;
- science: compounds, structures, evidence, activities, lineages and edges;
- visual review: regions, molecule objects, bindings and object relations;
- workflow: tasks, changesets, change items, comments and approvals;
- publication: releases, release items and exports;
- operations: import batches, background jobs, audit events and backups.

Important concepts remain separate. A compound may have zero, one, or multiple
structure candidates. A parseable structure is not automatically confirmed. A
visual object relation is not automatically a medicinal-chemistry lineage
relation.

### 7.3 Structure states

The controlled structure state vocabulary is:

```text
proposal
parseable_candidate
source_bound_candidate
structure_confirmed
constitution_confirmed
non_unique_stereochemistry
multicomponent_unresolved
source_structure_mismatch
rejected
```

This explicitly supports racemates, epimer mixtures, multi-component records,
constitution-only representations, and source conflicts without fabricating a
single isomeric structure.

### 7.4 Pair readiness

`pair_ready` is derived, never manually editable. It requires a supported
relation, distinct parent and derived compounds, confirmed complete
single-component structures at both endpoints, exact Paper-local binding, and
no dummy atoms, radicals, or source conflicts. The API returns blocking reasons
when an edge is not eligible.

## 8. File and Asset Model

### 8.1 Asset registry

Large files remain in controlled filesystem storage. PostgreSQL stores an
`asset_id`, internal storage key, SHA-256, MIME type, size, dimensions/page
count, category, source relationship, derivation parameters, access level,
integrity state, and audit metadata.

The frontend receives only asset IDs and protected URLs. It never receives the
server's absolute filesystem paths.

### 8.2 File categories

Categories include:

- original: article PDF, SI PDF/table/archive, external source snapshot;
- PDF-derived: page render and thumbnail;
- evidence: evidence crop;
- model input/output: OCSR input crop and proposal;
- reviewed visual: molecule-object crop;
- confirmed drawing: RDKit structure and molecule-pair panel;
- operational: import manifest, validation report, release export;
- temporary: upload staging and render cache.

Asset integrity states are independent of categories:

```text
registered, verified, quarantined, superseded, missing, corrupt
```

### 8.3 Storage and deduplication

Originals are registered in place during initial migration. Derived data uses
content- or parameter-addressed keys. Identical source hash, page, normalized
bounds, rotation, padding, DPI, and renderer version reuse one crop asset.
Several objects may display the same asset without duplicating the file.

Temporary output is written to staging, hashed, and atomically moved only after
successful generation. Failed work never becomes a valid asset.

## 9. PDF Regions and Molecule Objects

### 9.1 Region geometry

A Region represents geometry on a particular PDF page; it does not assert
chemical meaning. Coordinates are normalized to the PDF page in the range
`0..1`, with rotation and rendering metadata recorded. This keeps annotations
stable at different browser zoom levels and render resolutions.

Reviewers can create, move, resize, duplicate, split, tombstone, and restore
Regions. Rectangles are the primary first-version tool; polygons are optional
and secondary. Editing is non-destructive: original PDFs and crops are never
overwritten.

### 9.2 Molecule objects

A Molecule Object expresses the reviewer's semantic interpretation of visual
content. Controlled types include:

```text
complete_molecule
shared_scaffold
r_group
linker
variable_site
replacement_fragment
multi_structure_region
reaction_or_scheme_context
mixed_chemical_region
non_structure
uncertain
```

Only a confirmed `complete_molecule` can become a final pair endpoint. Other
types remain important reconstruction evidence.

### 9.3 Many-to-many relationships

The model explicitly permits:

```text
one Region --> several Molecule Objects
one Molecule Object --> several Regions/images
one Molecule Object --> several Paper-local Compounds
one Compound --> several Molecule Objects/images
```

This supports adjacent linkers/R-groups, shared scaffold images, one image with
several labels, repeated display of the same crop, and alternate/contextual or
conflicting sources. Compound labels are rows in a binding table, not a comma-
separated string. Prime labels and stereochemical qualifiers remain distinct.

Object relations such as `contains`, `adjacent_to`, `shares_scaffold_with`,
`substituent_of`, `linker_of`, `variable_site_of`, `alternate_view_of`, and
`conflicts_with` do not create lineage edges.

## 10. Pages and User Experience

### 10.1 Route map

```text
/login
/
/papers
/papers/:paperId
/papers/:paperId/lineages/:lineageId
/papers/:paperId/review
/review/tasks
/review/changesets
/review/changesets/:changesetId
/admin/approvals
/admin/files
/admin/imports
/admin/releases
/admin/users
/admin/audit
/admin/system
```

Visitor navigation contains only published-data pages. Reviewer and Admin
navigation contains the review and operational workspaces appropriate to the
role.

### 10.2 Overview and Paper library

The overview reads the current release aggregate, not the legacy 16-path pilot
summary. Corpus, lineage, relation quality, structure quality, pair readiness,
and human review are separate metrics with explicit denominators. No single
ambiguous completion percentage is shown.

The Paper library supports URL-persisted search, pagination, sorting, and
filters for Paper metadata, target, lineage coverage, relation state, structure
state, conflicts, task state, and review state. PostgreSQL indexing and full-
text search are sufficient for the first version.

### 10.3 Visitor Paper page

Visitors see only the published Paper revision, lineage trees, compound and
pair drawings generated from confirmed SMILES, approved activity data, source
text, approved evidence crops, release metadata, and an explicit quality
summary. Unresolved relationships use non-confirmatory visual treatment. A
paper screenshot never substitutes for the final molecule drawing.

### 10.4 Review workspace

The desktop review workspace uses three resizable panels:

```text
navigation and queues | PDF/image canvas | selected-object inspector/history
```

The left panel navigates pages, evidence, Regions, objects, compounds, edges,
issues, and comments. The center uses PDF.js with protected range requests and
annotation overlays. The right panel edits typed properties and shows stable
IDs, published and draft revisions, validation, history, and comments.

Reviewer autosave uses visible `Saving`, `Saved`, `Failed`, and `Conflict`
states. A small browser-local recovery buffer may help after connection loss,
but PostgreSQL is authoritative.

### 10.5 Approval and comparison

Submission has a full summary page grouped by domain. Admin review includes
field diffs, old/new PDF overlays, old/new RDKit drawings, lineage graph diffs,
source files, validation results, and threaded comments. The first version
approves or rejects the complete changeset; it does not partially approve
individual change items.

## 11. API and Background Jobs

All APIs use `/api/v1`. JSON errors have stable codes, human-readable messages,
details safe for the caller, and a request ID. Internal paths, tracebacks, and
database errors never reach the browser.

Key groups are authentication, published Papers, protected assets, tasks,
changesets, draft objects, approvals, releases, imports, users, audits, jobs,
and system health. Critical mutation endpoints support idempotency keys.

PDF rendering, cropping, RDKit parsing/drawing, pair-panel generation, asset
verification, imports, release validation, export generation, indexing, and
backup verification run as background jobs. PostgreSQL holds the authoritative
job state; Redis is only the delivery mechanism. Jobs use input and parameter
hashes for idempotency and can be reconciled after worker or Redis failure.

## 12. Security and File Delivery

Only Nginx's fixed HTTPS port is exposed to the LAN. FastAPI, PostgreSQL, and
Redis bind only internally. Nginx serves frontend assets and uses internal file
transfer after FastAPI authorizes an asset. Full PDFs support byte ranges.

The formal deployment uses an internal CA certificate. Temporary HTTP may be
used during development only. Security controls include CSRF, Content Security
Policy, `nosniff`, parameterized database access, output escaping, upload and
archive limits, external-download allowlists, request-size limits, session
revocation, and reauthentication for critical Admin actions.

Files are treated as untrusted inputs. Uploaded archives are checked for entry
count, depth, uncompressed size, and traversal. Unclassifiable or invalid files
enter quarantine. Secrets come from environment variables or protected secret
files and are never committed.

## 13. Reliability, Backups, and Observability

Published reads remain available when workers are down. Draft text writes may
continue while render work queues. Database failure returns `503` rather than
false empty data. Missing/corrupt assets receive explicit states, block new
publication when necessary, and do not erase textual data.

Backups cover PostgreSQL, original and published assets, release exports,
deployment configuration, and independently controlled encryption keys.
Targets are:

- PostgreSQL backup every four hours;
- backup before every schema migration and release;
- daily asset manifest and incremental file backup;
- weekly full file backup;
- 30-day rolling retention plus long-term release archives;
- storage on a physically separate disk or controlled network location;
- recovery point objective of four hours;
- recovery time objective of four hours;
- monthly isolated restore drill with a retained report.

Application logs are structured JSON and include request IDs, safe actor and
resource identifiers, timing, outcome, and error code. Admin health pages show
database, storage, worker, queue, disk, backup, integrity, schema, application,
and release status. Audit events are append-only and may be chained by hash to
make later alteration detectable.

## 14. Validation and Test Strategy

The test pyramid includes:

- unit tests for labels, coordinates, state machines, permissions, file types,
  diffs, rollback, and pair readiness;
- PostgreSQL integration tests for JSONB, transactions, locks, constraints,
  migrations, and concurrent updates;
- API tests for every role, invalid input, hidden resources, idempotency,
  state conflicts, and audit generation;
- file-security tests for traversal, guessed IDs, range requests, MIME spoofing,
  archive limits, missing/corrupt files, and path non-disclosure;
- chemistry tests preserving all current source, stereochemistry, mixture,
  prime-label, self-loop, duplicate-edge, and pair-readiness boundaries;
- frontend unit tests for permissions, filters, object bindings, region tools,
  autosave, and conflicts;
- Playwright end-to-end tests for Visitor, two Reviewers, and Admin;
- concurrency tests for draft saves, publication, duplicate jobs, and queue
  recovery;
- migration reconciliation tests against the exact current aggregate; and
- backup/restore tests in an isolated environment.

No test may use a production path as an output destination. A production
manifest hash check is part of the test gate.

## 15. Delivery Sequence

Implementation follows these gates:

1. freeze and hash the existing system; isolate tests from production data;
2. establish Git and an isolated development worktree after explicit execution
   approval;
3. scaffold the application, database, deployment, and health checks;
4. implement accounts, sessions, roles, and audit foundations;
5. register source assets without moving or modifying them;
6. import and reconcile the existing aggregate as a baseline release;
7. deliver professional Visitor read-only pages;
8. deliver a minimal metadata/evidence changeset-to-release workflow;
9. deliver protected PDF viewing and Region editing;
10. deliver molecule-object and many-to-many image/compound bindings;
11. deliver structure, evidence, activity, and lineage editors with RDKit;
12. complete approval, release, export, rollback, and Admin operations;
13. complete backups, recovery drills, security, concurrency, and performance
    acceptance; and
14. run old/new systems in parallel, reconcile, then cut over with a documented
    fallback.

## 16. Acceptance Criteria

The new platform is ready to replace the old Dashboard only when:

- all 672 Papers and baseline aggregate counts reconcile exactly;
- Visitors cannot obtain full PDFs, drafts, or hidden assets;
- Reviewers can view assigned PDFs and create non-destructive annotations;
- one image can support multiple objects and compound labels without file
  duplication;
- Reviewers can edit typed scientific records and submit immutable changesets;
- Admins can request changes, reject, approve, publish, and roll back;
- drafts do not affect Visitor views before publication;
- every significant operation is attributable and auditable;
- concurrent editing cannot silently overwrite data;
- publication is atomic and idempotent;
- existing scientific integrity rules remain intact;
- database and file backups have passed an actual restore drill;
- the supported LAN deployment uses HTTPS on one fixed port; and
- the old Dashboard remains available as a read-only fallback through the
  stabilization period.

## 17. Approved Decisions

The following decisions were explicitly confirmed during design review:

1. deployment is LAN-only through a port;
2. accounts are Admin-created and self-registration is disabled;
3. Reviewer changes require Admin approval before publication;
4. Visitors see published data and evidence crops, but not complete PDFs;
5. the concurrency target is 5-20 online users and 2-5 concurrent editors;
6. PostgreSQL is the system of record for accounts, review, revision,
   publication, and audit data;
7. the selected architecture is the FastAPI/PostgreSQL/Vue modular monolith;
8. structure-image editing is non-destructive Region/object annotation;
9. the first version supports image reuse and many-to-many image/object/label
   relationships; and
10. the first version edits SMILES and redraws with RDKit but does not provide a
    full chemical drawing editor.
