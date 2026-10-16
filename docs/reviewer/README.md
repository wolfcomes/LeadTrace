# Reviewer handbook

Open the illustrated handbook in a browser:

- [中文 HTML](../../leadtrace/frontend/public/reviewer-guide/zh.html)
- [English HTML](../../leadtrace/frontend/public/reviewer-guide/en.html)
- Text copies: [中文 Markdown](reviewer-guide.zh.md), [English Markdown](reviewer-guide.en.md).

When the frontend is built, the same files are served at `/reviewer-guide/zh.html`
and `/reviewer-guide/en.html`. The workbench's Reviewer help links to the selected
language in a new tab. The HTML requires no login or external scripts and is
usable offline: copy the entire `public/reviewer-guide/` directory, including
`guide.css`, `fonts.css`, `fonts/` and `images/`. Use the browser print command to print/save as PDF.

## Maintaining a single guide

Edit `leadtrace/frontend/src/review/help/reviewer-guide.json`. Each section has a
stable semantic `id`, bilingual summaries for in-app help, and structured blocks
for the full handbook. Never bind field examples to array indices. Supported
blocks are paragraph, note, steps, table, example, flow, question and figure.
All source text is HTML-escaped by the renderer; do not put raw HTML in the JSON.

```bash
python leadtrace/ops/reviewer/render_guide.py
python leadtrace/ops/reviewer/render_guide.py --check
```

The renderer also copies the required unmodified Noto Sans SC font shards and
their SIL Open Font License from the frontend dependency. Install frontend
dependencies before regeneration/checking. Bundled fonts make Chinese text
portable on systems without Chinese fonts.

Generated HTML/Markdown are checked in for offline access. Styling lives in
`leadtrace/frontend/public/reviewer-guide/guide.css`.

## Screenshot provenance

Screenshots show real Vue workbench components supplied with explicitly fictional
teaching records through Playwright request interception. They contain no
source-paper crops, real scientific records, credentials or database exports.
The capture script handles all `/api/` calls locally and requires loopback Vite;
it never talks to Preview or production. Nothing is saved to a database.

With frontend dependencies installed:

```bash
cd leadtrace/frontend
npm run dev -- --host 127.0.0.1 --port 5186 --strictPort
```

In another terminal, from the repository root:

```bash
node leadtrace/ops/reviewer/capture_guide.mjs
python leadtrace/ops/reviewer/render_guide.py --check
```

Captures temporarily make sticky headers static so they cannot obscure a
full-height section; form/graph content and controls are unchanged.

Each language has overview, Compound, Activity, Lineage, Add Node, Edge and
submission screenshots. Image captions explain the task and fictional status;
images link to their full-resolution files. Update captures when the relevant UI
changes. Screenshot generation is a documentation tool, not scientific approval.

## Fictional Lineage construction cases

The handbook also includes five graph-construction cases (seven graphs per
language): parallel analogues, successive batches connected by a hub, independent
branches sharing a baseline, a short chain, and supported convergence. All labels,
relationships and review states are fictional teaching assumptions.

With the local frontend running on port 5186, capture these separately:

```bash
node leadtrace/ops/reviewer/capture_lineage_examples.mjs
python leadtrace/ops/reviewer/render_guide.py
python leadtrace/ops/reviewer/render_guide.py --check
```

The script permits only the specified loopback frontend origin, intercepts every
API request, rejects unhandled requests, and checks displayed node/edge counts,
endpoints and hub labels before capture. It uses the real point-graph component
and deterministic saved positions at 2× pixel density. For portable canvas text
on hosts without system Chinese fonts, capture explicitly uses the app’s bundled
Noto Sans SC font; sticky headers are temporarily made static to avoid obscuring
the captured panel. Scientific data, topology and geometry are unchanged. It saves
`lineage-examples-manifest.json` separately from the introductory screenshots.
No original paper content, credentials or database writes are involved.
