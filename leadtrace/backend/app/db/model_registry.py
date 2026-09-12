from __future__ import annotations

import importlib


_MODEL_MODULES = (
    "app.activities.models",
    "app.approvals.models",
    "app.assets.models",
    "app.audit.models",
    "app.auth.models",
    "app.compounds.models",
    "app.evidence.models",
    "app.imports.models",
    "app.jobs.models",
    "app.lineages.models",
    "app.maintenance.models",
    "app.papers.models",
    "app.releases.models",
    "app.reviews.comments",
    "app.reviews.models",
    "app.revisions.models",
    "app.structures.models",
    "app.users.models",
    "app.visual_objects.models",
)


def load_model_registry() -> None:
    """Load every mapped table before isolated workers perform ORM flushes."""

    for module_name in _MODEL_MODULES:
        importlib.import_module(module_name)


__all__ = ["load_model_registry"]
