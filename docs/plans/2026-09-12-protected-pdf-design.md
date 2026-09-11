# Protected PDF Access Design

**Status:** Approved for Task 16 implementation

**Goal:** Serve article and supporting-information PDFs only to authorized users while preserving byte-range viewing, integrity checks, safe response headers, and auditable access.

## Architecture

The document layer resolves a Paper's registered PDF Asset through the existing
AssetRepository and LocalAssetStore. The request is authorized before any file
handle is opened: Visitors are denied, Reviewers must be assigned to the Paper,
and Admins may access the document. Only assets with a verified integrity state,
the expected PDF MIME type, and an allowed document category are eligible.

The API exposes `GET /api/v1/papers/{paper_id}/source-pdf` with a single-byte
Range implementation. Full responses return `200`; valid partial responses return
`206`; malformed, multi-range, or unsatisfiable requests return `416` with a
`bytes */size` Content-Range. Every response uses the registered SHA-256 as a
strong ETag and includes private caching, inline disposition, range support,
length, MIME, and `nosniff` headers. Absolute paths and storage keys are never
returned to clients or written to audit details.

In the Nginx deployment, the authorization layer can hand off an already
validated file through an internal transfer location. Native no-Docker mode
uses the same authorization and range service with a bounded FastAPI response,
so local LAN development does not require Nginx to be installed.

## Audit and failure behavior

Successful document reads append a document-view audit event containing actor,
Paper, Asset, request ID, source address, and access type. It records no physical
path. Missing, corrupt, superseded, disallowed, or unassigned assets fail before
file access and do not disclose whether a protected path exists beyond the
appropriate authorization/resource response.

## Verification

Backend tests cover Visitor, unassigned Reviewer, assigned Reviewer, and Admin;
full and partial reads; ETag and security headers; invalid and unsatisfiable
Ranges; missing/corrupt/non-PDF assets; traversal and absolute-path attempts;
and redacted document audit events. Deployment configuration is checked to keep
the internal transfer location non-routable.
