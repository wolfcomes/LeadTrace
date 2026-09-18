# LeadTrace Five-Slide Advisor Presentation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the existing 12-slide LeadTrace advisor deck with a five-slide version containing original slides 1, 3, 5, 6, and 7, and show the verified 1,209-paper source corpus on the cover.

**Architecture:** Keep the current HTML/CSS → Playwright PNG → PPTX/PDF pipeline. Remove unselected slide sections from the HTML, make renderer and verifier slide counts dynamic or explicitly five, and regenerate every derived artifact with the existing source/render/package hash contract.

**Tech Stack:** HTML/CSS, Playwright Chromium, Python 3.12, Pillow, python-pptx, ReportLab, PyMuPDF.

---

### Task 1: Change verification to the approved five-slide contract

**Files:**
- Modify: `deliverables/leadtrace-advisor-presentation/source/verify_presentation.py`

**Step 1: Change expected slide count and required titles**

Require exactly five slides and require the retained slide titles plus a cover
text check for `1209 篇`. Remove required titles belonging to deleted slides.

**Step 2: Run the verifier against the old deck**

Run:

```bash
python deliverables/leadtrace-advisor-presentation/source/verify_presentation.py
```

Expected: FAIL because the old source still contains 12 slides.

### Task 2: Reduce the presentation source to five slides

**Files:**
- Modify: `deliverables/leadtrace-advisor-presentation/source/presentation.html`
- Modify: `deliverables/leadtrace-advisor-presentation/source/styles.css`
- Modify: `deliverables/leadtrace-advisor-presentation/source/render.mjs`

**Step 1: Keep only original slides 1, 3, 5, 6, and 7**

Delete the seven unselected `<section class="slide">` elements. Preserve the
selected content and visual components.

**Step 2: Update the cover count and scope labels**

Replace the 20-paper cover metric with `1209 篇` and label it `当前原始论文语料`.
Label integrity and automated-test metrics as pilot evidence so they are not
mistaken for 1,209-paper processing results.

**Step 3: Renumber the retained slides**

Update section numbers and footers to `01 / 05` through `05 / 05`.

**Step 4: Update rendering count**

Make `render.mjs` require five source slides and emit exactly `01.png` through
`05.png`, deleting stale rendered PNGs from the previous 12-slide version.

### Task 3: Rewrite the handoff documents for the short deck

**Files:**
- Modify: `deliverables/leadtrace-advisor-presentation/README.md`
- Modify: `deliverables/leadtrace-advisor-presentation/SPEAKER_NOTES.md`

**Step 1: Rewrite README scope and pacing**

Describe a five-slide, roughly five-minute advisor briefing. Document the
1,209-paper counting rule and distinguish the current source corpus from the
20-paper isolated pilot.

**Step 2: Rewrite speaking notes**

Keep exactly five sections corresponding to the retained slides. Preserve
transitions and evidence boundaries.

### Task 4: Regenerate and visually validate all artifacts

**Files:**
- Regenerate: `deliverables/leadtrace-advisor-presentation/rendered/*.png`
- Regenerate: `deliverables/leadtrace-advisor-presentation/rendered/manifest.json`
- Regenerate: `deliverables/leadtrace-advisor-presentation/LeadTrace_导师汇报版.pptx`
- Regenerate: `deliverables/leadtrace-advisor-presentation/LeadTrace_导师汇报版.pdf`
- Regenerate: `deliverables/leadtrace-advisor-presentation/preview.png`

**Step 1: Render and package**

Run:

```bash
node deliverables/leadtrace-advisor-presentation/source/render.mjs
python deliverables/leadtrace-advisor-presentation/source/package_presentation.py
```

Expected: exactly five PNGs, a five-slide PPTX, and a five-page PDF.

**Step 2: Run automated verification**

Run:

```bash
python deliverables/leadtrace-advisor-presentation/source/verify_presentation.py
```

Expected: PASS for five HTML slides, five 1600×900 PNGs, source hashes, PPTX
embedded images, PDF embedded images, required titles, and the cover count.

**Step 3: Inspect all five slides**

View the contact sheet and each full-resolution slide. Confirm the source count,
continuous page numbers, title wraps, screenshot crop, non-overlap, and visual
pacing.

**Step 4: Run repository checks**

Run:

```bash
unzip -t deliverables/leadtrace-advisor-presentation/LeadTrace_导师汇报版.pptx
git diff --check
```

Expected: valid PPTX archive and no whitespace errors.

**Step 5: Commit**

```bash
git add deliverables/leadtrace-advisor-presentation
git commit -m "docs: condense LeadTrace advisor presentation"
```
