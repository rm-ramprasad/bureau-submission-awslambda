"""Commercial UCRF file: the layout types/commercial/layout.yaml rendered by the generic delimited engine
(submissions/formats/delimited)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Engine

from submissions.bureaus import BureauProfile
from submissions.enums import ReportingCycle, SubmissionType
from submissions.formats.delimited import engine as delimited
from submissions.formats.delimited.layout import Layout, load_layout
from submissions.formats.tudf.engine import FileStats
from submissions.reference import snapshot_translations
from submissions.types import type_definition

LAYOUT_FILE = type_definition(SubmissionType.COMMERCIAL).path("layout.yaml")


def layout() -> Layout:
    return load_layout(LAYOUT_FILE)


def build_file(engine: Engine, snapshot_id: int, as_of_date: date, bureau: BureauProfile,
               cycle: ReportingCycle | None, created_date: date) -> tuple[bytes, FileStats]:
    """The file for one bureau. `created_date` is HD field 4 (date of creation), never before the as-of date."""
    with engine.connect() as conn:
        translations = snapshot_translations(conn, snapshot_id)      # as validated
    return delimited.build_file(engine, snapshot_id, as_of_date, bureau, cycle, layout(), translations,
                                max(created_date, as_of_date))


__all__ = ["FileStats", "LAYOUT_FILE", "build_file", "layout"]
