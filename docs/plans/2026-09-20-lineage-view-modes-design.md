# Lineage display modes and semantic-category assessment

User-directed small UI revision: default to a compact numbered node/edge view;
provide an explicit structure-view toggle reusing the existing molecule graph.
Both modes retain Edge navigation and compound lookup. Use mode-specific node
sizes and spacing, fit compact graphs on entry, and retain independent viewports
when toggling modes within the same graph. Structural changes invalidate cached
viewports. Structure image loading is needed only in structure view. Increase wheel
sensitivity from 0.15 to 3 (Cytoscape 3.34 normalizes discrete wheel deltas) and button zoom steps from 1.25 to 1.5.

Verify default mode, actual mode rendering, real wheel zoom, viewport persistence,
Edge clicks/return in both modes, dense layout and unchanged scientific snapshots.

Separately assess SAR versus synthesis categories against existing data/schema.
The user requested an assessment of classification, so propose semantic modeling
and migration guidance without silently assigning or rewriting scientific types.
