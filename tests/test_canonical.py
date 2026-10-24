from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from sqlalchemy import delete, func, inspect, select

from submissions.canonical.definition import MODEL_PATH, ModelDefinitionError, canonical_model, parse_model
from submissions.canonical.generate import generate_sql, main as generate_main
from submissions.canonical.schema import (
    ENTITY_TABLES, RECORD_TYPES, extract_snapshot, record_from_row, ref_code, ref_code_rows, ref_state_pin,
    ref_state_pin_rows,
)
from submissions.types import type_definition

EXPECTED_ENTITIES = {"party", "party_identifier", "party_phone", "party_email", "party_address", "account",
                     "account_holder", "account_history", "extension_attribute",
                     "relationship", "guarantor", "security", "cheque_dishonour"}         # 1.1: commercial


# ---------------------------------------------------------------- definition
def test_packaged_model_loads():
    model = canonical_model()
    assert model.version == "1.1"
    assert set(model.entities) == EXPECTED_ENTITIES
    assert model.entities["account_holder"].column("ownership_indicator").code_list == "ownership_indicator"


def _file_codes(tdef, list_name: str) -> set[str]:
    return {t.output_code for t in tdef.translations[list_name].values()}


def test_code_lists_match_spec_appendices():
    """Canonical lists are the union of every type's catalogues; each type's file codes match its own spec."""
    consumer = type_definition("CONSUMER")
    assert len(_file_codes(consumer, "account_type")) == 61                  # 00-21, 23-47, 50-59, 61, 69-71
    assert _file_codes(consumer, "id_type") == {f"{n:02d}" for n in range(1, 11)}
    assert len(_file_codes(consumer, "credit_facility_status")) == 19
    assert consumer.groups["card_account_type"] == ("CREDIT_CARD", "FLEET_CARD", "SECURED_CREDIT_CARD",
                                                    "CORPORATE_CREDIT_CARD")
    future = {v for v, t in consumer.translations["account_type"].items() if not t.active}   # "future use" in the spec
    assert future == {"TELCO_WIRELESS", "TELCO_BROADBAND", "TELCO_LANDLINE"}
    assert "26" not in _file_codes(consumer, "state_code")

    commercial = type_definition("COMMERCIAL")                               # Commercial UCRF 3.10, section 8
    assert len(_file_codes(commercial, "account_type")) == 66                # 8.8 credit types
    assert _file_codes(commercial, "credit_facility_status") == {f"{n:02d}" for n in range(3, 25)}   # 8.10 (01/02: dates)
    assert _file_codes(commercial, "state_code") == {f"{n:02d}" for n in range(1, 38) if n != 9} | {"77", "99"}
    assert len(_file_codes(commercial, "country")) == 195 and "079" in _file_codes(commercial, "country")
    assert commercial.translations["currency"]["INR"].output_code == "INR"
    assert commercial.groups["revolving_credit_type"] == ("CASH_CREDIT", "OVERDRAFT", "CORPORATE_CREDIT_CARD",
                                                          "TEMPORARY_OVERDRAFT")


def test_every_code_column_references_a_code_list():
    model = canonical_model()
    for entity in model.entities.values():
        for col in entity.columns:
            assert (col.type == "code") == (col.code_list is not None), f"{entity.name}.{col.name}"


