# Molecular Lineage graph and contextual Edge details

Implement the user's requested structure depictions inside Cytoscape and in-page
Edge selection in the existing worktree/preview. Scientific records stay intact.

Use protected RDKit depiction endpoints, fixed large molecule-card nodes, force
layout with spacing (concentric for single-baseline stars), pan/zoom, fit overview, readable-scale reset, compound locator,
and canvas expansion. Missing depictions retain labelled fallback nodes. Graph
viewport persists across overview/detail navigation. On large graphs, default zoom
is bounded at a readable scale; full overview is an explicit control.

Edge tap switches the main pane to parent/child compound cards, structure status,
compound links, relation/summary/status and Evidence. Reuse existing editors and
permission/version handling. Keep selected entity in URL with browser history,
and accessible Edge buttons. A narrow side inspector was considered but cannot
comfortably accommodate two structures and evidence in the current main column.

Sequence: failing navigation/fallback tests; cached structure reads and graph;
endpoint cards and contextual navigation; existing frontend tests/typecheck/build;
real browser canvas taps, layout/image checks, history and snapshot preservation.
