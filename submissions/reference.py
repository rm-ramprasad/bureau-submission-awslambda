"""Reference data: canonical code lists (model.yaml) and each submission type's translations / groups
(types/<type>/codes.yaml), written into ref_code, ref_state_pin, ref_code_translation and ref_code_group.

Runs after the migrations on every deploy (jobs Lambda `migrate`). The database is the master: packaged rows are
only inserted when missing (initial data for a new installation, or codes added in a release); rows edited or added
in the tables are never updated or deleted, so a new file type or an extra code can be entered as records.

Usage:  python -m submissions.reference
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, Engine, Table, select

from submissions.canonical.schema import (
    ref_code, ref_code_group, ref_code_rows, ref_code_translation, ref_state_pin, ref_state_pin_rows,
)
from submissions.types import type_definitions

log = logging.getLogger(__name__)


def translation_rows() -> list[dict]:
    return [dict(submission_type=str(d.submission_type), code_list=list_name, code=value,
                 output_code=t.output_code, is_active=t.active)
            for d in type_definitions().values() for list_name, values in d.translations.items()
            for value, t in values.items()]


def group_rows() -> list[dict]:
    return [dict(submission_type=str(d.submission_type), group_name=name, code=value)
            for d in type_definitions().values() for name, values in d.groups.items() for value in values]


def _insert_missing(conn, table: Table, rows: list[dict]) -> int:
    keys = [c.name for c in table.primary_key.columns]
    existing = {tuple(r) for r in conn.execute(select(*(table.c[k] for k in keys)))}
    missing = [row for row in rows if tuple(row[k] for k in keys) not in existing]
    if missing:
        conn.execute(table.insert(), missing)
    return len(missing)


def seed(engine: Engine) -> dict[str, int]:
    """Insert the packaged reference rows that are missing; table -> rows inserted. Existing rows are left as they
    are: the database is the master, so a value edited there is never overwritten by a deploy."""
    work = [(ref_code, ref_code_rows()), (ref_state_pin, ref_state_pin_rows()),
            (ref_code_translation, translation_rows()), (ref_code_group, group_rows())]
    with engine.begin() as conn:
        return {t.name: _insert_missing(conn, t, rows) for t, rows in work}


def active_translations(conn: Connection, submission_type: str) -> dict[str, dict[str, str]]:
    """What a file writer uses: code list -> canonical value -> file code, active rows only (the same rows the
    generated code rules accept)."""
    t = ref_code_translation.c
    out: dict[str, dict[str, str]] = {}
    for r in conn.execute(select(t.code_list, t.code, t.output_code).where(
            t.submission_type == str(submission_type), t.is_active.is_(True))):
        out.setdefault(r.code_list, {})[r.code] = r.output_code
    return out


def main() -> None:
    from submissions.config import Settings
    from submissions.db import make_engine
    from submissions.logging_config import configure_logging
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    log.info("Reference data: %s", seed(make_engine(settings.database_url)))


if __name__ == "__main__":
    main()
