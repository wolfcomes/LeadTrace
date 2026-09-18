# LeadTrace Advisor Presentation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Produce a polished 12-slide Chinese PowerPoint and PDF for a 10–12 minute advisor presentation about LeadTrace.

**Architecture:** Build the visual deck as a fixed 16:9 HTML/CSS slide canvas so Chromium can render the exact design to PNG. Package the rendered slides into a standard PowerPoint with one full-slide image per page, and assemble the same PNGs into a PDF. Keep the HTML, CSS, rendering script, and packaging script alongside the final files so wording and layout remain reproducible.

**Tech Stack:** HTML/CSS, Playwright Chromium, Python 3.12, Pillow, python-pptx, ReportLab.

---

### Task 1: Create the slide source and visual system

**Files:**
- Create: `deliverables/leadtrace-advisor-presentation/source/presentation.html`
- Create: `deliverables/leadtrace-advisor-presentation/source/styles.css`

**Step 1: Create the shared 16:9 design system**

Define a 1600×900 slide canvas, navy/slate background, cyan data accents,
medicinal-chemistry orange emphasis, Chinese serif/sans typography, reusable
title, footer, card, metric, diagram-node, and evidence-note styles.

**Step 2: Implement the 12-slide narrative**

Add the approved sequence from the design document. Keep each slide to one
primary assertion and one dominant visual. Use real pilot screenshots on the
scientific-workspace and audit/approval slides.

**Step 3: Audit every quantitative claim**

Cross-check slide wording against:

- `leadtrace/README.md`
- `docs/acceptance/leadtrace-paper-centric-pilot-results.md`
- `docs/plans/2026-09-15-leadtrace-paper-centric-redesign-design.md`
- `leadtrace/backend/pyproject.toml`
- `leadtrace/frontend/package.json`

Expected: pilot claims are explicitly labeled, future capabilities are marked
as future work, and no unsupported productivity or extraction-accuracy claim
appears.

### Task 2: Add reproducible rendering and packaging

**Files:**
- Create: `deliverables/leadtrace-advisor-presentation/source/render.mjs`
- Create: `deliverables/leadtrace-advisor-presentation/source/package_presentation.py`
- Create: `deliverables/leadtrace-advisor-presentation/source/verify_presentation.py`

**Step 1: Write the render script**

Use the repository's installed Playwright Chromium to open the local HTML at a
1600×900 viewport, isolate each `.slide`, and save twelve numbered PNGs under
`deliverables/leadtrace-advisor-presentation/rendered/`.

**Step 2: Run the renderer**

Run:

```bash
node deliverables/leadtrace-advisor-presentation/source/render.mjs
```

Expected: exactly 12 PNG files, each 1600×900.

**Step 3: Write the packaging script**

Use `python-pptx` to create a 13.333×7.5 inch widescreen deck and place each
rendered image edge-to-edge. Use ReportLab to create a matching landscape PDF.

**Step 4: Run the packaging script**

Run:

```bash
python deliverables/leadtrace-advisor-presentation/source/package_presentation.py
```

Expected outputs:

- `deliverables/leadtrace-advisor-presentation/LeadTrace_导师汇报版.pptx`
- `deliverables/leadtrace-advisor-presentation/LeadTrace_导师汇报版.pdf`

### Task 3: Validate structure and visual output

**Files:**
- Create: `deliverables/leadtrace-advisor-presentation/README.md`
- Create: `deliverables/leadtrace-advisor-presentation/preview.png`

**Step 1: Run automated verification**

Run:

```bash
python deliverables/leadtrace-advisor-presentation/source/verify_presentation.py
```

Expected: PASS for 12 HTML slides, 12 PNGs, PNG dimensions, 12 PPTX slides,
12 PDF pages, required title strings, and output file sizes.

**Step 2: Build a contact-sheet preview**

Use Pillow to arrange all twelve PNGs in a 3×4 grid and save `preview.png`.

**Step 3: Inspect the contact sheet and selected full slides**

Check title hierarchy, small-text legibility, image crop quality, color
contrast, alignment, overlap, and slide-to-slide pacing. Revise and rerender if
any slide looks crowded or repetitive.

**Step 4: Write handoff notes**

Document the final files, recommended 10–12 minute pacing, how to regenerate
the deck, and the accuracy boundary between validated pilot results and future
vision.

### Task 4: Final repository checks

**Step 1: Run final verification**

Run:

```bash
python deliverables/leadtrace-advisor-presentation/source/verify_presentation.py
git diff --check
```

Expected: verification PASS and no whitespace errors.

**Step 2: Commit the deliverables**

Run:

```bash
git add docs/plans/2026-09-18-leadtrace-advisor-presentation.md \
  deliverables/leadtrace-advisor-presentation
git commit -m "docs: add LeadTrace advisor presentation"
```
