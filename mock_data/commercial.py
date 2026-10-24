"""Mock LMS commercial data: business borrowers and their facilities, in both mock schemas (same layout).

  business_borrower        one row per business borrower (or an individual reported commercially)
  business_address         addresses with contacts (registered office, branch, plant ...)
  business_relationship    directors, partners, proprietors, holding companies ... of a borrower
  business_facility        credit facilities (one borrower each)
  facility_guarantor       guarantors of a facility
  facility_security        tangible securities of a facility
  facility_cheque_bounce   inward cheques dishonoured on a facility

Codes are the LMS's own (PVT, CC, STD ...): clients/_base/commercial.yaml translates them. Generated with its own
random seed, so the consumer mock data (and the consumer golden files) never change because of this module.
Each facility carries its expected record outcome (test_expected: ACCEPT / REJECT_RECORD) and the rule that must
fire for it (test_rule_reference) in its test_* columns: the oracle for the commercial rules.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from sqlalchemy import Column, Date, Integer, MetaData, Numeric, PrimaryKeyConstraint, String, Table

SEED = 7310
AS_OF = date(2026, 9, 30)

LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
# (city, district, client state spelling, PIN prefix 3 digits, STD code)
CITIES = [
    ("Mumbai", "Mumbai Suburban", "Maharashtra", "400", "022"), ("Pune", "Pune", "Maharashtra", "411", "020"),
    ("Bengaluru", "Bengaluru Urban", "Karnataka", "560", "080"), ("Chennai", "Chennai", "Tamil Nadu", "600", "044"),
    ("Hyderabad", "Hyderabad", "Telangana", "500", "040"), ("New Delhi", "New Delhi", "Delhi", "110", "011"),
    ("Ahmedabad", "Ahmedabad", "Gujarat", "380", "079"), ("Coimbatore", "Coimbatore", "Tamil Nadu", "641", "0422"),
    ("Ludhiana", "Ludhiana", "Punjab", "141", "0161"), ("Kolkata", "Kolkata", "West Bengal", "700", "033"),
]
PEOPLE = [("Mr", "Rajiv Malhotra", "M"), ("Mrs", "Sunanda Rao", "F"), ("Mr", "Farhan Qureshi", "M"),
          ("Ms", "Kavya Menon", "F"), ("Mr", "Gurdeep Singh Bhatia", "M"), ("Dr", "Anand Krishnan", "M"),
          ("Mrs", "Meera Deshpande", "F"), ("Mr", "Thomas Varghese", "M"), ("Mr", "Venkatesh Iyer", "M"),
          ("Ms", "Ritu Agarwal", "F"), ("Mr", "Prakash Jain", "M"), ("Mrs", "Lata Shetty", "F")]


class _Gen:
    def __init__(self, tenant_no: int):
        self.rnd = random.Random(SEED + tenant_no)
        self.borrowers, self.addresses, self.relations = [], [], []
        self.facilities, self.guarantors, self.securities, self.bounces = [], [], [], []
        self._b = self._f = self._r = 0

    # ---------------------------------------------------------------- identifiers
    def pan(self, holder: str) -> str:
        r = self.rnd
        return "".join(r.choice(LETTERS) for _ in range(3)) + holder + r.choice(LETTERS) + f"{r.randint(0, 9999):04d}" \
            + r.choice(LETTERS)

    def cin(self, listed: bool, state: str = "MH") -> str:
        r = self.rnd
        return f"{'L' if listed else 'U'}{r.randint(10000, 99999)}{state}{r.randint(1985, 2020)}" \
               f"{'PLC' if listed else 'PTC'}{r.randint(100000, 999999)}"

    def udyam(self, state: str = "MH") -> str:
        return f"UDYAM-{state}-{self.rnd.randint(10, 35):02d}-{self.rnd.randint(1000000, 9999999)}"

    def mobile(self) -> str:
        while True:
            n = self.rnd.choice("6789") + "".join(str(self.rnd.randint(0, 9)) for _ in range(9))
            if len(set(n)) > 3:
                return n

    def date(self, start: date, end: date) -> date:
        return start + timedelta(days=self.rnd.randint(0, (end - start).days))

    # ---------------------------------------------------------------- builders
    def borrower(self, name: str, constitution: str, *, ids: dict | None = None, category="SMALL", industry="MFG",
                 rating: tuple | None = None, city: tuple | None = None, addresses=("REG",), **over) -> dict:
        self._b += 1
        city = city or self.rnd.choice(CITIES)
        b = dict(customer_id=f"B{self._b:04d}", business_name=name,
                 short_name=None if constitution == "IND" else name.split()[0][:20],      # not for individuals
                 constitution=constitution, msme_category=category, industry=industry,
                 bsr_activity_1=self.rnd.choice(["10710", "46900", "62011", "25920", "47190"]), bsr_activity_2=None,
                 bsr_activity_3=None, hsn_code=None, incorporation_date=self.date(date(1990, 1, 1), date(2020, 12, 31)),
                 turnover=self.rnd.choice([4500000, 25000000, 180000000, 950000000]), turnover_fy=date(2026, 3, 31),
                 employees=self.rnd.choice([8, 25, 140, 900]), rating=None, rating_agency=None, rating_date=None,
                 rating_valid_till=None, pan=None, cin=None, tin=None, service_tax=None, udyam=None,
                 company_reg_no=None, ckyc=None)
        if ids is None:
            ids = {"pan": self.pan("C")}
        b.update(ids)
        if rating:
            b.update(rating=rating[0], rating_agency=rating[1], rating_date=date(2025, 11, 20),
                     rating_valid_till=date(2026, 11, 19))
        b.update(over)
        self.borrowers.append(b)
        for seq, kind in enumerate(addresses, 1):
            self.address(b["customer_id"], seq, kind, city if seq == 1 else self.rnd.choice(CITIES))
        return b

    def address(self, customer_id: str, seq: int, kind: str, city: tuple, **over) -> dict:
        a = dict(customer_id=customer_id, seq=seq, address_type=kind,
                 line1=f"{self.rnd.choice(['Unit', 'Plot', 'Gala', 'Shed'])} {self.rnd.randint(1, 250)}, "
                       f"{self.rnd.choice(['Industrial Estate', 'Trade Centre', 'Business Park', 'MIDC Area'])}",
                 line2=f"{self.rnd.randint(1, 90)}, {self.rnd.choice(['Ring Road', 'Station Road', 'Highway Road'])}",
                 line3=None, city=city[0], district=city[1], state=city[2],
                 pin=f"{city[3]}{self.rnd.randint(1, 99):03d}", country="IN", mobile=self.mobile(),
                 phone_area=city[4], phone=f"{self.rnd.randint(2000000, 2999999)}",
                 email=f"accounts{seq}@{customer_id.lower()}.example.in" if seq == 1 else None)
        a.update(over)
        self.addresses.append(a)
        return a

    def person(self, **over) -> dict:
        prefix, name, sex = self.rnd.choice(PEOPLE)
        city = self.rnd.choice(CITIES)
        p = dict(kind="IND_IN", name=name, prefix=prefix, gender=sex,
                 dob=self.date(date(1955, 1, 1), date(1990, 12, 31)), incorporation_date=None, pan=self.pan("P"),
                 voter_id=None, passport=None, dl=None, aadhaar=None, ration_card=None, cin=None, din=None, tin=None,
                 service_tax=None, ckyc=None, udyam=None, company_reg_no=None, line1=f"Flat {self.rnd.randint(1, 900)}, "
                 f"{self.rnd.choice(['Sai', 'Lotus', 'Royal'])} Residency", line2=None, line3=None, city=city[0],
                 district=city[1], state=city[2], pin=f"{city[3]}{self.rnd.randint(1, 99):03d}", country="IN",
                 mobile=self.mobile(), phone=None, phone_area=None)
        p.update(over)
        return p

    def company(self, name: str, **over) -> dict:
        city = self.rnd.choice(CITIES)
        c = dict(kind="CORP_IN", name=name, prefix=None, gender=None, dob=None,
                 incorporation_date=self.date(date(1980, 1, 1), date(2015, 12, 31)), pan=self.pan("C"),
                 voter_id=None, passport=None, dl=None, aadhaar=None, ration_card=None, cin=self.cin(False), din=None,
                 tin=None, service_tax=None, ckyc=None, udyam=None, company_reg_no=None, line1=f"{name}, Corporate Tower",
                 line2=f"{self.rnd.randint(1, 90)}, Business District", line3=None, city=city[0], district=city[1],
                 state=city[2], pin=f"{city[3]}{self.rnd.randint(1, 99):03d}", country="IN", mobile=None,
                 phone=f"{self.rnd.randint(2000000, 2999999)}", phone_area=city[4], category="LARGE", industry="MFG")
        c.update(over)
        return c

    def relation(self, borrower: dict, relation: str, party: dict, stake=None) -> None:
        self._r += 1
        self.relations.append(dict(customer_id=borrower["customer_id"], related_id=f"R{self._r:04d}",
                                   relation=relation, stake_pct=stake, **party))

    def facility(self, borrower: dict, product: str, *, no: int, expected="ACCEPT", rule="", desc="",
                 **over) -> dict:
        self._f += 1
        r = self.rnd
        sanction = r.choice([2500000, 7500000, 15000000, 40000000, 120000000])
        start = self.date(date(2017, 1, 1), date(2025, 12, 31))
        revolving = product in ("CC", "OD", "TOD", "CORPCARD")
        f = dict(facility_id=f"F{self._f:05d}", customer_id=borrower["customer_id"],
                 facility_number=f"BR{r.randint(11, 40)}{product}{r.randint(10**6, 10**7 - 1)}",
                 branch_code=f"BR{r.randint(11, 40)}", product=product, sanction_date=start, sanction_amount=sanction,
                 currency="INR", tenure_months=None if revolving else r.choice([12, 36, 60, 84]),
                 frequency="ROLLING" if revolving else "MONTHLY",
                 drawing_power=round(sanction * 0.9) if revolving else None,
                 outstanding=round(sanction * r.uniform(0.3, 0.85), 2),
                 maturity_date=None if revolving else date(start.year + 5, start.month, min(start.day, 28)),
                 renewal_date=date(2026, 3, 31) if revolving else None, dpd=0, asset_class="STD",
                 asset_class_date=None, overdue=0, bucket_1=None, bucket_2=None, bucket_3=None, bucket_4=None,
                 bucket_5=None, high_credit=round(sanction * 0.95) if revolving else None,
                 instalment=None if revolving else round(sanction / 50), last_paid=round(sanction / 50),
                 last_paid_date=AS_OF - timedelta(days=r.randint(2, 25)), status=None, status_date=None,
                 closed_date=None, written_off=None, settled=None, restructure_reason=None, security_cover="FULL",
                 guarantee_cover="NIL", remark=None, wilful_date=None, suit_status="NONE", suit_ref=None,
                 suit_amount=None, suit_date=None, test_scenario_number=no, test_expected=expected,
                 test_rule_reference=rule, test_description=desc)
        f.update(over)
        self.facilities.append(f)
        return f

    def guarantor(self, facility: dict, party: dict, invoked: date | None = None) -> None:
        self.guarantors.append(dict(facility_id=facility["facility_id"], guarantor_id=f"G{len(self.guarantors) + 1:04d}",
                                    invocation_date=invoked, **{k: v for k, v in party.items()
                                                                if k not in ("category", "industry")},
                                    category=party.get("category"), industry=party.get("industry")))

    def security(self, facility: dict, sec_type: str, charge: str, value=None, currency="INR") -> None:
        self.securities.append(dict(facility_id=facility["facility_id"], seq=len(self.securities) + 1,
                                    value=value or round(facility["sanction_amount"] * 1.3), currency=currency,
                                    sec_type=sec_type, charge=charge, valuation_date=date(2026, 4, 1)))

    def bounce(self, facility: dict, times: int = 1, reason: str = "INSUFF") -> None:
        self.bounces.append(dict(facility_id=facility["facility_id"], seq=len(self.bounces) + 1,
                                 bounce_date=date(2026, 8, 7), amount=self.rnd.choice([85000, 240000]),
                                 cheque_no=f"{self.rnd.randint(100000, 999999)}", times=times,
                                 cheque_date=date(2026, 8, 1) if times == 1 else None, reason=reason))


def build(tenant_no: int) -> _Gen:
    g = _Gen(tenant_no)
    # ---------- positive coverage
    b1 = g.borrower("Shree Ganesh Polymers Private Limited", "PVT", category="MEDIUM", industry="MFG",
                    ids={"pan": g.pan("C"), "cin": g.cin(False), "udyam": g.udyam()},
                    rating=("BBB+", "CRISIL"), addresses=("REG", "PLANT"), hsn_code="390110")
    g.relation(b1, "PROMOTER_DIR", g.person(din=f"{g.rnd.randint(10**7, 10**8 - 1)}"), stake=6200)
    g.relation(b1, "INDEP_DIR", g.person(din=f"{g.rnd.randint(10**7, 10**8 - 1)}"))
    f1 = g.facility(b1, "CC", no=1, desc="Pvt Ltd manufacturer, cash credit with drawing power and renewal")
    g.security(f1, "STOCK", "PRIMARY_1")
    g.security(f1, "LAND", "COLLATERAL_1")

    b2 = g.borrower("Lakshmi Traders", "PROP", category="MICRO", industry="TRD",
                    ids={"pan": g.pan("P"), "udyam": g.udyam("TN")})
    owner = g.person()
    g.relation(b2, "PROPRIETOR", owner, stake=10000)
    f2 = g.facility(b2, "TL_LONG", no=2, desc="Proprietorship, long term loan, proprietor as personal guarantor")
    g.guarantor(f2, owner)

    b3 = g.borrower("Kaveri Logistics Services", "PART", category="SMALL", industry="SVC",
                    ids={"pan": g.pan("F")})
    g.relation(b3, "PARTNER", g.person(), stake=5000)
    g.relation(b3, "PARTNER", g.person(), stake=5000)
    f3 = g.facility(b3, "OD", no=3, desc="Partnership, overdraft, one inward cheque dishonoured")
    g.bounce(f3)

    b4 = g.borrower("Deccan Infra Projects Limited", "PUB", category="LARGE", industry="SVC",
                    ids={"pan": g.pan("C"), "cin": g.cin(True)}, rating=("AA-", "ICRA"))
    g.relation(b4, "HOLDING", g.company("Deccan Holdings Limited"), stake=7400)
    g.relation(b4, "SHAREHOLDER", g.company("Bharat Growth Fund Private Limited"), stake=1800)
    g.facility(b4, "BG", no=4, desc="Public Ltd, bank guarantee (non-fund based)")
    f4b = g.facility(b4, "LC", no=4, currency="USD", sanction_amount=1500000, outstanding=58000000.0,
                     desc="Letter of credit sanctioned in USD, balance in INR")
    g.security(f4b, "DEPOSIT", "PRIMARY_1", value=2000000, currency="USD")

    b5 = g.borrower("Ramnath Agarwal HUF", "HUF", category="MICRO", industry="TRD", ids={"pan": g.pan("H")})
    g.relation(b5, "KARTA", g.person(name="Ramnath Agarwal", prefix="Mr", gender="M"))
    g.facility(b5, "WCL", no=5, desc="HUF, working capital loan, Karta")

    b6 = g.borrower("Sahyadri Agro Foods Private Limited", "PVT", category="SMALL", industry="AGRI",
                    ids={"pan": g.pan("C"), "cin": g.cin(False)})
    g.facility(b6, "FACT_NR", no=6, frequency="BULLET",
               desc="Factoring without recourse (buyer): relationship segment not required")

    b7 = g.borrower("Orbit Textiles Private Limited", "PVT", category="MEDIUM", industry="MFG",
                    ids={"pan": g.pan("C"), "cin": g.cin(False)})
    g.relation(b7, "PROMOTER_DIR", g.person(din=f"{g.rnd.randint(10**7, 10**8 - 1)}"), stake=8000)
    g.facility(b7, "TL_LONG", no=7, status="WO", status_date=date(2025, 12, 31), dpd=430, asset_class="LOSS",
               asset_class_date=date(2024, 9, 1), overdue=8400000, bucket_4=1200000, bucket_5=7200000,
               written_off=9100000, wilful_date=date(2025, 6, 30), suit_status="DECREE",
               suit_ref="CS(COMM) 412/2025", suit_amount=9800000, suit_date=date(2025, 8, 14),
               desc="Written off, wilful defaulter, suit decreed, overdue buckets")

    b8 = g.borrower("Nilgiri Hospitality LLP", "PART", category="SMALL", industry="SVC", ids={"pan": g.pan("F")})
    g.relation(b8, "PARTNER", g.person(), stake=6000)
    g.facility(b8, "TL_MED", no=8, closed_date=date(2026, 7, 15), outstanding=0, status_date=date(2026, 7, 15),
               desc="Term loan closed by payment")

    b9 = g.borrower("Arvind Kulkarni", "IND", category="RETAIL", industry="OTH",
                    ids={"pan": g.pan("P"), "ckyc": f"{g.rnd.randint(10**13, 10**14 - 1)}"})
    g.relation(b9, "OTHERS", g.person(name="Arvind Kulkarni", prefix="Mr", gender="M"))
    f9 = g.facility(b9, "CVL", no=9, guarantee_cover="FULL",
                    desc="Individual borrower (constitution 90) guaranteed by a company (cross-reporting)")
    g.guarantor(f9, g.company("Sample Logistics Private Limited", category="SMALL", industry="SVC"))

    b10 = g.borrower("Sri Venkateswara Educational Trust", "TRUST", category="OTHERS", industry="SVC",
                     ids={"pan": g.pan("T")})
    g.relation(b10, "TRUSTEE", g.person())
    g.facility(b10, "DL", no=10, desc="Trust, demand loan, trustee")

    b11 = g.borrower("Precision Auto Components Private Limited", "PVT", category="SMALL", industry="MFG",
                     ids={"pan": g.pan("C"), "cin": g.cin(False), "udyam": g.udyam()})
    g.relation(b11, "PROMOTER_DIR", g.person(din=f"{g.rnd.randint(10**7, 10**8 - 1)}"), stake=10000)
    f11 = g.facility(b11, "EQP", no=11, dpd=45, asset_class="SMA1", overdue=310000, bucket_1=110000,
                     bucket_2=200000, desc="Equipment finance, SMA-1, DPD 45 with overdue buckets")
    g.security(f11, "PLANT", "PRIMARY_1")

    b12 = g.borrower("Indo Pacific Electronics Private Limited", "PVT", category="MEDIUM", industry="IMP",
                     ids={"pan": g.pan("C"), "cin": g.cin(False)}, addresses=("REG", "WH"))
    g.relation(b12, "HOLDING", g.company("Pacific Electronics Pte Ltd", kind="CORP_FOREIGN", pan=None, cin=None,
                                         line1="10 Anson Road", line2="International Plaza", city="Singapore",
                                         district=None, state="Foreign", pin="079903", country="SG"), stake=5100)
    g.facility(b12, "PCL", no=12, desc="Importer, packing credit, foreign holding company (Singapore)")

    b13 = g.borrower("Kisan Sahakari Dugdh Utpadak Sangh", "COOP", category="SMALL", industry="AGRI",
                     ids={"pan": g.pan("A"), "company_reg_no": "COOP/PUN/2004/118"})
    g.relation(b13, "SHAREHOLDER", g.person())
    g.facility(b13, "MUDRA_WC", no=13, desc="Co-operative society, Mudra working capital")

    # ---------- negative coverage
    b14 = g.borrower("Apex Enterprises", "PROP", category="MICRO", industry="TRD", ids={})
    g.relation(b14, "PROPRIETOR", g.person())
    g.facility(b14, "TL_MED", no=14, expected="REJECT_RECORD", rule="CUCRF.REC.NO_IDENTIFIER",
               desc="Borrower with no identifier at all")

    b15 = g.borrower("Vishal Hardware Stores", "PROP", category="MICRO", industry="TRD", ids={"pan": g.pan("P")})
    g.relation(b15, "PROMOTER_DIR", g.person())
    g.facility(b15, "OD", no=15, expected="REJECT_RECORD", rule="CUCRF.RS.NOT_FOR_CONSTITUTION",
               desc="Proprietorship whose only relationship is a promoter director (not permitted for "
                    "constitution 30): RS rejected, so no relationship remains")

    b16 = g.borrower("Metro Builders Private Limited", "PVT", category="SMALL", industry="SVC",
                     ids={"pan": g.pan("C"), "cin": "U45200MH2011"})
    g.relation(b16, "PROMOTER_DIR", g.person(din=f"{g.rnd.randint(10**7, 10**8 - 1)}"))
    g.facility(b16, "TL_LONG", no=16, expected="ACCEPT", rule="CUCRF.BS.ID_FORMAT",
               desc="CIN shorter than 21 characters: CIN left out, PAN still valid")

    b17 = g.borrower("Coastal Seafoods Exports Private Limited", "PVT", category="SMALL", industry="EXP",
                     ids={"pan": g.pan("C"), "cin": g.cin(False)})
    g.relation(b17, "PROMOTER_DIR", g.person(din=f"{g.rnd.randint(10**7, 10**8 - 1)}"))
    f17 = g.facility(b17, "EBD", no=17, expected="ACCEPT", rule="CUCRF.REQUIRED.security.security_classification",
                     desc="Security without a charge classification: SS left out, facility reported")
    g.security(f17, "RECEIVABLES", None)
    return g


# ------------------------------------------------------------------ source tables
def _amount(name: str) -> Column:
    return Column(name, Numeric(20, 2))


def _party_columns() -> list[Column]:
    """Columns shared by business_relationship and facility_guarantor."""
    return [Column("kind", String(15)), Column("name", String(150)), Column("prefix", String(15)),
            Column("gender", String(2)), Column("dob", Date), Column("incorporation_date", Date),
            Column("pan", String(20)), Column("voter_id", String(30)), Column("passport", String(30)),
            Column("dl", String(30)), Column("aadhaar", String(30)), Column("ration_card", String(30)),
            Column("cin", String(30)), Column("din", String(12)), Column("tin", String(30)),
            Column("service_tax", String(30)), Column("ckyc", String(30)), Column("udyam", String(30)),
            Column("company_reg_no", String(30)), Column("category", String(10)), Column("industry", String(10)),
            Column("line1", String(150)), Column("line2", String(150)), Column("line3", String(150)),
            Column("city", String(40)), Column("district", String(40)), Column("state", String(40)),
            Column("pin", String(10)), Column("country", String(2)), Column("mobile", String(60)),
            Column("phone", String(60)), Column("phone_area", String(6))]


def source_tables(md: MetaData) -> dict[str, Table]:
    return {
        "business_borrower": Table(
            "business_borrower", md, Column("customer_id", String(20), primary_key=True),
            Column("business_name", String(150)), Column("short_name", String(20)), Column("constitution", String(10)),
            Column("msme_category", String(10)), Column("industry", String(10)), Column("bsr_activity_1", String(5)),
            Column("bsr_activity_2", String(5)), Column("bsr_activity_3", String(5)), Column("hsn_code", String(20)),
            Column("incorporation_date", Date), _amount("turnover"), Column("turnover_fy", Date),
            Column("employees", Integer), Column("rating", String(10)), Column("rating_agency", String(20)),
            Column("rating_date", Date), Column("rating_valid_till", Date), Column("pan", String(20)),
            Column("cin", String(30)), Column("tin", String(30)), Column("service_tax", String(30)),
            Column("udyam", String(30)), Column("company_reg_no", String(30)), Column("ckyc", String(30))),
        "business_address": Table(
            "business_address", md, Column("customer_id", String(20)), Column("seq", Integer),
            Column("address_type", String(10)), Column("line1", String(150)), Column("line2", String(150)),
            Column("line3", String(150)), Column("city", String(40)), Column("district", String(40)),
            Column("state", String(40)), Column("pin", String(10)), Column("country", String(2)),
            Column("mobile", String(60)), Column("phone_area", String(6)), Column("phone", String(60)),
            Column("email", String(100)), PrimaryKeyConstraint("customer_id", "seq")),
        "business_relationship": Table(
            "business_relationship", md, Column("customer_id", String(20)), Column("related_id", String(20)),
            Column("relation", String(20)), Column("stake_pct", Integer), *_party_columns(),
            PrimaryKeyConstraint("customer_id", "related_id")),
        "business_facility": Table(
            "business_facility", md, Column("facility_id", String(20), primary_key=True),
            Column("customer_id", String(20)), Column("facility_number", String(30)), Column("branch_code", String(10)),
            Column("product", String(20)), Column("sanction_date", Date), _amount("sanction_amount"),
            Column("currency", String(3)), Column("tenure_months", Integer), Column("frequency", String(20)),
            _amount("drawing_power"), _amount("outstanding"), Column("maturity_date", Date),
            Column("renewal_date", Date), Column("dpd", Integer), Column("asset_class", String(10)),
            Column("asset_class_date", Date), _amount("overdue"), _amount("bucket_1"), _amount("bucket_2"),
            _amount("bucket_3"), _amount("bucket_4"), _amount("bucket_5"), _amount("high_credit"),
            _amount("instalment"), _amount("last_paid"), Column("last_paid_date", Date), Column("status", String(20)),
            Column("status_date", Date), Column("closed_date", Date), _amount("written_off"), _amount("settled"),
            Column("restructure_reason", String(20)), Column("security_cover", String(10)),
            Column("guarantee_cover", String(10)), Column("remark", String(100)), Column("wilful_date", Date),
            Column("suit_status", String(20)), Column("suit_ref", String(25)), _amount("suit_amount"),
            Column("suit_date", Date), Column("test_scenario_number", Integer), Column("test_expected", String(30)),
            Column("test_rule_reference", String(60)), Column("test_description", String(255))),
        "facility_guarantor": Table(
            "facility_guarantor", md, Column("facility_id", String(20)), Column("guarantor_id", String(20)),
            Column("invocation_date", Date), *_party_columns(), PrimaryKeyConstraint("facility_id", "guarantor_id")),
        "facility_security": Table(
            "facility_security", md, Column("facility_id", String(20)), Column("seq", Integer), _amount("value"),
            Column("currency", String(3)), Column("sec_type", String(20)), Column("charge", String(20)),
            Column("valuation_date", Date), PrimaryKeyConstraint("facility_id", "seq")),
        "facility_cheque_bounce": Table(
            "facility_cheque_bounce", md, Column("facility_id", String(20)), Column("seq", Integer),
            Column("bounce_date", Date), _amount("amount"), Column("cheque_no", String(30)), Column("times", Integer),
            Column("cheque_date", Date), Column("reason", String(10)), PrimaryKeyConstraint("facility_id", "seq")),
    }


def rows(tenant_no: int) -> dict[str, list[dict]]:
    g = build(tenant_no)
    return {"business_borrower": g.borrowers, "business_address": g.addresses, "business_relationship": g.relations,
            "business_facility": g.facilities, "facility_guarantor": g.guarantors, "facility_security": g.securities,
            "facility_cheque_bounce": g.bounces}