def _raw():
    return yaml.safe_load(MODEL_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("mutate,message", [
    (lambda m: m.pop("canonical_version"), "canonical_version"),
    (lambda m: m["entities"]["party"]["columns"]["gender"].update(code_list="sex"), "unknown code_list"),
    (lambda m: m["entities"]["party"]["columns"]["full_name"].update(type="text"), "type must be"),
    (lambda m: m["entities"]["party"]["columns"]["full_name"].pop("length"), "need a length"),
    (lambda m: m["entities"]["party"]["columns"].update(row_id={"type": "integer"}), "reserved"),
    (lambda m: m["entities"]["party"]["columns"]["full_name"].update(colour="red"), "unknown keys"),
    (lambda m: m["entities"]["party"].update(indexes=[["nope"]]), "unknown columns"),
    (lambda m: m["entities"]["party"]["columns"]["full_name"].update(description="a; b"), "semicolon"),
    (lambda m: m["code_lists"]["gender"]["codes"].update({4: "Other"}), "quoted"),
    (lambda m: m["code_lists"]["gender"]["codes"].update({"X" * 41: "Too long"}), "longer than 40"),
    (lambda m: m["entities"]["party_email"].update(table="c_party"), "duplicate table"),
])
def test_invalid_definitions_rejected(mutate, message):
    raw = _raw()
    mutate(raw)
    with pytest.raises(ModelDefinitionError, match=message):
        parse_model(raw)


# ---------------------------------------------------------------- generated DDL (starting point for a migration)
def test_generator_writes_ddl(tmp_path):
    out = tmp_path / "ddl.sql"
    assert generate_main(["--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == generate_sql()


def test_generated_sql_shape():
    sql = generate_sql()
    for table in ["extract_snapshot", "ref_code", "ref_state_pin", "ref_code_translation", "ref_code_group",
                  *(t.name for t in ENTITY_TABLES.values())]:
        assert f"CREATE TABLE {table} (" in sql
    assert "ON DELETE CASCADE" in sql and "AUTO_INCREMENT" in sql
    assert "INSERT INTO" not in sql                       # reference rows: submissions.reference seed


# ---------------------------------------------------------------- tables
def test_entity_tables_have_row_id_snapshot_and_indexes():
    for name, table in ENTITY_TABLES.items():
        cols = table.c.keys()
        assert cols[:2] == ["row_id", "snapshot_id"], name
        assert all(c.nullable for c in table.c if c.name not in ("row_id", "snapshot_id")), name
        assert all(list(ix.columns)[0].name == "snapshot_id" for ix in table.indexes), name


def test_reference_rows():
    rows = ref_code_rows()
    assert len(rows) == sum(len(cl.codes) for cl in canonical_model().code_lists.values())
    pins = {r["state_code"]: (r["pin_prefix_min"], r["pin_prefix_max"]) for r in ref_state_pin_rows()}
    assert pins["MAHARASHTRA"] == (40, 44) and pins["APO"] == (90, 99) and "FOREIGN" not in pins
    assert len(pins) == 37   # consumer states 01-25, 27-37 and APO 99 (foreign 77 has no range)


def test_tables_create_and_round_trip(engine):
    assert set(ENTITY_TABLES[n].name for n in EXPECTED_ENTITIES) <= set(inspect(engine).get_table_names())
    now = datetime(2026, 10, 21)
    with engine.begin() as conn:
        assert conn.execute(select(func.count()).select_from(ref_code)).scalar() == len(ref_code_rows())
        snap = conn.execute(extract_snapshot.insert().values(
            tenant_id="nbfc_001", submission_type="CONSUMER", as_of_date=date(2026, 9, 30), canonical_version="1.0",
            status="BUILDING", created_at=now, updated_at=now)).inserted_primary_key[0]
        conn.execute(ENTITY_TABLES["account"].insert().values(
            snapshot_id=snap, account_key="L1", account_number="B101PL1", account_type="05",
            date_opened=date(2024, 1, 1), high_credit_amount=Decimal("300000.00"),
            current_balance=Decimal("-2450.50"), days_past_due=0))
        conn.execute(ENTITY_TABLES["account"].insert().values(snapshot_id=snap, account_type="HLX"))  # unmapped kept
        row = conn.execute(select(ENTITY_TABLES["account"]).where(ENTITY_TABLES["account"].c.account_key == "L1")).one()
    rec = record_from_row("account", row)
    assert type(rec) is RECORD_TYPES["account"] and rec.__class__.__name__ == "AccountRecord"
    assert (rec.snapshot_id, rec.current_balance, rec.emi_amount) == (snap, Decimal("-2450.50"), None)


def test_deleting_snapshot_cascades(engine):
    now = datetime(2026, 10, 21)
    with engine.begin() as conn:
        snap = conn.execute(extract_snapshot.insert().values(
            tenant_id="nbfc_001", submission_type="CONSUMER", as_of_date=date(2026, 9, 30), canonical_version="1.0",
            status="BUILDING", created_at=now, updated_at=now)).inserted_primary_key[0]
        conn.execute(ENTITY_TABLES["party"].insert(), [dict(snapshot_id=snap, party_key=f"C{i}") for i in range(3)])
        conn.execute(delete(extract_snapshot).where(extract_snapshot.c.snapshot_id == snap))
        assert conn.execute(select(func.count()).select_from(ENTITY_TABLES["party"])).scalar() == 0


def test_snapshot_unique_per_batch_tenant_type(engine):
    from sqlalchemy.exc import IntegrityError
    now = datetime(2026, 10, 21)
    values = dict(tenant_id="nbfc_001", submission_type="CONSUMER", as_of_date=date(2026, 9, 30), batch_id="b1",
                  canonical_version="1.0", status="BUILDING", created_at=now, updated_at=now)
    with engine.begin() as conn:
        conn.execute(extract_snapshot.insert().values(**values))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(extract_snapshot.insert().values(**values))
