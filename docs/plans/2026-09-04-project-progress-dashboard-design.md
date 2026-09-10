# Project Progress Dashboard Design

## Purpose

Build a local, auditable project dashboard for the 2024 JMC lead-optimization
collection. The dashboard has two equal responsibilities: provide a truthful
project-level progress view and support efficient human review of text paths,
structure crops, and DECIMER proposals while the corpus is still incomplete.

## Product Shape

The first version is a read-only local web application with a separate browser
review ledger. It reads the current pipeline CSV/JSON outputs through a small
Python standard-library server and serves a responsive HTML/CSS/JavaScript
interface. Browser review decisions are stored in localStorage and are clearly
labelled as local notes; they never modify `06_text_confirmed_paths` or any
pipeline source file.

The interface has four views:

- Overview: stage-based progress, workload counts, blockers, and data quality.
- Path queue: searchable, paginated explicit and unresolved path records.
- OCSR review: crop image, source evidence page, proposal SMILES, RDKit status,
  confidence, and local review actions.
- Evidence: an evidence-first table for DOI, page, compound IDs, modification
  language, and cited Figure/Table/Scheme references.

## Data Semantics

The dashboard must keep these quantities separate:

- 672 papers are the corpus and are complete at the text-extraction stage.
- 6,939 rows are extracted evidence statements.
- 5,178 enriched rows are candidate records, not confirmed paths.
- 16 rows are unique explicit directed text paths.
- 4 rows are individual structure crops/proposals, not complete paths.
- 0 rows are final confirmed modification edges.

Progress is shown as stage status and counts rather than one misleading
percentage. Structure progress may show 4 of up to 32 parent/derived structure
slots localized, while path completion remains zero until both compounds and
the modification evidence are confirmed.

## Interaction Design

The overview uses a left navigation rail and a dense work area. A stage map is
the primary visual: Corpus, Text, Evidence, Candidates, Text paths, Structures,
and Confirmed paths. Clicking a stage opens its relevant view or queue.

The path queue supports scope tabs, free-text search, priority and status
filters, pagination, and a selected-record detail panel. The OCSR view supports
proposal selection, crop/source image inspection, copy-to-clipboard for raw or
canonical SMILES, and local review states: pending, inspect, needs
re-localization, and human-checked proposal. The UI never labels a DECIMER
proposal as a confirmed structure.

Incomplete and missing data are first-class states. Empty queues, pending
structures, invalid RDKit results, and stale local review notes are displayed
explicitly rather than hidden behind zero-valued completion percentages.

## Visual Direction

Use a warm paper background with ink-blue navigation, coral actions, teal
progress accents, and amber warnings. Typography should distinguish a compact
operational sans-serif body from a restrained editorial display face. Cards
are reserved for metrics and repeated records; major page sections remain
unframed bands. The layout must remain usable at desktop and narrow mobile
widths.

## Technical Boundary

Create a dependency-free `dashboard/` application at the workspace root:

- `server.py` reads pipeline files, exposes JSON endpoints, and safely serves
  reviewed PNG evidence assets.
- `index.html`, `styles.css`, and `app.js` form the client application.
- `tests/test_dashboard_server.py` verifies counts, stage semantics, filtering,
  and safe asset routing.
- `README.md` documents startup and the read-only/local-ledger boundary.

The server keeps the dashboard usable as new pipeline artifacts replace the
current snapshots. No frontend build step or network dependency is required.
