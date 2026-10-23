"""JSON API: request flow (draft -> exceptions -> submit -> validate -> confirm -> files), tracker and files, findings
actions, rules & policies, audit, dispatch, and SSO identity."""

import base64
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from mock_data.generate_mock_data import load_into
from submissions.adjustments import AdjustmentRepository, AdjustmentScope
from submissions.bureaus.seed import seed as seed_bureaus
from submissions.enums import BureauCode as B, ExtractStrategy, Outcome, RequestStatus as S, RunMode as M
from submissions.enums import SubmissionType as T
from submissions.ops.tables import audit_event
from submissions.pipeline import Services
from submissions.requests import RequestResult
from submissions.snapshot import SnapshotRepository
from submissions.storage import LocalFileStore
from submissions.users import UserRepository
from submissions.validation import rules
from submissions.worker.runner import Worker

ROOT = Path(__file__).resolve().parent.parent
AS_OF = date(2026, 9, 30)
JOINT_LOAN, CLEAN_LOAN = "B122HL10788234", "B107PL79230310"


def actions(engine) -> list[str]:
    with engine.connect() as conn:
        return list(conn.execute(select(audit_event.c.action).order_by(audit_event.c.event_id)).scalars())


@pytest.fixture
def worker(engine, lms_engine, requests_repo, tenant_repo, bureau_repo, tmp_path):
    seed_bureaus(bureau_repo, ["nbfc_001", "nbfc_002"])
    services = Services(app_engine=engine, source_engine=lms_engine, snapshots=SnapshotRepository(engine),
                        base_dir=ROOT, store=LocalFileStore(tmp_path))
    return Worker(services, requests_repo, tenant_repo, bureau_repo, worker_id="w-api")


@pytest.fixture
def api(make_api, tmp_path):
    return make_api(store=LocalFileStore(tmp_path))


def new_request(api, submit=True, **fields) -> tuple[int, dict]:
    body = {"tenant_id": "nbfc_001", "as_of_date": "2026-09-30", "submission_types": ["CONSUMER"],
            "reporting_cycle": "ME"} | fields
    status, data = api.post("/requests", **body)
    if submit and status == 201:
        api.post(f"/batches/{data['batch_id']}/submit")
    return status, data


# ---------------------------------------------------------------- meta, health
def test_meta_lists_choices(api):
    status, meta = api.get("/meta")
    assert status == 200 and {t["tenant_id"] for t in meta["tenants"]} == {"nbfc_001", "nbfc_002"}
    types = {t["value"]: t["enabled"] for t in meta["submission_types"]}
    assert types == {"CONSUMER": True, "COMMERCIAL": False, "NESL": False}
    assert {o["value"] for o in meta["override_fields"]} >= {"days_past_due", "settlement_amount"}
    assert meta["default_as_of"].endswith(("-28", "-29", "-30", "-31"))


def test_health_reports_waiting_requests(api, requests_repo, clock):
    assert api.get("/health")[1] == {"oldest_pending_at": None, "waiting_seconds": None, "slow": False}
    requests_repo.create_batch("nbfc_001", AS_OF, M.VALIDATE, [T.CONSUMER])
    health = api.get("/health")[1]
    assert health["oldest_pending_at"].startswith("2026-10-21T09:00:00") and health["slow"] is True


def test_unknown_tenant_and_routes(api):
    assert api.get("/batches", tenant="nbfc_999") == (400, {"error": "Unknown NBFC nbfc_999"})
    assert api.get("/batches/nope")[0] == 404
    assert api.get("/snapshots/999/findings")[0] == 404
    assert api.get("/requests/999/file")[0] == 404
    assert api.get("/nothing-here")[0] == 404


