"""Rule parameters as data: pack defaults, per-NBFC overrides, effect on validation, Rules & policies page."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from submissions.adapters.extract import run_extract
from submissions.adapters.mapping import load_mapping
from submissions.ops.tables import audit_event
from submissions.snapshot import SnapshotRepository
from submissions.validation import parameters as P
from submissions.validation.checks.identifiers import id_number_problem
from submissions.validation.engine import validate_snapshot
from submissions.validation.rules import load_rule_set
from submissions.validation.tables import validation_finding

CLIENTS = Path(__file__).resolve().parent.parent / "clients"
AS_OF = date(2026, 9, 30)


def test_pack_declares_the_parameters_with_typed_defaults():
    params = P.builtin_parameters("CONSUMER")
    assert params["dob_gender_required_from"].default == date(2005, 5, 1)
    assert params["phone_or_id_required_from"].default == date(2007, 6, 1)
    assert params["min_address_length"].default == 3
    assert params["id_pattern_pan"].default.startswith("^[A-Z]{3}")
    assert set(params["state_pin_required_from"].used_by) == {"UCRF.PA.STATE_REQUIRED", "UCRF.PA.PIN_REQUIRED"}


@pytest.mark.parametrize("name, raw, message", [
    ("dob_gender_required_from", "01-05-2005", "YYYY-MM-DD"),
    ("min_address_length", "two", "whole number"),
    ("min_address_length", "0", "between 1 and 40"),
    ("id_pattern_pan", "^[A-Z", "not a valid regular expression"),
    ("id_pattern_pan", "", "enter a value"),
])
def test_invalid_values_are_rejected(name, raw, message):
    with pytest.raises(P.ParameterError, match=message):
        P.builtin_parameters("CONSUMER")[name].parse(raw)


def test_override_is_per_nbfc_and_default_removes_it(engine):
    P.set_parameter(engine, "nbfc_001", "CONSUMER", "min_address_length", "10", "u")
    assert P.load_parameters(engine, "nbfc_001", "CONSUMER")["min_address_length"] == 10
    assert P.load_parameters(engine, "nbfc_002", "CONSUMER")["min_address_length"] == 3
    P.set_parameter(engine, "nbfc_001", "CONSUMER", "min_address_length", "3", "u")      # the default again
    assert P.overrides(engine, "nbfc_001", "CONSUMER") == {}


def test_messages_show_the_values():
    assert P.render_message("on or after {dob_gender_required_from:%d-%m-%Y}",
                            {"dob_gender_required_from": date(2010, 1, 2)}) == "on or after 02-01-2010"
    assert P.render_message("no placeholders", {}) == "no placeholders"
    assert P.render_message("{unknown}", {}) == "{unknown}"


def test_id_patterns_can_be_overridden():
    assert id_number_problem("PAN", "ABCDE1234F") is not None                  # 4th letter must be P or H
    assert id_number_problem("PAN", "ABCPE1234F") is None
    loose = {"id_pattern_pan": r"^[A-Z]{5}[0-9]{4}[A-Z]$"}
    assert id_number_problem("PAN", "ABCDE1234F", loose) is None
    assert "does not match the pattern" in id_number_problem("PAN", "1234", loose)
    assert id_number_problem("AADHAAR", "123456789012", loose) is not None        # Aadhaar checksum is not a parameter


# ---------------------------------------------------------------- effect on a real validation
def validate(engine, lms_engine, tenant_repo):
    sid = run_extract(tenant=tenant_repo.get("nbfc_001"), mapping=load_mapping(CLIENTS / "nbfc_001" / "consumer.yaml"),
                      submission_type="CONSUMER", as_of_date=AS_OF, app_engine=engine, source_engine=lms_engine,
                      snapshots=SnapshotRepository(engine), owner="t").snapshot_id
    result = validate_snapshot(engine, SnapshotRepository(engine), sid, load_rule_set(engine, "nbfc_001", "CONSUMER"))
    with engine.connect() as conn:
        found = conn.execute(select(validation_finding.c.rule_id, validation_finding.c.message)
                             .where(validation_finding.c.snapshot_id == sid)).all()
    return result, found


def test_parameters_change_the_validation(engine, lms_engine, tenant_repo):
    before, found = validate(engine, lms_engine, tenant_repo)
    phone_or_id = [m for r, m in found if r == "UCRF.REC.NO_PHONE_OR_ID"]
    assert phone_or_id and "01-06-2007" in phone_or_id[0]                      # message carries the value

    P.set_parameter(engine, "nbfc_001", "CONSUMER", "phone_or_id_required_from", "2099-01-01", "u")
    P.set_parameter(engine, "nbfc_001", "CONSUMER", "min_address_length", "40", "u")
    after, found = validate(engine, lms_engine, tenant_repo)
    assert not [r for r, _ in found if r == "UCRF.REC.NO_PHONE_OR_ID"]         # no account opened after 2099
    short = [m for r, m in found if r == "UCRF.PA.ADDRESS_TOO_SHORT"]
    assert short and "shorter than 40 characters" in short[0]
    assert after.records == before.records


# ---------------------------------------------------------------- page
def messages(api) -> str:
    return " ".join(r["message"] for r in api.get("/rules", type="CONSUMER")[1]["rules"])


def test_parameters_through_the_api(make_api, engine):
    api = make_api(tenant="nbfc_001")
    _, page = api.get("/rules", type="CONSUMER")
    labels = {p["name"]: p["label"] for p in page["parameters"]}
    assert labels["phone_or_id_required_from"] == "Phone or ID required from"
    assert "on or after 01-05-2005" in messages(api)                           # rule messages show the values
    status, err = api.post("/rules/parameters/min_address_length", type="CONSUMER", value="5")
    assert status == 400 and "give a reason" in err["error"]
    status, err = api.post("/rules/parameters/id_pattern_pan", type="CONSUMER", value="^[A-Z", reason="r")
    assert status == 400 and "not a valid regular expression" in err["error"]
    api.post("/rules/parameters/dob_gender_required_from", type="CONSUMER", value="2010-01-01", reason="NBFC policy")
    assert "on or after 01-01-2010" in messages(api)
    param = next(p for p in api.get("/rules", type="CONSUMER")[1]["parameters"]
                 if p["name"] == "dob_gender_required_from")
    assert param["value"] == "2010-01-01" and param["override"]["updated_by"] == "internal-user"
    assert P.load_parameters(engine, "nbfc_001", "CONSUMER")["dob_gender_required_from"] == date(2010, 1, 1)
    api.post("/rules/parameters/dob_gender_required_from/reset", type="CONSUMER")
    assert P.overrides(engine, "nbfc_001", "CONSUMER") == {}
    with engine.connect() as conn:
        actions = list(conn.execute(select(audit_event.c.action).order_by(audit_event.c.event_id)).scalars())
    assert actions == ["RULE_PARAMETER_CHANGED", "RULE_PARAMETER_RESET"]
    assert api.post("/rules/parameters/nope", type="CONSUMER", value="1")[0] == 404
    assert make_api().post("/rules/parameters/min_address_length", value="5", reason="r")[0] == 400   # no NBFC
