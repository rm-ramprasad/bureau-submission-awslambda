"""Golden files: the generated UCRF consumer files must stay byte-identical for the mock snapshots.

Any change to the layout or the engine that alters a byte fails here. If a change is intended (a spec change), review
the diff, then regenerate:  $env:REGENERATE_GOLDEN = "1"; python -m pytest tests/test_ucrf_golden.py
"""

import os
from datetime import date
from pathlib import Path

import pytest

from submissions.adapters.extract import run_extract
from submissions.adapters.mapping import load_mapping
from submissions.bureaus.seed import seed as seed_bureaus
from submissions.enums import BureauCode, ReportingCycle
from submissions.types.consumer.file import FormatOptions, build_file
from submissions.snapshot import SnapshotRepository
from submissions.validation.engine import validate_snapshot
from submissions.validation.rules import load_rule_set

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = Path(__file__).with_name("golden")
AS_OF = date(2026, 9, 30)
REGENERATE = os.environ.get("REGENERATE_GOLDEN") == "1"


@pytest.fixture
def snapshot(engine, lms_engine, tenant_repo, bureau_repo):
    seed_bureaus(bureau_repo, ["nbfc_001", "nbfc_002"])

    def make(tenant_id):
        snapshots = SnapshotRepository(engine)
        sid = run_extract(tenant=tenant_repo.get(tenant_id), mapping=load_mapping(ROOT / "clients" / tenant_id / "consumer.yaml"),
                          submission_type="CONSUMER", as_of_date=AS_OF, app_engine=engine, source_engine=lms_engine,
                          snapshots=snapshots, owner="golden").snapshot_id
        validate_snapshot(engine, snapshots, sid, load_rule_set(engine, tenant_id, "CONSUMER"))
        add_history(engine, sid)
        return sid
    return make


def add_history(engine, snapshot_id: int) -> None:
    """The mock LMS has no account history (it comes from a one-time historical load), so add some for TH coverage:
    a card account (credit/cash limits, credit balance) and a loan with 50 months (capped at 47), DPD above the cap,
    asset class instead of DPD, unknown asset class, zero payment."""
    from decimal import Decimal
    from sqlalchemy import select
    from submissions.canonical.schema import ENTITY_TABLES
    account, history = ENTITY_TABLES["account"], ENTITY_TABLES["account_history"]
    with engine.begin() as conn:
        rows = conn.execute(select(account.c.account_key, account.c.account_type)
                            .where(account.c.snapshot_id == snapshot_id).order_by(account.c.account_key)).all()
        card = next(r.account_key for r in rows if r.account_type == "CREDIT_CARD")
        loan = next(r.account_key for r in rows if r.account_type != "CREDIT_CARD")
        values = []
        for i in range(50):                                          # loan: 50 months back from September 2026
            year, mon = divmod(8 - i, 12)
            month = date(2026 + year, mon + 1, 15)
            values.append(dict(snapshot_id=snapshot_id, account_key=loan, history_month=month,
                               days_past_due=[None, 1200, 30, None][i % 4],       # none / above the cap / normal
                               asset_classification=["UNKNOWN", None, None, "SUBSTANDARD"][i % 4],   # unknown / - / - / SUB

                               amount_overdue=Decimal("1500.50") if i % 2 else None,
                               high_credit_amount=Decimal("500000"), current_balance=Decimal(400000 - i * 1000),
                               date_last_payment=month.replace(day=5) if i % 3 else None,
                               actual_payment_amount=[Decimal("12500.40"), Decimal("0"), None][i % 3]))
        for i in range(3):                                           # card: limits and a credit balance
            values.append(dict(snapshot_id=snapshot_id, account_key=card, history_month=date(2026, 9 - i, 28),
                               days_past_due=0, asset_classification=None, amount_overdue=None,
                               high_credit_amount=Decimal("80000"), credit_limit=Decimal("100000"),
                               cash_limit=Decimal("20000") if i else None,
                               current_balance=Decimal("-2450.50") if i == 1 else Decimal("15000"),
                               date_last_payment=None, actual_payment_amount=Decimal("5000")))
        conn.execute(history.insert(), values)


def check(name: str, content: bytes) -> None:
    path = GOLDEN / name
    if REGENERATE:
        GOLDEN.mkdir(exist_ok=True)
        path.write_bytes(content)
    assert path.exists(), f"missing golden file {name}: run with REGENERATE_GOLDEN=1"
    expected = path.read_bytes()
    if content != expected:
        at = next((i for i, (a, b) in enumerate(zip(content, expected)) if a != b), min(len(content), len(expected)))
        pytest.fail(f"{name} differs at byte {at}: got {content[max(0, at - 30):at + 30]!r}, "
                    f"expected {expected[max(0, at - 30):at + 30]!r} (lengths {len(content)} / {len(expected)})")


@pytest.mark.parametrize("tenant_id", ["nbfc_001", "nbfc_002"])
def test_files_match_golden(engine, bureau_repo, snapshot, tenant_id):
    sid = snapshot(tenant_id)
    for bureau in BureauCode:
        content, _ = build_file(engine, sid, AS_OF, bureau_repo.get(tenant_id, bureau, "CONSUMER"),
                               ReportingCycle.MONTH_END)
        check(f"{tenant_id}_{bureau.value.lower()}.txt", content)


def test_alternative_encoding_matches_golden(engine, bureau_repo, snapshot):
    sid = snapshot("nbfc_001")
    content, _ = build_file(engine, sid, AS_OF, bureau_repo.get("nbfc_001", "CIBIL", "CONSUMER"), None,
                            FormatOptions(segment_tag_tlv=True, record_separator="\n"))
    check("nbfc_001_cibil_tlv_newline.txt", content)
