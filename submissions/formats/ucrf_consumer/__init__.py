"""UCRF consumer file: the layout ucrf_consumer_3_74.yaml rendered by the generic TUDF engine (submissions/formats/tudf)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import Engine

from submissions.bureaus import BureauProfile
from submissions.enums import ReportingCycle
from submissions.formats.tudf import engine as tudf
from submissions.formats.tudf.engine import FileStats
from submissions.formats.tudf.layout import Layout, load_layout
from submissions.formats.tudf.parser import ParsedSegment
from submissions.formats.tudf.parser import parse_records as _parse_records
from submissions.formats.tudf.snapshot import Drops, SnapshotData

LAYOUT_FILE = Path(__file__).with_name("ucrf_consumer_3_74.yaml")


def layout() -> Layout:
    return load_layout(LAYOUT_FILE)


@dataclass(frozen=True)
class FormatOptions:
    """Per-build overrides of the layout's encoding (None = as in the layout)."""
    segment_tag_tlv: bool | None = None       # True: "PN03N01"; False: "PNN01"
    record_separator: str | None = None

    def apply(self, base: Layout) -> Layout:
        style = None if self.segment_tag_tlv is None else ("tlv" if self.segment_tag_tlv else "plain")
        return base.with_encoding(segment_tag_style=style, record_separator=self.record_separator)


def header_length() -> int:
    return layout().header_length


def header(bureau: BureauProfile, as_of_date: date, cycle: ReportingCycle | None) -> str:
    """The fixed-width header segment for this bureau and date."""
    empty = SnapshotData({}, {}, {}, {}, [], 0, Drops())
    return tudf.Renderer(layout(), empty, bureau, SimpleNamespace(as_of_date=as_of_date, cycle=cycle)).header()


def build_file(engine: Engine, snapshot_id: int, as_of_date: date, bureau: BureauProfile,
               cycle: ReportingCycle | None = None, options: FormatOptions = FormatOptions()) -> tuple[bytes, FileStats]:
    return tudf.build_file(engine, snapshot_id, as_of_date, bureau, cycle, options.apply(layout()))


def parse_records(body: str, options: FormatOptions = FormatOptions()) -> list[list[ParsedSegment]]:
    return _parse_records(body, options.apply(layout()))


__all__ = ["FileStats", "FormatOptions", "LAYOUT_FILE", "ParsedSegment", "build_file", "header", "header_length",
           "layout", "parse_records"]
