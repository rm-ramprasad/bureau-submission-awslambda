"""Read a validated canonical snapshot for formatting: rows, accepted records, and the validation drops.

Only ACCEPTED records (record_outcome) are written. Validation findings decide what is left out: REJECT_FIELD drops
that field, REJECT_SEGMENT drops that segment instance. The formatter makes no rule decisions of its own.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import Connection, select

from submissions.canonical.schema import ENTITY_TABLES
from submissions.enums import Outcome, RecordOutcome
from submissions.formats.tudf.layout import Layout
from submissions.validation.tables import record_outcome, validation_finding


@dataclass
class Drops:
    """Field and segment drops from validation findings, with their account restriction (None = all records)."""
    fields: dict[tuple[str, int, str], list[str | None]] = field(default_factory=lambda: defaultdict(list))
    segments: dict[tuple[str, int], list[str | None]] = field(default_factory=lambda: defaultdict(list))

    def field_dropped(self, entity: str, row_id: int, column: str, account_key: str) -> bool:
        return any(a is None or a == account_key for a in self.fields.get((entity, row_id, column), []))

    def segment_dropped(self, entity: str, row_id: int, account_key: str) -> bool:
        return any(a is None or a == account_key for a in self.segments.get((entity, row_id), []))


@dataclass
class SnapshotData:
    parties: dict[str, object]
    accounts: dict[str, object]
    holders: dict[tuple[str, str], object]
    children: dict[str, dict[str, list]]          # entity -> party_key / account_key -> rows (in row_id order)
    accepted: list[tuple[str, str]]               # (account_key, party_key), one record each
    rejected: int
    drops: Drops


def load_snapshot(conn: Connection, snapshot_id: int, layout: Layout) -> SnapshotData:
    def rows(entity):
        t = ENTITY_TABLES[entity]
        return conn.execute(select(t).where(t.c.snapshot_id == snapshot_id).order_by(t.c.row_id)).all()

    children = {}
    for seg in layout.segments:
        if seg.rows and seg.rows not in children:
            grouped = defaultdict(list)
            for r in rows(seg.rows):
                grouped[getattr(r, seg.by)].append(r)
            children[seg.rows] = grouped

    drops = Drops()
    f = validation_finding.c
    for x in conn.execute(select(f.entity, f.row_id, f.field, f.account_key, f.outcome).where(
            f.snapshot_id == snapshot_id, f.outcome.in_([str(Outcome.REJECT_FIELD), str(Outcome.REJECT_SEGMENT)]),
            f.row_id.is_not(None))):
        if x.outcome == Outcome.REJECT_FIELD and x.field:
            drops.fields[(x.entity, x.row_id, x.field)].append(x.account_key)
        elif x.outcome == Outcome.REJECT_SEGMENT:
            drops.segments[(x.entity, x.row_id)].append(x.account_key)

    o = record_outcome.c
    outcomes = conn.execute(select(o.account_key, o.party_key, o.outcome).where(o.snapshot_id == snapshot_id)
                            .order_by(o.account_key, o.party_key)).all()
    return SnapshotData(
        parties={r.party_key: r for r in rows("party")},
        accounts={r.account_key: r for r in rows("account")},
        holders={(r.account_key, r.party_key): r for r in rows("account_holder")},
        children=children,
        accepted=[(x.account_key, x.party_key) for x in outcomes if x.outcome == RecordOutcome.ACCEPTED],
        rejected=sum(1 for x in outcomes if x.outcome == RecordOutcome.REJECTED),
        drops=drops,
    )
