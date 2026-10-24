"""Commercial (phase 4): the pipe-delimited file from the mock snapshots. Structure checks against the spec, and
golden files byte for byte (regenerate after an intended change: $env:REGENERATE_GOLDEN = "1").
"""

from datetime import date

import pytest

from mock_data.commercial import rows as commercial_rows
from submissions.bureaus import BureauProfile
from submissions.enums import BureauCode, ReportingCycle
from submissions.types import type_definition
from submissions.types.commercial.file import build_file
from tests.test_commercial_rules import _validate
from tests.test_ucrf_golden import check

AS_OF = date(2026, 9, 30)
CREATED = date(2026, 10, 5)
FIELDS = {"HD": 7, "BS": 27, "AS": 17, "RS": 39, "CR": 45, "GS": 38, "SS": 7, "CD": 8, "TS": 4}
ORDER = {"HD": {"BS"}, "BS": {"AS"}, "AS": {"AS", "RS", "CR"}, "RS": {"RS", "CR"},      # 6 Table 2 (AS -> CR only
         "CR": {"CR", "GS", "SS", "CD", "BS", "TS"}, "GS": {"GS", "SS", "CD", "CR", "BS", "TS"},   # for 9026, no RS)
         "SS": {"SS", "CD", "CR", "BS", "TS"}, "CD": {"CD", "CR", "BS", "TS"}}


def bureau(tenant_id: str, code: BureauCode) -> BureauProfile:
    return BureauProfile(tenant_id, code, "COMMERCIAL", f"{code.value} commercial", f"CM{tenant_id[-3:]}0001",
                         None, "", "Commercial-ME-{as_of:%d%m%Y}-{member_id}.txt")


@pytest.fixture
def commercial_file(engine, lms_engine, tenant_repo):
    def make(tenant_id="nbfc_001", code=BureauCode.CIBIL):
        result, outcomes, findings = _validate(engine, lms_engine, tenant_repo, tenant_id)
        content, stats = build_file(engine, result.snapshot_id, AS_OF, bureau(tenant_id, code),
                                    ReportingCycle.MONTH_END, CREATED)
        return content, stats, outcomes
    return make


def _lines(content: bytes) -> list[list[str]]:
    text = content.decode("ascii")
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    lines = text.split("\r\n")[:-1]
    assert all(line.endswith("|") for line in lines)                 # trailing delimiter (decision 8)
    return [line[:-1].split("|") for line in lines]


def test_file_structure_follows_the_spec(commercial_file):
    content, stats, outcomes = commercial_file()
    lines = _lines(content)
    tags = [f[0] for f in lines]
    for f in lines:
        assert len(f) == FIELDS[f[0]], f"{f[0]} has {len(f)} fields"
    for a, b in zip(tags, tags[1:]):
        assert b in ORDER[a], f"{a} followed by {b}"
    assert tags[0] == "HD" and tags[-1] == "TS" and tags.count("HD") == tags.count("TS") == 1
    hd, ts = lines[0], lines[-1]
    assert hd[1:6] == ["CM0010001", "", "05102026", "30092026", "ME"]
    assert ts[1:3] == [str(tags.count("BS")), str(tags.count("CR"))]
    accepted = [k for k, (o, _) in outcomes.items() if o == "ACCEPTED"]
    assert tags.count("CR") == stats.written == len(accepted) and stats.rejected == len(outcomes) - len(accepted)
    assert "~" not in content.decode() and "^" not in content.decode()


def test_rejected_and_dropped_data_is_left_out(commercial_file):
    content, _, outcomes = commercial_file()
    lines = _lines(content)
    facilities = {f["test_scenario_number"]: f for f in commercial_rows(1)["business_facility"]}
    numbers = {f[1] for f in lines if f[0] == "CR"}
    for no in (14, 15):                                               # rejected records: no CR line
        assert facilities[no]["facility_number"] not in numbers
    borrowers = {b["customer_id"]: b for b in commercial_rows(1)["business_borrower"]}
    bs16 = next(f for f in lines if f[0] == "BS" and f[3] == borrowers[facilities[16]["customer_id"]]["business_name"])
    assert bs16[8] == "" and bs16[7] != ""                            # CIN (field 9) dropped, PAN (field 8) kept
    after17 = lines[[f[1] for f in lines].index(facilities[17]["facility_number"]) + 1]
    assert after17[0] != "SS"                                         # security without classification left out


def test_values_are_written_as_commercial_codes(commercial_file):
    content, _, _ = commercial_file()
    lines = _lines(content)

    def field(line, no):                                             # spec field number (1 = segment tag)
        return line[no - 1]

    f = {r["test_scenario_number"]: r for r in commercial_rows(1)["business_facility"]}
    cr = {field(line, 2): line for line in lines if line[0] == "CR"}
    wo = cr[f[7]["facility_number"]]                                  # written off, wilful, suit decreed
    assert [field(wo, n) for n in (6, 7, 15, 26, 35, 37)] == ["INR", "0420", "1430", "05", "1", "03"]
    closed = cr[f[8]["facility_number"]]
    assert [field(closed, n) for n in (11, 26, 27)] == ["0", "02", "15072026"]
    cc = cr[f[1]["facility_number"]]                                  # cash credit: revolving, rolling
    assert [field(cc, n) for n in (7, 9, 15, 26, 35, 42)] == ["0100", "07", "1000", "01", "0", "01"]
    lc = next(line for line in lines if line[0] == "CR" and field(line, 7) == "3000")
    assert field(lc, 6) == "USD"
    bs = next(line for line in lines if line[0] == "BS")
    assert [field(bs, n) for n in (13, 14, 15)] == ["11", "05", "01"]   # private limited, medium, manufacturing
    assert {field(line, 3) for line in lines if line[0] == "RS"} >= {"1", "2", "3"}
    sg = next(line for line in lines if line[0] == "RS" and field(line, 33) not in ("079", ""))
    assert [field(sg, n) for n in (3, 4, 31, 25)] == ["3", "11", "77", "5100"]   # foreign entity, holding, 51%
    assert field(sg, 33) == type_definition("COMMERCIAL").translations["country"]["SINGAPORE"].output_code


@pytest.mark.parametrize("tenant_id", ["nbfc_001", "nbfc_002"])
def test_files_match_golden(commercial_file, tenant_id):
    for code in BureauCode:
        content, _, _ = commercial_file(tenant_id, code)
        check(f"commercial_{tenant_id}_{code.value.lower()}.txt", content)
