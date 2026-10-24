"""Pipelines per submission type and their registry: each type folder with a pipeline.py (`PIPELINE`) is one."""

from __future__ import annotations

import importlib
from pathlib import Path

from submissions.adapters.mapping import mapping_file
from submissions.enums import SubmissionType
from submissions.pipeline.base import FileGenerationUnavailable, Services, SubmissionPipeline
from submissions.tenants import Tenant
from submissions.types import type_definitions

CODE_ROOT = Path(__file__).resolve().parent.parent.parent      # clients/ is packaged next to submissions/


def _discover() -> dict[SubmissionType, SubmissionPipeline]:
    found, defs = {}, type_definitions()
    for st in SubmissionType:                               # enum order: consumer first in lists and schedules
        d = defs.get(st)
        if d and (d.folder / "pipeline.py").exists():
            found[st] = importlib.import_module(f"submissions.types.{d.folder.name}.pipeline").PIPELINE
    return found


REGISTRY: dict[SubmissionType, SubmissionPipeline] = _discover()


def get_pipeline(submission_type: SubmissionType | str) -> SubmissionPipeline | None:
    return REGISTRY.get(SubmissionType(submission_type))


def enabled_types() -> list[SubmissionType]:
    """Submission types the product supports (a pipeline exists)."""
    return list(REGISTRY)


def available_types(tenant: Tenant, base_dir: Path = CODE_ROOT) -> list[SubmissionType]:
    """Types one NBFC can run: a pipeline exists and the NBFC has a mapping for it (clients/<tenant>/<type>.yaml).
    An NBFC without a commercial portfolio simply has no commercial.yaml."""
    if not tenant.mapping_path:
        return []
    return [t for t in REGISTRY if mapping_file(base_dir, tenant.mapping_path, t).exists()]


__all__ = ["CODE_ROOT", "FileGenerationUnavailable", "REGISTRY", "Services", "SubmissionPipeline", "available_types",
           "enabled_types", "get_pipeline"]
