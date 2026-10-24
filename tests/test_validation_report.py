from pathlib import Path

import pytest
import yaml

from submissions.types import type_definition
from submissions.validation import results
from submissions.validation.results import report
from submissions.validation.rules import RuleDefinitionError, builtin_rules, load_pack, load_pack_file, report_hints
from tests.test_validation_engine import extract, outcomes, validate

HINTS = report_hints("CONSUMER")


@pytest.mark.parametrize("rule_id, expected", [
    ("UCRF.PN.NAME_DIGITS", "PERSONAL"), ("UCRF.ID.NUMBER_FORMAT", "IDENTITY"),
    ("UCRF.PT.NUMBER_INVALID", "CONTACT"), ("UCRF.EC.EMAIL_INVALID", "CONTACT"),
    ("UCRF.PA.PIN_FORMAT", "ADDRESS"), ("UCRF.TL.CLOSED_WITH_BALANCE", "LOAN"),
    ("UCRF.REC.NO_PHONE_OR_ID", "MINIMUM"), ("UCRF.REQUIRED.party.full_name", "PERSONAL"),
    ("UCRF.ENUM.party_address.state_code", "ADDRESS"), ("UCRF.ADJ.NOT_FOUND", "LOAN"),
    ("UCRF.REQUIRED.extension_attribute.attr_name", "LOAN"), ("NBFC017.HL_NEEDS_COLLATERAL", "CUSTOM"),
])
def test_category_from_the_pack(rule_id, expected):
    assert HINTS.category(rule_id) == expected


def test_every_builtin_rule_has_a_category_and_effect():
    for r in builtin_rules("CONSUMER"):
        assert r.category in HINTS.categories and HINTS.category(r.rule_id) == r.category
        assert str(r.outcome) in results.EFFECTS
    assert list(HINTS.categories)[-1] == HINTS.custom_category == "CUSTOM"


def test_pack_declares_prefix_and_cascade():
    pack = load_pack_file(type_definition("CONSUMER").path("rules.yaml"))
    assert pack.prefix == "UCRF." and pack.cascade.name == "account_holder_minimums"
    assert pack.cascade.settings["qualifying_id_types"][0] == "PAN"


def test_pack_category_overrides_the_default(tmp_path):
    pack = yaml.safe_load((type_definition("CONSUMER").path("rules.yaml")).read_text("utf-8"))
    pack["rules"][0]["category"] = "MINIMUM"
    path = tmp_path / "pack.yaml"
    path.write_text(yaml.safe_dump(pack), encoding="utf-8")
    rule = next(r for r in load_pack(path) if r.rule_id == pack["rules"][0]["id"])
    assert rule.category == "MINIMUM"
    pack["rules"][0]["category"] = "NOPE"
    path.write_text(yaml.safe_dump(pack), encoding="utf-8")
    with pytest.raises(RuleDefinitionError, match="unknown category"):
        load_pack(path)


def test_generated_messages_are_readable():
    rule = next(r for r in builtin_rules("CONSUMER") if r.rule_id == "UCRF.REQUIRED.account.account_number")
    assert rule.message == "Account number is required"


@pytest.mark.parametrize("tenant_id", ["nbfc_001", "nbfc_002"])
def test_report_counts_records_and_adds_up(engine, lms_engine, tenant_repo, tenant_id):
    snapshot_id = extract(engine, lms_engine, tenant_repo, tenant_id)
    validate(engine, tenant_id, snapshot_id)
    rep = report(engine, snapshot_id)
    k, recs = rep["kpis"], outcomes(engine, snapshot_id)

    assert k["records"] == len(recs) and k["reported"] + k["not_reported"] == k["records"]
    assert k["not_reported"] == sum(v == "REJECTED" for v in recs.values()) > 0
    assert sum(c["records"] for c in rep["not_reported_by_category"]) == k["not_reported"]   # one main reason each
    assert 0 < k["with_gaps"] <= k["reported"]

    cats = {c["key"]: c for c in rep["categories"]}
    assert list(cats) == [c for c in HINTS.categories if c in cats]                        # display order
    rule = {r["rule_id"]: r for c in rep["categories"] for r in c["rules"]}
    closed = rule["UCRF.TL.CLOSED_WITH_BALANCE"]
    assert closed["effect"] == "Not reported" and closed["records"] >= 1 and closed["message"]
    assert "UCRF.TL.CLOSED_WITH_BALANCE" in {r["rule_id"] for r in cats["LOAN"]["rules"]}
    assert rule["UCRF.EC.EMAIL_INVALID"]["effect"] == "Partly reported" and cats["CONTACT"]["with_gaps"] >= 1
    assert all(r["records"] <= k["records"] for r in rule.values())


def test_expected_rules_are_not_gaps(engine, lms_engine, tenant_repo):
    from dataclasses import replace
    snapshot_id = extract(engine, lms_engine, tenant_repo, "nbfc_001")
    validate(engine, "nbfc_001", snapshot_id)
    plain, hinted = report(engine, snapshot_id, replace(HINTS, expected=frozenset())), report(engine, snapshot_id)
    assert "UCRF.TL.ASSET_CLASS_WITH_DPD" in hinted["expected_rules"]
    asset = next(r for c in hinted["categories"] for r in c["rules"] if r["rule_id"] == "UCRF.TL.ASSET_CLASS_WITH_DPD")
    assert asset["expected"] and asset["effect"] == results.EXPECTED_EFFECT and asset["records"] > 0
    loan = next(c for c in hinted["categories"] if c["key"] == "LOAN")
    assert loan["rules"][-1]["expected"]                                         # listed last
    assert hinted["kpis"]["with_gaps"] < plain["kpis"]["with_gaps"]
    assert hinted["kpis"]["with_gaps"] < hinted["kpis"]["reported"] / 2           # no longer "nearly everything"
    assert hinted["kpis"]["not_reported"] == plain["kpis"]["not_reported"]        # file outcome unchanged


def test_findings_api_filters_by_category(engine, lms_engine, tenant_repo, make_api):
    snapshot_id = extract(engine, lms_engine, tenant_repo, "nbfc_001")
    validate(engine, "nbfc_001", snapshot_id)
    api = make_api()
    status, data = api.get(f"/snapshots/{snapshot_id}/findings", category="CONTACT")
    assert status == 200 and data["total"] > 0
    assert {f["rule_id"].split(".")[1] for f in data["findings"]} <= {"PT", "EC", "REQUIRED", "ENUM"}
    assert data["report"]["kpis"]["records"] > 0
    assert api.get(f"/snapshots/{snapshot_id}/findings", category="NOPE")[0] == 400