# ---------------------------------------------------------------- creating requests
def test_new_request_is_a_draft_until_submitted(api, requests_repo, worker, dispatcher):
    status, data = new_request(api, submit=False)
    assert status == 201 and "Add any exclusions" in data["message"]
    (row,) = requests_repo.list_batch(data["batch_id"])
    assert (row.status, row.run_mode, row.bureau_code, row.requested_by) == (S.DRAFT, M.VALIDATE, None, "internal-user")
    assert dispatcher.dispatched == [] and worker.run_once() == 0           # not validated until submitted
    assert [d["batch_id"] for d in api.get("/exceptions")[1]["drafts"]] == [data["batch_id"]]
    api.post(f"/batches/{data['batch_id']}/submit")
    assert dispatcher.dispatched == [row.request_id]                        # started on submit
    assert requests_repo.get(row.request_id).status is S.PENDING


def test_new_request_is_always_a_validation(api, requests_repo):
    _, data = new_request(api, run_mode="GENERATE", bureau_codes=["CIBIL"])    # ignored if posted anyway
    assert [(r.run_mode, r.bureau_code) for r in requests_repo.list_batch(data["batch_id"])] == [(M.VALIDATE, None)]


def test_user_header_is_recorded_without_sign_in(api, requests_repo):
    status, data = api.post("/requests", headers={"X-Forwarded-User": "ops.priya"}, tenant_id="nbfc_002",
                            as_of_date="2026-09-30", submission_types=["CONSUMER"])
    assert requests_repo.list_batch(data["batch_id"])[0].requested_by == "ops.priya"


@pytest.mark.parametrize("fields,message", [
    (dict(tenant_id="nbfc_999"), "Select an active NBFC"),
    (dict(as_of_date="2099-01-01"), "future"),
    (dict(as_of_date="not-a-date"), "YYYY-MM-DD"),
    (dict(submission_types=["NESL"]), "Not available yet"),
    (dict(submission_types=[]), "at least one submission type"),
])
def test_invalid_requests_are_refused(api, fields, message):
    status, data = new_request(api, **fields)
    assert status == 400 and message in data["error"]


def test_duplicate_request_rejected(api):
    new_request(api)
    status, data = new_request(api)
    assert status == 400 and "Already open (draft, pending or running)" in data["error"]


# ---------------------------------------------------------------- after the worker ran
def test_batch_findings_and_csv_after_validation(api, worker):
    _, data = new_request(api)
    worker.run_once()
    _, batch = api.get(f"/batches/{data['batch_id']}")
    (row,) = batch["rows"]
    assert row["status"] == "SUCCEEDED" and batch["active"] is False
    (snap,) = batch["snapshots"]
    assert snap["records"] == {"ACCEPTED": 48, "REJECTED": 8} and snap["snapshot"]["status"] == "VALIDATED"
    assert batch["generate_from"][0]["request_id"] == row["request_id"]
    assert set(batch["generate_from"][0]["bureaus"]) == {"CIBIL", "CRIF_HIGHMARK", "EQUIFAX", "EXPERIAN"}
    sid = row["snapshot_id"]

    _, findings = api.get(f"/snapshots/{sid}/findings", rule_id="UCRF.TL.CLOSED_WITH_BALANCE")
    assert findings["total"] == 1 and findings["findings"][0]["account_key"].endswith("L00047")
    csv_resp = api.raw(f"/snapshots/{sid}/findings.csv", outcome="REJECT_RECORD")
    lines = csv_resp.get_data(as_text=True).strip().splitlines()
    assert csv_resp.mimetype == "text/csv" and lines[0].startswith("rule_id,outcome")
    assert len(lines) - 1 == 9 and all(",REJECT_RECORD," in line for line in lines[1:])


def test_findings_csv_export_goes_to_s3_on_aws(make_api, worker):
    class FakeExports:
        def __init__(self):
            self.puts = []

        def put_object(self, **kw):
            self.puts.append(kw)

        def generate_presigned_url(self, method, *, Params, ExpiresIn):
            return f"https://jobs.s3/{Params['Key']}"

    client = FakeExports()
    from submissions.api import create_app
    from submissions.config import Settings
    plain = make_api()
    _, data = new_request(plain)
    worker.run_once()
    sid = plain.get(f"/batches/{data['batch_id']}")[1]["rows"][0]["snapshot_id"]
    app = create_app(Settings("sqlite://", "sqlite://", Path("."), jobs_bucket="jobs"),
                     engine=worker.services.app_engine, exports=(client, "jobs"))
    resp = app.test_client().get(f"/api/snapshots/{sid}/findings.csv")
    link = resp.get_json()
    assert link["url"].startswith("https://jobs.s3/exports/") and link["file_name"].startswith("findings-nbfc_001")
    assert client.puts[0]["Body"].startswith(b"rule_id,outcome") and client.puts[0]["Bucket"] == "jobs"


