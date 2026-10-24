"""UCRF consumer pipeline: the standard mapped pipeline with the TUDF consumer file (file.py)."""

from __future__ import annotations

from submissions.pipeline.mapped import MappedPipeline
from submissions.types.consumer.file import build_file


def _write(services, request, snapshot, bureau, created):
    return build_file(services.app_engine, snapshot.snapshot_id, snapshot.as_of_date, bureau,
                      request.reporting_cycle)


PIPELINE = MappedPipeline(_write)
