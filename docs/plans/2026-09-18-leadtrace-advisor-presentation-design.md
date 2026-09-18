# LeadTrace Advisor Presentation Design

**Status:** Approved for implementation

**Date:** 2026-09-18 (Asia/Shanghai)

## Audience and objective

The presentation is designed for an academic advisor. It should make the
project feel ambitious and research-worthy without making claims beyond the
available evidence. In roughly 10–12 minutes, the audience should understand:

1. why medicinal-chemistry knowledge trapped in PDFs is a meaningful research
   and infrastructure problem;
2. how LeadTrace converts papers into structured, evidence-linked lead-
   optimization knowledge;
3. what is technically and methodologically novel about the system;
4. what has already been demonstrated by the 20-paper pilot; and
5. how the platform can support future research in knowledge graphs, data
   curation, model training, and compound design.

## Narrative approach

The deck uses an academic-report structure, strengthened with selected
technical evidence:

- **Problem:** papers preserve conclusions for humans but not reusable decision
  chains for machines.
- **Thesis:** trustworthy scientific AI needs a governed knowledge-production
  loop, not a one-shot extraction model.
- **System:** LeadTrace models Paper, Compound, Structure, Lineage, Edge,
  Evidence, and Activity as a paper-centric scientific graph.
- **Workflow:** AI may prefill untouched workspaces; reviewers verify and edit;
  administrators approve immutable submissions for publication.
- **Trust:** provenance, optimistic concurrency, audit history, immutable
  snapshots, content hashes, permission boundaries, backup, and restore.
- **Evidence:** the isolated 20-paper pilot, complete manual and AI workflows,
  zero integrity violations, 679 backend tests, 87 frontend tests, and a
  five-second restore drill against a one-hour target.
- **Vision:** evolve from paper-level curation into a cross-paper medicinal-
  chemistry knowledge network and a high-quality data foundation for AI.

## Slide sequence

1. Cover — LeadTrace and the central thesis.
2. The hidden bottleneck — valuable medicinal-chemistry decisions remain
   locked in unstructured papers.
3. Reframing the problem — from document reading to governed knowledge
   production.
4. Scientific data model — the evidence-linked lead-optimization graph.
5. End-to-end workflow — source PDF to reviewed, published knowledge.
6. Human–AI collaboration — safe prefill, expert correction, and race safety.
7. Scientific workspace — structures, source evidence, lineage, and activity
   in one context.
8. Trust architecture — traceability and immutable publication.
9. System architecture — web, worker, PostgreSQL, Redis, protected assets, and
   LAN deployment.
10. Pilot results — quantified functional and engineering evidence.
11. Research and platform value — immediate contribution and future research
    directions.
12. Closing — LeadTrace as a prototype scientific knowledge operating system.

## Visual design

- 16:9 widescreen, Chinese-language presentation.
- Dark navy/slate base with cyan for data flow and orange for medicinal-
  chemistry emphasis.
- Large assertion-style titles; minimal body prose; one dominant visual per
  slide.
- Custom diagrams for the knowledge graph, workflow, trust layers, and system
  architecture.
- Real application screenshots are used where legible; otherwise the deck
  uses simplified interface representations rather than decorative stock
  imagery.
- Quantitative claims include concise source notes and distinguish pilot
  evidence from future vision.

## Accuracy boundaries

The deck may describe LeadTrace as a trustworthy scientific-data production
platform, a human-in-the-loop knowledge factory, and an early medicinal-
chemistry knowledge operating system. It must not claim production-scale
deployment, autonomous extraction accuracy, proven drug-discovery cycle-time
reduction, or completed cross-paper reasoning. The pilot is explicitly labeled
as an isolated 20-paper validation, and future capabilities are marked as a
roadmap.

## Deliverables and validation

The deliverables are an editable `.pptx`, its generation source, and a rendered
PDF or slide-preview images when the local toolchain supports them. Validation
includes programmatic PPTX generation, slide rendering, visual inspection for
overflow and hierarchy, and a final claim audit against repository evidence.
