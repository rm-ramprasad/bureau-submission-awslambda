"""Pipelines per submission type and their registry: each type folder with a pipeline.py (`PIPELINE`) is one."""

from __future__ import annotations

import importlib

from submissions.enums import SubmissionType
from submissions.pipeline.base import FileGenerationUnavailable, Services, SubmissionPipeline
from submissions.types import type_definitions


def _discover() -> dict[SubmissionType, SubmissionPipeline]:
    found = {}
    for st, d in type_definitions().items():
        if (d.folder / "pipeline.py").exists():
            found[st] = importlib.import_module(f"submissions.types.{d.folder.name}.pipeline").PIPELINE
    return found


REGISTRY: dict[SubmissionType, SubmissionPipeline] = _discover()


def get_pipeline(submission_type: SubmissionType | str) -> SubmissionPipeline | None:
    return REGISTRY.get(SubmissionType(submission_type))


def enabled_types() -> list[SubmissionType]:
    """Submission types the UI may offer."""
    return list(REGISTRY)


__all__ = ["FileGenerationUnavailable", "REGISTRY", "Services", "SubmissionPipeline", "enabled_types", "get_pipeline"]
