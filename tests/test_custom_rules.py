"""K.8 custom rules without SQL: definition -> SQL, safety, findings in a real validation, the page."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from submissions.adapters.extract import run_extract
from submissions.adapters.mapping import load_mapping
from submissions.ops.tables import audit_event
from submissions.snapshot import SnapshotRepository
from submissions.validation import custom as C
from submissions.validation.engine import validate_snapshot
from submissions.validation.rules import load_rule_set, set_policy
from submissions.validation.tables import validation_finding

CLIENTS = Path(__file__).resolve().parent.parent / "clients"
AS_OF = date(2026, 9, 30)


def d(**kw) -> C.Definition:
    base = dict(name="TEST_RULE", entity="account", field="high_credit_amount", check="range", outcome="WARN",
                message="Sanction below the NBFC minimum", min="100000")
    return C.Definition(**base | kw)


@pytest.mark.parametrize("definition, sql_part", [
    (d(), "x.high_credit_amount IS NOT NULL AND (x.high_credit_amount < 100000)"),
    (d(check="required", field="emi_amount"), "x.emi_amount IS NULL"),
    (d(check="required", field="account_number"), "(x.account_number IS NULL OR TRIM(x.account_number) = '')"),
    (d(check="in_list", field="account_type", values=["05", "06"]), "x.account_type NOT IN ('05', '06')"),
    (d(check="not_in_list", field="account_type", values=["10"]), "x.account_type IN ('10')"),
    (d(check="length", field="account_number", min="8", max="20"),
     "(CHAR_LENGTH(x.account_number) < 8 OR CHAR_LENGTH(x.account_number) > 20)"),
    (d(check="pattern", field="account_number", pattern="^B[0-9]"), "NOT REGEXP_LIKE(x.account_number, '^B[0-9]')"),
    (d(check="compare", field="amount_overdue", operator="<=", other_field="current_balance"),
     "NOT (x.amount_overdue <= x.current_balance)"),
    (d(when_field="account_type", when_values=["05"]), "AND x.account_type IN ('05')"),
    (d(entity="party", field="birth_date", min="1940-01-01"), "x.birth_date < '1940-01-01'"),
])
def test_compiles_to_sql(definition, sql_part):
    sql = C.compile_sql(definition)
    assert sql_part in sql and ":snapshot_id" in sql and sql.startswith("SELECT x.row_id")


@pytest.mark.parametrize("definition, message", [
    (d(name="bad name"), "Name"),
    (d(field="no_such_field"), "Unknown field"),
    (d(entity="tenant"), "Unknown record type"),
    (d(min=None), "minimum, a maximum or both"),
    (d(min="12abc"), "not a number"),
    (d(field="account_number", min="1"), "Range works on numbers and dates"),
    (d(check="pattern", field="account_number", pattern="[unclosed"), "not a valid regular expression"),
    (d(check="compare", field="amount_overdue", operator="<", other_field="date_opened"), "different types"),
    (d(check="in_list", field="account_type", values=[]), "at least one value"),
    (d(outcome="NOPE"), "outcome"),
    (d(message=" "), "Message"),
])
def test_invalid_definitions(definition, message):
    with pytest.raises(C.CustomRuleError, match=message):
        C.build("nbfc_001", definition)


def test_values_cannot_inject_sql():
    sql = C.compile_sql(d(check="in_list", field="account_type", values=["05') OR 1=1 --"]))
    assert "'05'') OR 1=1 --'" in sql                                       # quoted as a plain string
    with pytest.raises(C.CustomRuleError):
        C.compile_sql(d(field="high_credit_amount; DROP TABLE c_account"))
    with pytest.raises(C.CustomRuleError):
        C.compile_sql(d(min="1 OR 1=1"))


# ---------------------------------------------------------------- in a real validation
def validated_snapshot(engine, lms_engine, tenant_repo):
    sid = run_extract(tenant=tenant_repo.get("nbfc_001"), mapping=load_mapping(CLIENTS / "nbfc_001" / "mapping.yaml"),
                      submission_type="CONSUMER", as_of_date=AS_OF, app_engine=engine, source_engine=lms_engine,
                      snapshots=SnapshotRepository(engine), owner="t").snapshot_id
    validate_snapshot(engine, SnapshotRepository(engine), sid, load_rule_set(engine, "nbfc_001", "CONSUMER"))
    return sid


def custom_findings(engine, sid, rule_id):
    with engine.connect() as conn:
        return conn.execute(select(validation_finding).where(validation_finding.c.snapshot_id == sid,
                                                             validation_finding.c.rule_id == rule_id)).all()


def test_custom_rule_runs_with_the_pack(engine, lms_engine, tenant_repo):
    rule = C.save(engine, "nbfc_001", "CONSUMER", d(min="10000000"), "u")      # 1 crore: most loans are below
    rule2 = C.save(engine, "nbfc_001", "CONSUMER",
                   d(name="PAN_FORMAT_STRICT", entity="party_identifier", field="id_number", check="pattern",
                     pattern="^[A-Z0-9]+$", when_field="id_type", when_values=["01"], outcome="REJECT_SEGMENT",
                     message="PAN has stray characters", min=None), "u")
    sid = validated_snapshot(engine, lms_engine, tenant_repo)
    hits = custom_findings(engine, sid, rule.rule_id)
    assert hits and all(h.outcome == "WARN" and h.account_key for h in hits)
    preview_count, examples = C.preview(engine, rule, sid)
    assert preview_count == len(hits) and len(examples) <= 5
    assert rule2.rule_id == "CUSTOM.NBFC_001.PAN_FORMAT_STRICT"

    set_policy(engine, "nbfc_001", rule.rule_id, is_enabled=False)            # same switches as UCRF rules
    sid2 = validated_snapshot(engine, lms_engine, tenant_repo)
    assert custom_findings(engine, sid2, rule.rule_id) == []
    assert not [r for r in load_rule_set(engine, "nbfc_002", "CONSUMER") if r.rule_id == rule.rule_id]   # per NBFC


def test_duplicate_name_and_delete(engine):
    C.save(engine, "nbfc_001", "CONSUMER", d(), "u")
    with pytest.raises(C.CustomRuleError, match="already exists"):
        C.save(engine, "nbfc_001", "CONSUMER", d(), "u")
    C.save(engine, "nbfc_001", "CONSUMER", d(min="5"), "u", replace_existing=True)
    assert C.definitions(engine, "nbfc_001", "CONSUMER")["CUSTOM.NBFC_001.TEST_RULE"].min == "5"
    assert C.delete_rule(engine, "nbfc_001", "CUSTOM.NBFC_001.TEST_RULE")
    assert C.definitions(engine, "nbfc_001", "CONSUMER") == {}


# ---------------------------------------------------------------- page
FORM = {"type": "CONSUMER", "name": "MIN_SANCTION", "field": "account.high_credit_amount", "check": "range",
        "min": "10000000", "outcome": "WARN", "message": "Sanction below 1 crore"}
RULE_ID = "CUSTOM.NBFC_001.MIN_SANCTION"


def test_api_preview_save_edit_delete(make_api, engine, lms_engine, tenant_repo):
    api = make_api(tenant="nbfc_001")
    status, preview = api.post("/rules/custom/preview", **FORM)
    assert status == 200 and preview["snapshot"] is None and "high_credit_amount" in preview["sql"]
    validated_snapshot(engine, lms_engine, tenant_repo)
    _, preview = api.post("/rules/custom/preview", **FORM)
    assert isinstance(preview["count"], int) and preview["snapshot"]["snapshot_id"]
    assert C.definitions(engine, "nbfc_001", "CONSUMER") == {}                  # nothing saved

    status, err = api.post("/rules/custom", **FORM)
    assert status == 400 and "Give a reason" in err["error"]
    status, saved = api.post("/rules/custom", reason="credit policy", **FORM)
    assert status == 200 and saved["rule_id"] == RULE_ID
    _, page = api.get("/rules", type="CONSUMER")
    assert page["custom"][RULE_ID]["describe"] == "account.high_credit_amount is between 10000000 and …"
    assert next(r for r in page["rules"] if r["rule_id"] == RULE_ID)["kind_label"] == "Custom (form)"

    api.post("/rules/custom", reason="lowered", editing=RULE_ID, **FORM | {"min": "500000"})
    assert C.definitions(engine, "nbfc_001", "CONSUMER")[RULE_ID].min == "500000"
    assert api.post("/rules/custom", reason="r", editing=RULE_ID, **FORM | {"name": "OTHER"})[0] == 400

    api.post(f"/rules/custom/{RULE_ID}/delete", type="CONSUMER")
    assert C.definitions(engine, "nbfc_001", "CONSUMER") == {}
    assert api.post(f"/rules/custom/{RULE_ID}/delete", type="CONSUMER")[0] == 404
    with engine.connect() as conn:
        actions = list(conn.execute(select(audit_event.c.action).order_by(audit_event.c.event_id)).scalars())
    assert actions == ["CUSTOM_RULE_ADDED", "CUSTOM_RULE_CHANGED", "CUSTOM_RULE_DELETED"]
