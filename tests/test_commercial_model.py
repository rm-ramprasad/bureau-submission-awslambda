"""Commercial (phase 2): canonical model 1.1, the base commercial mapping and its extract from the mock LMS."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from mock_data.commercial import rows as commercial_rows
from submissions.adapters.extract import run_extract
from submissions.adapters.mapping import load_mapping, mapping_file
from submissions.canonical.definition import canonical_model
from submissions.canonical.schema import ENTITY_TABLES
from submissions.snapshot import SnapshotRepository
from submissions.types import type_definition

ROOT = Path(__file__).resolve().parent.parent
AS_OF = date(2026, 9, 30)


def _extract(engine, lms_engine, tenant_repo, tenant_id="nbfc_001"):
    tenant = tenant_repo.get(tenant_id)
    mapping = load_mapping(mapping_file(ROOT, tenant.mapping_path, "COMMERCIAL"))
    return run_extract(tenant=tenant, mapping=mapping, submission_type="COMMERCIAL", as_of_date=AS_OF,
                       app_engine=engine, source_engine=lms_engine, snapshots=SnapshotRepository(engine), owner="t")


def _rows(engine, entity, sid, **where):
    t = ENTITY_TABLES[entity]
    q = select(t).where(t.c.snapshot_id == sid, *(t.c[k] == v for k, v in where.items())).order_by(t.c.row_id)
    with engine.connect() as conn:
        return conn.execute(q).all()


def test_base_mapping_loads_and_guarantor_reuses_the_related_party_columns():
    m = load_mapping(ROOT / "clients" / "nbfc_001" / "commercial.yaml")
    assert str(m.submission_type) == "COMMERCIAL"
    rel, gua = (m.entities[e].selects[0].columns for e in ("relationship", "guarantor"))
    assert {"party_key", "relationship_type", "control_percentage"} <= set(rel)
    assert not {"party_key", "relationship_type", "control_percentage"} & set(gua)     # removed with null
    assert gua["account_key"].expr == "p.facility_id" and gua["pan"].expr == rel["pan"].expr


@pytest.mark.parametrize("tenant_id,tenant_no", [("nbfc_001", 1), ("nbfc_002", 2)])
def test_extract_matches_the_mock_lms(engine, lms_engine, tenant_repo, tenant_id, tenant_no):
    src = commercial_rows(tenant_no)
    b, a = src["business_borrower"], src["business_address"]
    ids = ["pan", "cin", "tin", "service_tax", "udyam", "company_reg_no", "ckyc"]
    expected = {"party": len(b), "party_identifier": sum(1 for r in b for c in ids if r.get(c)),
                "party_address": len(a), "party_email": sum(1 for r in a if r["email"]),
                "party_phone": sum(1 for r in a for c in ("mobile", "phone") if r[c]),
                "account": len(src["business_facility"]), "account_holder": len(src["business_facility"]),
                "relationship": len(src["business_relationship"]), "guarantor": len(src["facility_guarantor"]),
                "security": len(src["facility_security"]), "cheque_dishonour": len(src["facility_cheque_bounce"]),
                "account_history": 0, "extension_attribute": 0}
    result = _extract(engine, lms_engine, tenant_repo, tenant_id)
    assert result.row_counts == expected


def test_values_land_as_canonical_values(engine, lms_engine, tenant_repo):
    sid = _extract(engine, lms_engine, tenant_repo).snapshot_id
    first = _rows(engine, "party", sid, party_key="B0001")[0]
    assert (first.legal_constitution, first.business_category, first.industry_type, first.rating_agency) == \
        ("PRIVATE_LIMITED", "MEDIUM", "MANUFACTURING", "CRISIL")
    assert {i.id_type for i in _rows(engine, "party_identifier", sid, party_key="B0001")} == {"PAN", "CIN", "UDYAM"}
    assert [a.address_category for a in _rows(engine, "party_address", sid, party_key="B0001")] == \
        ["REGISTERED_OFFICE", "PLANT_FACTORY"]
    scenario_7 = next(f["facility_id"] for f in commercial_rows(1)["business_facility"]
                      if f["test_scenario_number"] == 7)
    wo = _rows(engine, "account", sid, account_key=scenario_7)[0]
    assert (wo.credit_facility_status, wo.suit_filed_status, wo.asset_classification, wo.wilful_default_date) == \
        ("WRITTEN_OFF", "DECREE_ISSUED", "LOSS", date(2025, 6, 30))
    holding = [r for r in _rows(engine, "relationship", sid) if r.country == "SINGAPORE"]
    assert holding and (holding[0].related_type, holding[0].relationship_type, holding[0].control_percentage) == \
        ("FOREIGN_ENTITY", "HOLDING_COMPANY", Decimal("51.00"))
    g = _rows(engine, "guarantor", sid)
    assert {r.related_type for r in g} == {"INDIAN_INDIVIDUAL", "INDIAN_ENTITY"} and all(r.account_key for r in g)
    assert {s.security_classification for s in _rows(engine, "security", sid)} == \
        {"PRIMARY_FIRST_CHARGE", "COLLATERAL_FIRST_CHARGE", None}                 # scenario 17: no charge
    assert _rows(engine, "cheque_dishonour", sid)[0].reason == "INSUFFICIENT_FUNDS"


def test_every_code_in_the_snapshot_has_a_commercial_file_code(engine, lms_engine, tenant_repo):
    """The mock data only uses values the commercial file can report (no ENUM findings from mapping gaps)."""
    sid = _extract(engine, lms_engine, tenant_repo).snapshot_id
    commercial, model = type_definition("COMMERCIAL"), canonical_model()
    missing = set()
    for entity, edef in model.entities.items():
        for col in edef.columns:
            if col.code_list in commercial.translations:
                for r in _rows(engine, entity, sid):
                    value = getattr(r, col.name)
                    if value is not None and value not in commercial.translations[col.code_list]:
                        missing.add(f"{entity}.{col.name}={value}")
    assert not missing