def test_generate_from_validation_reuses_snapshot_and_dispatches(api, worker, requests_repo, dispatcher):
    _, data = new_request(api)
    worker.run_once()
    (validated,) = requests_repo.list_batch(data["batch_id"])
    status, gen = api.post(f"/batches/{data['batch_id']}/generate", request_id=validated.request_id,
                           bureau_codes=["CIBIL", "EXPERIAN"])
    rows = requests_repo.list_batch(gen["batch_id"])
    assert status == 201 and len(rows) == 2
    assert all(r.run_mode is M.GENERATE and r.snapshot_id == validated.snapshot_id for r in rows)
    assert dispatcher.dispatched[-2:] == [r.request_id for r in rows]


def test_generate_needs_bureaus_and_profiles(api, engine, worker, requests_repo):
    from submissions.bureaus.tables import bureau_profile
    _, data = new_request(api)
    worker.run_once()
    (validated,) = requests_repo.list_batch(data["batch_id"])
    path = f"/batches/{data['batch_id']}/generate"
    assert "at least one bureau" in api.post(path, request_id=validated.request_id, bureau_codes=[])[1]["error"]
    with engine.begin() as conn:
        conn.execute(bureau_profile.delete().where(bureau_profile.c.bureau_code == "EXPERIAN"))
    status, err = api.post(path, request_id=validated.request_id, bureau_codes=["EXPERIAN"])
    assert status == 400 and "No active bureau profile" in err["error"]
    assert api.post(path, request_id="x", bureau_codes=["CIBIL"])[0] == 400


def test_cancel_and_retry_dispatches_again(api, requests_repo, dispatcher):
    _, data = new_request(api)
    pending = requests_repo.list_batch(data["batch_id"])[0]
    assert api.post(f"/requests/{pending.request_id}/cancel")[0] == 200
    assert requests_repo.get(pending.request_id).status is S.CANCELLED
    assert api.post(f"/requests/{pending.request_id}/cancel")[0] == 409               # not cancellable twice
    api.post(f"/requests/{pending.request_id}/retry")
    assert requests_repo.get(pending.request_id).status is S.PENDING
    assert dispatcher.dispatched == [pending.request_id, pending.request_id]


def test_dispatch_failure_does_not_lose_the_request(make_api, requests_repo):
    from submissions.api import create_app
    from submissions.config import Settings

    class Broken:
        def dispatch(self, requests):
            list(requests)
            raise RuntimeError("S3 unavailable")

    app = create_app(Settings("sqlite://", "sqlite://", Path(".")), engine=requests_repo.engine, dispatcher=Broken())
    client = app.test_client()
    batch_id = client.post("/api/requests", json={"tenant_id": "nbfc_001", "as_of_date": "2026-09-30",
                                                  "submission_types": ["CONSUMER"]}).get_json()["batch_id"]
    assert client.post(f"/api/batches/{batch_id}/submit").status_code == 200    # saved; recovery re-dispatches
    assert requests_repo.list_batch(batch_id)[0].status is S.PENDING


def test_download_streams_local_files_only_inside_the_store(api, requests_repo, tmp_path):
    requests_repo.create_batch("nbfc_001", AS_OF, M.GENERATE, ["CONSUMER"], ["CIBIL", "EQUIFAX"], snapshot_id=1)
    outside, inside = tmp_path.parent / "secret.txt", tmp_path / "CIB0000001-01102026-090000.txt"
    outside.write_text("nope")
    inside.write_text("HDR")
    bad = requests_repo.claim_next("w")
    requests_repo.mark_succeeded(bad.request_id, RequestResult(output_file_path=str(outside)))
    assert api.get(f"/requests/{bad.request_id}/file")[0] == 404
    good = requests_repo.claim_next("w")
    requests_repo.mark_succeeded(good.request_id, RequestResult(output_file_name=inside.name,
                                                                output_file_path=str(inside)))
    resp = api.raw(f"/requests/{good.request_id}/file")
    assert resp.status_code == 200 and resp.get_data() == b"HDR"
    assert inside.name in resp.headers["Content-Disposition"]


