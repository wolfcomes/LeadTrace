# PDF clarity implementation plan

User approved the proposed display-width/device-pixel-ratio rendering and bounded canvas improvement. Keep existing display geometry and region coordinates, raise default raster resolution to actual CSS width × devicePixelRatio, and retain the zoom control's existing detail scaling. Cap raster area at 8 million pixels and either dimension at 8192 pixels. Resize rerenders only when width or device density changes, coalesced per frame; stale render cancellation stays intact. No server-side PDF transformation or stored-image regeneration.

1. Add failing component tests for 800px display on DPR2, narrow/resized display, capped oversized pages and stale render identity. Use synthetic PDF mocks and browser-generated fixtures only.
2. Add bounded render sizing helper and integrate display measurement, resize observation/window density changes, lifecycle cleanup. Keep CSS layout and normalized overlays unchanged.
3. Run affected tests, typecheck, frontend suite/build, synthetic browser geometry/clarity and built Ketcher CSP checks. Independent code review.
4. Archive this completed plan with hash outside tracked tree. Commit, fast-forward local main, stage immutable frontend release. Validate Caddy config and atomically reload frontend root only; backend/database remain at current deployment. Verify live served asset hashes, CSP, health and record handoff.
