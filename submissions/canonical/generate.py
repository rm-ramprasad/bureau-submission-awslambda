"""MySQL DDL for the canonical tables, from the same Table objects the code uses: the starting point for a new
migration when model.yaml changes (copy the CREATE / ALTER you need into migrations/NNN_*.sql; applied migrations,
003 included, are never edited). Reference rows are not here: submissions.reference seeds them after migrations.
Schema parity with the migrations is checked by tests/test_migrate.py against MySQL.

Usage:
  python -m submissions.canonical.generate                      # print to stdout
  python -m submissions.canonical.generate --out <file>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import Table
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

from submissions.canonical.schema import (
    ENTITY_TABLES, MODEL, extract_snapshot, ref_code, ref_code_group, ref_code_translation, ref_state_pin,
)

_DIALECT = mysql.dialect()


def _clean(sql) -> str:
    return "\n".join(line.rstrip() for line in str(sql).strip().splitlines())


def _create(table: Table) -> list[str]:
    statements = [_clean(CreateTable(table).compile(dialect=_DIALECT))]
    statements += [_clean(CreateIndex(ix).compile(dialect=_DIALECT))
                   for ix in sorted(table.indexes, key=lambda ix: ix.name)]
    return statements


def generate_sql() -> str:
    tables = [extract_snapshot, ref_code, ref_state_pin, ref_code_translation, ref_code_group, *ENTITY_TABLES.values()]
    statements = [s for t in tables for s in _create(t)]
    header = (
        f"-- GENERATED from submissions/canonical/model.yaml (canonical_version {MODEL.version}).\n"
        "-- Canonical snapshot tables (c_*), snapshot header and reference tables (rows: submissions.reference).\n"
    )
    sql = header + "\n" + "\n\n".join(s + ";" for s in statements) + "\n"
    if any(";" in line[:-1] for line in sql.splitlines()):
        raise ValueError("Generated SQL has a ';' inside a line; the migration runner would mis-split it")
    return sql


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, help="write the DDL to this file")
    args = ap.parse_args(argv)
    sql = generate_sql()
    if args.out:
        args.out.write_text(sql, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(sql)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