# ---------------------------------------------------------------- tracker, files, findings actions, audit
@pytest.fixture
def validated(worker, requests_repo):
    """A validated nbfc_001 request with CIBIL and Experian files."""
    v = requests_repo.create_batch("nbfc_001", AS_OF, M.VALIDATE, [T.CONSUMER])
    worker.run_once()
    row = requests_repo.list_batch(v)[0]
    g = requests_repo.create_batch("nbfc_001", AS_OF, M.GENERATE, [T.CONSUMER], [B.CIBIL, B.EXPERIAN],
                                   snapshot_id=row.snapshot_id)
    worker.run_once()
    return row, g


def test_files_lists_generated_files(api, validated):
    _, g = validated
    _, files = api.get("/files")
    assert files["total"] == 2 and {f["batch_id"] for f in files["files"]} == {g}
    assert all(f["has_file"] and f["output_file_name"] for f in files["files"])
    assert api.get("/files", bureau="CIBIL")[1]["total"] == 1
    assert api.get("/files", bureau="NOPE")[0] == 400


def test_tracker_filters_and_paging(api, validated):
    row, g = validated
    def ids(**q):
        return [b["batch_id"] for b in api.get("/batches", **q)[1]["batches"]]
    assert row.batch_id in ids(mode="VALIDATE") and row.batch_id not in ids(mode="GENERATE")
    assert ids(bureau="EXPERIAN", status="SUCCEEDED") == [g]
    assert ids(status="FAILED") == [] and ids(**{"from": "2030-01-01"}) == []
    assert api.get("/batches", **{"from": "not-a-date"})[0] == 400
    assert api.get("/batches", tenant="nbfc_002")[1]["total"] == 0


def test_exclude_from_findings_goes_into_one_draft(api, validated, engine, requests_repo):
    row, _ = validated
    _, findings = api.get(f"/snapshots/{row.snapshot_id}/findings")
    keys = list(dict.fromkeys(f["account_key"] for f in findings["findings"] if f["account_key"]))
    for key in keys[:2] + keys[:1]:                                      # the third is a duplicate
        status, data = api.post(f"/snapshots/{row.snapshot_id}/exclude", account_key=key)
        assert status == 200
    drafts = [b for b in requests_repo.list_batches() if b.status.value == "DRAFT"]
    assert len(drafts) == 1 and data["batch_id"] == drafts[0].batch_id    # one draft collects them
    (draft_row,) = requests_repo.list_batch(drafts[0].batch_id)
    adjustments = AdjustmentRepository(engine).list(AdjustmentScope.of(draft_row))
    assert len(adjustments) == 2 and all(a.reason.startswith("From findings") for a in adjustments)


def loan_key(api, snapshot_id) -> str:
    return next(f["account_key"] for f in api.get(f"/snapshots/{snapshot_id}/findings")[1]["findings"]
                if f["account_key"])


def test_override_from_findings_returns_the_draft_to_prefill(api, validated):
    row, _ = validated
    key = loan_key(api, row.snapshot_id)
    status, data = api.post(f"/snapshots/{row.snapshot_id}/override", account_key=key, field="amount_overdue")
    assert status == 200 and data["type"] == "CONSUMER" and data["field"] == "amount_overdue" and data["account"]
    assert api.get(f"/batches/{data['batch_id']}/exceptions")[1]["is_draft"] is True


