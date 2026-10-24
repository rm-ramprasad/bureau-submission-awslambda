"""Commercial (phase 3): the CUCRF rule pack and the facility x borrower record decision, against the mock LMS
scenarios (mock_data/commercial.py: expected outcome and expected rule per facility)."""

from collections import defaultdict
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from mock_data.commercial import rows as commercial_rows
from submissions.adapters.extract import run_extract
from submissions.adapters.mapping import load_mapping, mapping_file
from submissions.snapshot import SnapshotRepository
from submissions.validation.engine import validate_snapshot
from submissions.validation.python_rules import PYTHON_RULES
from submissions.validation.rules import builtin_pack, load_rule_set, set_policy
from submissions.validation.tables import record_outcome, validation_finding

ROOT = Path(__file__).resolve().parent.parent
AS_OF = date(2026, 9, 30)


def _validate(engine, lms_engine, tenant_repo, tenant_id="nbfc_001"):
    tenant, snapshots = tenant_repo.get(tenant_id), SnapshotRepository(engine)
    sid = run_extract(tenant=tenant, mapping=load_mapping(mapping_file(ROOT, tenant.mapping_path, "COMMERCIAL")),
                      submission_type="COMMERCIAL", as_of_date=AS_OF, app_engine=engine, source_engine=lms_engine,
                      snapshots=snapshots, owner="t").snapshot_id
    result = validate_snapshot(engine, snapshots, sid, load_rule_set(engine, tenant_id, "COMMERCIAL"))
    with engine.connect() as conn:
        o, f = record_outcome.c, validation_finding.c
        outcomes = {r.account_key: (r.outcome, r.reason_rule_id) for r in conn.execute(
            select(o.account_key, o.outcome, o.reason_rule_id).where(o.snapshot_id == sid))}
        findings = defaultdict(set)
        for r in conn.execute(select(f.rule_id, f.account_key, f.party_key, f.outcome).where(f.snapshot_id == sid)):
            findings[r.account_key or r.party_key].add((r.rule_id, r.outcome))
    return result, outcomes, findings


def test_pack_loads_with_its_own_prefix_and_cascade():
    pack = builtin_pack("COMMERCIAL")
    assert pack.prefix == "CUCRF." and pack.cascade.name == "facility_borrower_minimums"
    assert all(r.rule_id.startswith("CUCRF.") for r in pack.rules)
    assert all(r.python in PYTHON_RULES for r in pack.rules if r.python)
    ids = {r.rule_id for r in pack.rules}
    assert {"CUCRF.REQUIRED.party.legal_constitution", "CUCRF.ENUM.account.account_type",
            "CUCRF.REC.NO_RELATIONSHIP"} <= ids
    assert not ids & {r.rule_id for r in builtin_pack("CONSUMER").rules}


@pytest.mark.parametrize("tenant_id,tenant_no", [("nbfc_001", 1), ("nbfc_002", 2)])
def test_mock_scenarios_get_their_expected_outcome(engine, lms_engine, tenant_repo, tenant_id, tenant_no):
    _, outcomes, findings = _validate(engine, lms_engine, tenant_repo, tenant_id)
    borrowers = {f["facility_id"]: f["customer_id"] for f in commercial_rows(tenant_no)["business_facility"]}
    problems = []
    for f in commercial_rows(tenant_no)["business_facility"]:
        fid, expected, rule = f["facility_id"], f["test_expected"], f["test_rule_reference"]
        outcome, reason = outcomes[fid]
        want = "REJECTED" if expected == "REJECT_RECORD" else "ACCEPTED"
        if outcome != want:
            problems.append(f"scenario {f['test_scenario_number']} {fid}: {outcome} ({reason}), expected {want}")
        fired = {r for r, _ in findings[fid] | findings[borrowers[fid]]}
        if rule and rule not in fired:
            problems.append(f"scenario {f['test_scenario_number']} {fid}: {rule} did not fire ({sorted(fired)})")
    assert not problems, "\n".join(problems)


def test_clean_scenarios_have_no_rejections(engine, lms_engine, tenant_repo):
    """Positive scenarios: no REJECT_* finding at all, only warnings or the spec's expected handling."""
    _, _, findings = _validate(engine, lms_engine, tenant_repo)
    expected_rules = {r.rule_id for r in builtin_pack("COMMERCIAL").rules if r.expected}
    clean = [f for f in commercial_rows(1)["business_facility"] if not f["test_rule_reference"]]
    hits = {f["facility_id"]: sorted((r, o) for r, o in findings[f["facility_id"]] | findings[f["customer_id"]]
                                     if o.startswith("REJECT") and r not in expected_rules) for f in clean}
    assert not {k: v for k, v in hits.items() if v}


def test_relationship_is_optional_for_factoring_without_recourse(engine, lms_engine, tenant_repo):
    _, outcomes, findings = _validate(engine, lms_engine, tenant_repo)
    factoring = next(f for f in commercial_rows(1)["business_facility"] if f["product"] == "FACT_NR")
    assert outcomes[factoring["facility_id"]] == ("ACCEPTED", None)
    assert "CUCRF.REC.NO_RELATIONSHIP" not in {r for r, _ in findings[factoring["facility_id"]]}


def test_policy_can_soften_a_cascade_rule(engine, lms_engine, tenant_repo):
    set_policy(engine, "nbfc_001", "CUCRF.REC.NO_IDENTIFIER", outcome="WARN")
    _, outcomes, _ = _validate(engine, lms_engine, tenant_repo)
    no_ids = next(f for f in commercial_rows(1)["business_facility"] if f["test_scenario_number"] == 14)
    assert outcomes[no_ids["facility_id"]] == ("ACCEPTED", None)
