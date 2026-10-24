"""Validate one canonical snapshot: run every enabled rule, decide each record (cascade), summarise.

Results go to validation_finding, record_outcome and validation_summary. Re-running replaces the previous
results for the snapshot, so a snapshot can be re-validated after a policy change.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from sqlalchemy import Connection, Engine, delete, func, insert, select, text

from submissions.enums import Outcome, RecordOutcome, SnapshotStatus
from submissions.snapshot import SnapshotRepository
from submissions.validation.cascades import CASCADES
from submissions.validation.parameters import load_parameters, render_message
from submissions.validation.python_rules import PYTHON_RULES, RuleContext
from submissions.validation.rules import Cascade, Rule, builtin_pack
from submissions.validation.tables import record_outcome, validation_finding, validation_summary

_INSERT_SQL_FINDINGS = """INSERT INTO validation_finding
    (snapshot_id, rule_id, entity, row_id, account_key, party_key, segment, field, outcome, value, message)
SELECT :snapshot_id, :rule_id, :entity, q.row_id, q.account_key, q.party_key, :segment, :field, :outcome,
       SUBSTR(CAST(q.value AS CHAR), 1, 500), :message
FROM (
{sql}
) q"""


class ValidationError(Exception):
    pass


@dataclass(frozen=True)
class ValidationResult:
    snapshot_id: int
    records: int
    accepted: int
    rejected: int
    file_rejected: bool
    findings: dict[str, int]           # outcome -> count


def _params(snapshot_id: int, as_of_date: date, parameters: dict, submission_type: str) -> dict:
    """Bind values for SQL rules: the snapshot, its type (for ref_code_translation / ref_code_group), dates, and
    the rule parameters (:name)."""
    return {**parameters, "snapshot_id": snapshot_id, "submission_type": submission_type, "as_of_date": as_of_date,
            "one_year_before": as_of_date - timedelta(days=365)}


def _run_sql_rule(conn: Connection, rule: Rule, params: dict) -> None:
    try:
        conn.execute(text(_INSERT_SQL_FINDINGS.format(sql=rule.sql.strip().rstrip(";"))),
                     {**params, "rule_id": rule.rule_id, "entity": rule.entity, "segment": rule.segment,
                      "field": rule.field, "outcome": str(rule.outcome), "message": rule.message[:500]})
    except Exception as exc:
        raise ValidationError(f"Rule {rule.rule_id} failed: {exc}") from exc


def _run_python_rule(conn: Connection, rule: Rule, ctx: RuleContext) -> None:
    rows = [dict(snapshot_id=ctx.snapshot_id, rule_id=rule.rule_id, entity=rule.entity, row_id=f.row_id,
                 account_key=f.account_key, party_key=f.party_key, segment=rule.segment, field=rule.field,
                 outcome=str(rule.outcome), value=None if f.value is None else str(f.value)[:500],
                 message=(f"{rule.message}: {f.detail}" if f.detail else rule.message)[:500])
            for f in PYTHON_RULES[rule.python](ctx)]
    if rows:
        conn.execute(insert(validation_finding), rows)


def _clear(conn: Connection, snapshot_id: int) -> None:
    for t in (validation_finding, validation_summary, record_outcome):
        conn.execute(delete(t).where(t.c.snapshot_id == snapshot_id))


def run_validation(conn: Connection, snapshot_id: int, as_of_date: date, rules: list[Rule],
                   parameters: dict, cascade: Cascade, submission_type: str) -> ValidationResult:
    _clear(conn, snapshot_id)
    rules = [replace(r, message=render_message(r.message, parameters)) for r in rules]   # {parameter} in messages
    params = _params(snapshot_id, as_of_date, parameters, submission_type)
    ctx = RuleContext(conn, snapshot_id, as_of_date, parameters)
    active = [r for r in rules if r.enabled]
    for rule in active:
        if rule.kind == "sql":
            _run_sql_rule(conn, rule, params)
        elif rule.kind == "python":
            _run_python_rule(conn, rule, ctx)
    decide = CASCADES.get(cascade.name)
    if decide is None:
        raise ValidationError(f"Unknown cascade {cascade.name!r} (validation/cascades.py)")
    accepted, rejected = decide(conn, snapshot_id, {r.rule_id: r for r in rules}, parameters, cascade.settings)
    f = validation_finding.c
    conn.execute(insert(validation_summary).from_select(
        ["snapshot_id", "rule_id", "outcome", "finding_count"],
        select(f.snapshot_id, f.rule_id, f.outcome, func.count()).where(f.snapshot_id == snapshot_id)
        .group_by(f.snapshot_id, f.rule_id, f.outcome)))
    s = validation_summary.c
    by_outcome = {o: n for o, n in conn.execute(select(s.outcome, func.sum(s.finding_count)).where(
        s.snapshot_id == snapshot_id).group_by(s.outcome))}
    return ValidationResult(snapshot_id, accepted + rejected, accepted, rejected,
                            bool(by_outcome.get(str(Outcome.REJECT_FILE))), {k: int(v) for k, v in by_outcome.items()})


def snapshot_result(engine: Engine, snapshot_id: int) -> ValidationResult:
    """Read the stored result of an already validated snapshot (used when a snapshot is reused)."""
    s, o = validation_summary.c, record_outcome.c
    with engine.connect() as conn:
        by_outcome = {k: int(v) for k, v in conn.execute(select(s.outcome, func.sum(s.finding_count)).where(
            s.snapshot_id == snapshot_id).group_by(s.outcome))}
        records = dict(conn.execute(select(o.outcome, func.count()).where(o.snapshot_id == snapshot_id)
                                    .group_by(o.outcome)).all())
    accepted, rejected = records.get(str(RecordOutcome.ACCEPTED), 0), records.get(str(RecordOutcome.REJECTED), 0)
    return ValidationResult(snapshot_id, accepted + rejected, accepted, rejected,
                            bool(by_outcome.get(str(Outcome.REJECT_FILE))), by_outcome)


def validate_snapshot(engine: Engine, snapshots: SnapshotRepository, snapshot_id: int,
                      rules: list[Rule], parameters: dict | None = None) -> ValidationResult:
    """Validate an EXTRACTED (or re-validate a VALIDATED) snapshot and mark it VALIDATED.

    `parameters` default to the snapshot tenant's effective rule parameters (pack defaults + overrides).
    """
    snap = snapshots.get(snapshot_id)
    if snap.status not in (SnapshotStatus.EXTRACTED, SnapshotStatus.VALIDATED):
        raise ValidationError(f"Snapshot {snapshot_id} is {snap.status}; only extracted snapshots can be validated")
    if parameters is None:
        parameters = load_parameters(engine, snap.tenant_id, snap.submission_type)
    try:
        with engine.begin() as conn:
            result = run_validation(conn, snapshot_id, snap.as_of_date, rules, parameters,
                                    builtin_pack(snap.submission_type).cascade, str(snap.submission_type))
    except Exception as exc:
        snapshots.mark_failed(snapshot_id, f"validation: {exc}")
        raise
    snapshots.mark_validated(snapshot_id)
    return result