def test_findings_actions_blocked_while_a_run_is_open(api, validated, requests_repo):
    row, _ = validated
    requests_repo.create_batch("nbfc_001", AS_OF, M.VALIDATE, [T.CONSUMER])          # pending, not a draft
    key = loan_key(api, row.snapshot_id)
    status, err = api.post(f"/snapshots/{row.snapshot_id}/exclude", account_key=key)
    assert status == 409 and "Cannot open a new request" in err["error"]
    assert api.post(f"/snapshots/{row.snapshot_id}/exclude", account_key="NOPE")[0] == 404


def test_audit_filters(api, engine):
    from submissions.ops import audit
    audit.record(engine, "alice", "ADJUSTMENT_ADDED", tenant_id="nbfc_001", target="b-1")
    audit.record(engine, "bob", "FILE_DOWNLOADED", tenant_id="nbfc_001", target="7")
    def who(**q):
        return [e["actor"] for e in api.get("/audit", **q)[1]["events"]]
    assert who(actor="alice") == ["alice"] and who(action="FILE_DOWNLOADED") == ["bob"]
    assert [e["target"] for e in api.get("/audit", target="b-1")[1]["events"]] == ["b-1"]
    assert set(api.get("/audit")[1]["actors"]) == {"alice", "bob"}


# ---------------------------------------------------------------- exceptions step (LMS schema on the app server)
@pytest.fixture
def same_server(engine, bureau_repo, tenant_repo, requests_repo, tmp_path):
    """nbfc_001's LMS schema on the app server (adjustments are joined in SQL) and a worker reading it."""
    load_into(engine, ["nbfc_001"])
    tenant_repo.upsert(replace(tenant_repo.get("nbfc_001"), extract_strategy=ExtractStrategy.INSERT_SELECT))
    seed_bureaus(bureau_repo, ["nbfc_001"])
    services = Services(app_engine=engine, source_engine=engine, snapshots=SnapshotRepository(engine),
                        base_dir=ROOT, store=LocalFileStore(tmp_path))
    return Worker(services, requests_repo, tenant_repo, bureau_repo, worker_id="w-exc")


def statuses(api, batch_id, **q) -> list[str]:
    return [a["status"] for a in api.get(f"/batches/{batch_id}/exceptions", **q)[1]["adjustments"]]


def test_capture_and_remove(api, same_server, engine):
    _, data = new_request(api, submit=False)
    base = f"/batches/{data['batch_id']}/exceptions"
    api.post(f"{base}/exclude", kind="account", keys=f"{JOINT_LOAN}\nX-1, X-2", reason="disputed")
    assert "Already excluded: X-1" in api.post(f"{base}/exclude", kind="account", keys="X-1")[1]["message"]
    api.post(f"{base}/exclude", kind="customer", keys="C00001")
    status, err = api.post(f"{base}/override", account_number=CLEAN_LOAN, field="days_past_due", value="4.5")
    assert status == 400 and "whole number" in err["error"]
    api.post(f"{base}/override", account_number=CLEAN_LOAN, field="days_past_due", value="45", reason="late")
    _, page = api.get(base)
    assert [a["status"] for a in page["adjustments"]] == ["WILL_APPLY"] * 5
    assert {a["kind"] for a in page["adjustments"]} == {"EXCLUDE_ACCOUNT", "EXCLUDE_CUSTOMER", "OVERRIDE"}
    removed = page["adjustments"][0]["adjustment_id"]
    api.post(f"{base}/{removed}/remove")
    assert statuses(api, data["batch_id"]) == ["WILL_APPLY"] * 4
    assert "REMOVED" in statuses(api, data["batch_id"], history=1)
    assert actions(engine) == ["RUN_CREATED"] + ["ADJUSTMENT_ADDED"] * 3 + ["ADJUSTMENT_REMOVED"]


def test_submit_validate_confirm_generate(api, same_server, engine, requests_repo, tmp_path):
    _, data = new_request(api, submit=False)
    batch_id, base = data["batch_id"], f"/batches/{data['batch_id']}/exceptions"
    api.post(f"{base}/exclude", kind="account", keys=f"{JOINT_LOAN}\nNO-SUCH-LOAN")
    api.post(f"{base}/override", account_number=CLEAN_LOAN, field="amount_overdue", value="1500")
    api.post(f"/batches/{batch_id}/submit")
    same_server.run_once()
    (row,) = requests_repo.list_batch(batch_id)
    assert row.status is S.SUCCEEDED, row.error_message
    assert (row.total_records, row.excluded_accounts, row.overridden_accounts) == (54, 1, 1)   # validated the rest

    _, page = api.get(base)
    by_key = {a["key"]: a for a in page["adjustments"]}
    assert page["is_draft"] is False and by_key["NO-SUCH-LOAN"]["status"] == "NOT_FOUND"
    assert by_key[JOINT_LOAN]["status"] == "APPLIED" and by_key[CLEAN_LOAN]["status"] == "APPLIED"
    assert (by_key[CLEAN_LOAN]["old_value"], by_key[CLEAN_LOAN]["override_value"]) == ("0.00", "1500.00")
    status, err = api.post(f"{base}/exclude", kind="account", keys="X-9")
    assert status == 409 and "locked" in err["error"]

    adjusted = api.get(f"/batches/{batch_id}")[1]["snapshots"][0]["adjusted"]
    assert (adjusted["excluded_accounts"], adjusted["overridden_accounts"], adjusted["not_found"]) == (1, 1, 1)
    gen = dict(request_id=row.request_id, bureau_codes=["CIBIL"])
    status, err = api.post(f"/batches/{batch_id}/generate", **gen)
    assert status == 400 and "Confirm the excluded loans" in err["error"]
    _, ok = api.post(f"/batches/{batch_id}/generate", confirm_adjustments=True, **gen)
    same_server.run_once()
    (file_row,) = requests_repo.list_batch(ok["batch_id"])
    assert file_row.status is S.SUCCEEDED and file_row.excluded_accounts == 1
    csv_text = Path(file_row.exceptions_file_path).read_text()
    assert "# User adjustments applied" in csv_text and "NO-SUCH-LOAN" in csv_text and "1500.00" in csv_text
    assert {"RUN_SUBMITTED", "ADJUSTMENTS_CONFIRMED"} <= set(actions(engine))


def test_submit_without_exceptions_and_discard(api, same_server, requests_repo):
    _, data = new_request(api)
    same_server.run_once()
    (row,) = requests_repo.list_batch(data["batch_id"])
    assert row.status is S.SUCCEEDED and (row.total_records, row.excluded_accounts) == (56, 0)
    assert api.post(f"/batches/{data['batch_id']}/submit")[0] == 409            # not a draft any more

    _, other = new_request(api, submit=False)
    api.post(f"/batches/{other['batch_id']}/discard")
    assert requests_repo.list_batch(other["batch_id"])[0].status is S.CANCELLED
    assert new_request(api, submit=False)[0] == 201                                # the date is free again


# ---------------------------------------------------------------- rules & policies
RULE = "UCRF.ID.NUMBER_FORMAT"                 # default: on, REJECT_SEGMENT


def effective(engine, tenant="nbfc_001", rule_id=RULE):
    return next(r for r in rules.load_rule_set(engine, tenant, "CONSUMER") if r.rule_id == rule_id)


def test_rule_catalogue_without_an_nbfc(make_api):
    _, page = make_api().get("/rules", type="CONSUMER")
    rule = next(r for r in page["rules"] if r["rule_id"] == RULE)
    assert page["tenant_id"] is None and rule["message"].startswith("ID number is not valid")
    assert rule["sql"] or rule["python"]                                          # the logic is visible
    assert any(r["python"] for r in page["rules"]) and any(r["sql"] for r in page["rules"])
    assert make_api().post(f"/rules/{RULE}", type="CONSUMER", enabled=True, reason="r")[0] == 400   # needs an NBFC


def test_rule_change_needs_a_reason_and_is_per_nbfc(make_api, engine):
    api = make_api(tenant="nbfc_001")
    status, err = api.post(f"/rules/{RULE}", type="CONSUMER", enabled=True, outcome="WARN")
    assert status == 400 and "give a reason" in err["error"]
    assert effective(engine).outcome is Outcome.REJECT_SEGMENT
    api.post(f"/rules/{RULE}", type="CONSUMER", enabled=True, outcome="WARN", reason="NBFC holds legacy IDs")
    assert effective(engine).outcome is Outcome.WARN and effective(engine).enabled
    assert effective(engine, "nbfc_002").outcome is Outcome.REJECT_SEGMENT       # other NBFC untouched
    api.post(f"/rules/{RULE}", type="CONSUMER", enabled=False, outcome="WARN", reason="not used by this NBFC")
    assert not effective(engine).enabled
    changed = [r for r in api.get("/rules", type="CONSUMER")[1]["rules"] if r["changed"]]
    assert [r["rule_id"] for r in changed] == [RULE]
    with engine.connect() as conn:
        events = conn.execute(select(audit_event).where(audit_event.c.action == "RULE_POLICY_CHANGED")
                              .order_by(audit_event.c.event_id)).all()
    assert [e.target for e in events] == [RULE, RULE] and "legacy IDs" in events[0].details


def test_rule_back_to_default_and_reset(make_api, engine):
    api = make_api(tenant="nbfc_001")
    api.post(f"/rules/{RULE}", type="CONSUMER", enabled=True, outcome="WARN", reason="r")
    api.post(f"/rules/{RULE}", type="CONSUMER", enabled=True, outcome="REJECT_SEGMENT", reason="back")
    assert rules.policies(engine, "nbfc_001") == {}
    api.post(f"/rules/{RULE}", type="CONSUMER", enabled=False, outcome="REJECT_SEGMENT", reason="off")
    api.post(f"/rules/{RULE}/reset", type="CONSUMER")
    assert rules.policies(engine, "nbfc_001") == {} and effective(engine).enabled
    assert api.post("/rules/NOPE", type="CONSUMER", enabled=True, reason="r")[0] == 404
    assert api.post(f"/rules/{RULE}", type="CONSUMER", enabled=True, outcome="BOGUS", reason="r")[0] == 400


# ---------------------------------------------------------------- SSO identity (auth = cognito)
def id_token(**claims) -> str:
    def part(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    claims = {"token_use": "id", "aud": "client-1", "email": "Asha.K@Company.in", "sub": "s-1"} | claims
    return f"{part({'alg': 'RS256'})}.{part(claims)}.signature-checked-by-api-gateway"


def bearer(**claims) -> dict:
    return {"Authorization": f"Bearer {id_token(**claims)}"}


@pytest.fixture
def sso(make_api, engine):
    UserRepository(engine).add("asha.k", "Asha K", "asha.k@company.in", is_admin=True)
    return make_api(auth="cognito", cognito_client_id="client-1")


def test_sso_requires_a_registered_active_user(sso, engine):
    assert sso.get("/me")[0] == 401                                              # no token
    assert sso.get("/me", headers=bearer(token_use="access"))[0] == 401          # access token, not ID token
    assert sso.get("/me", headers=bearer(aud="other-client"))[0] == 401
    status, err = sso.get("/me", headers=bearer(email="someone@company.in"))
    assert status == 403 and "not registered" in err["error"]
    status, me = sso.get("/me", headers=bearer())
    assert status == 200 and me == {"username": "asha.k", "display_name": "Asha K", "email": "asha.k@company.in",
                                    "is_admin": True}
    UserRepository(engine).set_active("asha.k", False)
    assert sso.get("/me", headers=bearer())[0] == 403                            # leaver: disabled in the app
    assert actions(engine).count("LOGIN_DENIED") == 2


def test_sso_user_is_recorded_on_actions_and_logins(sso, engine, requests_repo):
    sso.post("/session", headers=bearer())
    status, data = sso.post("/requests", headers=bearer(), tenant_id="nbfc_001", as_of_date="2026-09-30",
                            submission_types=["CONSUMER"])
    assert status == 201 and requests_repo.list_batch(data["batch_id"])[0].requested_by == "asha.k"
    sso.post("/session/end", headers=bearer())
    assert actions(engine) == ["LOGIN", "RUN_CREATED", "LOGOUT"]
    assert UserRepository(engine).find("asha.k").last_login_at is not None
