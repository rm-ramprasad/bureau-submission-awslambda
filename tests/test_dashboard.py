"""Request stages (derived) and the dashboard / tracker views built on them."""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from submissions.bureaus.seed import seed as seed_bureaus
from submissions.enums import BureauCode as B, RequestStatus as S, RunMode as M, SubmissionType as T
from submissions.pipeline import Services
from submissions.requests.models import SubmissionRequest
from submissions.requests.stages import Period, Request, Stage, build_dashboard, load_requests
from submissions.snapshot import SnapshotRepository
from submissions.storage import LocalFileStore
from submissions.worker.runner import Worker

ROOT = Path(__file__).resolve().parent.parent
AS_OF = date(2026, 9, 30)
NOW = datetime(2026, 10, 21, 9, 0)


def row(status, mode=M.VALIDATE, **kw) -> SubmissionRequest:
    base = dict(request_id=1, batch_id="b", tenant_id="nbfc_001", run_mode=mode, as_of_date=AS_OF,
                submission_type=T.CONSUMER, bureau_code=None, snapshot_id=1, reporting_cycle=None, requested_by="u",
                requested_at=NOW, status=status, worker_id=None, attempt_count=0, started_at=None, finished_at=None,
                output_file_name=None, output_file_path=None, exceptions_file_path=None, total_records=None,
                accepted_records=None, rejected_records=None, duplicate_records=None, excluded_accounts=None,
                overridden_accounts=None, error_message=None)
    return SubmissionRequest(**base | kw)


@pytest.mark.parametrize("validation, files, stage", [
    ([S.DRAFT], [], Stage.AWAITING_EXCEPTIONS),
    ([S.CANCELLED], [], Stage.CANCELLED),
    ([S.PENDING], [], Stage.IN_PROGRESS),
    ([S.RUNNING], [], Stage.IN_PROGRESS),
    ([S.SUCCEEDED], [], Stage.VALIDATED),
    ([S.SUCCEEDED], [S.RUNNING], Stage.IN_PROGRESS),
    ([S.SUCCEEDED], [S.FAILED, S.SUCCEEDED], Stage.COMPLETED),
    ([S.SUCCEEDED], [S.FAILED], Stage.FAILED),
    ([S.SUCCEEDED], [S.CANCELLED], Stage.VALIDATED),
    ([S.FAILED], [], Stage.FAILED),
])
def test_stage_rules(validation, files, stage):
    req = Request("b", [row(s) for s in validation], [row(s, M.GENERATE, bureau_code=B.CIBIL) for s in files])
    assert req.stage is stage


def test_period_start():
    assert Period.THIS_MONTH.start(NOW) == datetime(2026, 10, 1)
    assert Period.LAST_30.start(NOW) == NOW - timedelta(days=30) and Period.ALL.start(NOW) is None


# ---------------------------------------------------------------- built from real rows
@pytest.fixture
def worker(engine, lms_engine, requests_repo, tenant_repo, bureau_repo, tmp_path):
    seed_bureaus(bureau_repo, ["nbfc_001", "nbfc_002"])
    services = Services(app_engine=engine, source_engine=lms_engine, snapshots=SnapshotRepository(engine),
                        base_dir=ROOT, store=LocalFileStore(tmp_path))
    return Worker(services, requests_repo, tenant_repo, bureau_repo, worker_id="w-dash")


def test_dashboard_counts_requests_not_rows(engine, worker, requests_repo, clock):
    done = requests_repo.create_batch("nbfc_001", AS_OF, M.VALIDATE, [T.CONSUMER])
    worker.run_once()
    snap = requests_repo.list_batch(done)[0].snapshot_id
    requests_repo.create_batch("nbfc_001", AS_OF, M.GENERATE, [T.CONSUMER], [B.CIBIL, B.EXPERIAN], snapshot_id=snap)
    worker.run_once()                                                   # two files: still one request
    requests_repo.create_batch("nbfc_002", AS_OF, M.VALIDATE, [T.CONSUMER], draft=True)
    clock.advance(3 * 86400)
    board = build_dashboard(engine, None, Period.ALL, clock())
    assert board.raised == 2
    assert (board.count(Stage.COMPLETED), board.count(Stage.AWAITING_EXCEPTIONS)) == (1, 1)
    assert board.files_generated == 2 and board.records_submitted == 96 and board.total("records") == 56
    assert board.completion_rate == 0.5
    assert [a.reason for a in board.attention] == ["Draft for 3 days: submit or discard it"]
    assert {(b["bureau"], b["files"], b["records"]) for b in board.bureaus} == {(B.CIBIL, 1, 48), (B.EXPERIAN, 1, 48)}
    assert [r.tenant_id for r in load_requests(engine, "nbfc_002")] == ["nbfc_002"]


def test_one_request_has_a_stage_per_type(engine, worker, requests_repo, tenant_repo, clock, tmp_path):
    """Consumer validated and filed, commercial failed in the same request: each type shows its own stage."""
    v = requests_repo.create_batch("nbfc_001", AS_OF, M.VALIDATE, [T.CONSUMER, T.COMMERCIAL])
    worker.run_once()
    rows = {r.submission_type: r for r in requests_repo.list_batch(v)}
    requests_repo.create_batch("nbfc_001", AS_OF, M.GENERATE, [T.CONSUMER], [B.CIBIL],
                               snapshot_id=rows[T.CONSUMER].snapshot_id)
    worker.run_once()
    with engine.begin() as conn:                                        # the commercial validation failed
        from submissions.requests.tables import submission_request as t
        conn.execute(t.update().where(t.c.request_id == rows[T.COMMERCIAL].request_id)
                     .values(status="FAILED", error_message="Snapshot build failed: party: no table"))
    now = clock()
    consumer = build_dashboard(engine, "nbfc_001", Period.ALL, now, T.CONSUMER)
    commercial = build_dashboard(engine, "nbfc_001", Period.ALL, now, T.COMMERCIAL)
    assert (consumer.count(Stage.COMPLETED), consumer.count(Stage.FAILED), consumer.total("records")) == (1, 0, 56)
    assert (commercial.count(Stage.COMPLETED), commercial.count(Stage.FAILED), commercial.total("records")) == (0, 1, 0)
    assert commercial.attention[0].reason.startswith("Failed: Snapshot build failed") and not consumer.attention
    assert commercial.files_generated == 0 and consumer.files_generated == 1


def test_dashboard_api_switches_type(make_api, worker, requests_repo):
    api = make_api()
    requests_repo.create_batch("nbfc_001", AS_OF, M.VALIDATE, [T.COMMERCIAL])
    worker.run_once()
    requests_repo.create_batch("nbfc_001", AS_OF, M.VALIDATE, [T.CONSUMER], draft=True)
    _, consumer = api.get("/dashboard", period="all", tenant="nbfc_001")
    assert consumer["type"] == "CONSUMER" and consumer["raised"] == 1                 # default: the first type
    assert [t["value"] for t in consumer["types"]] == ["CONSUMER", "COMMERCIAL"]
    _, commercial = api.get("/dashboard", period="all", tenant="nbfc_001", type="COMMERCIAL")
    assert commercial["type"] == "COMMERCIAL" and commercial["records"] == 18
    assert {s["value"]: s["count"] for s in commercial["stages"]}["VALIDATED"] == 1
    assert "scheduled" not in commercial
    _, tracker = api.get("/batches", stage="VALIDATED", period="all", type="COMMERCIAL")
    assert len(tracker["requests"]) == 1
    assert api.get("/batches", stage="VALIDATED", period="all", type="CONSUMER")[1]["requests"] == []
    assert api.get("/dashboard", type="NOPE")[0] == 400


def test_dashboard_api_and_click_through(make_api, worker, requests_repo):
    api = make_api()
    v = requests_repo.create_batch("nbfc_001", AS_OF, M.VALIDATE, [T.CONSUMER])
    worker.run_once()
    requests_repo.create_batch("nbfc_002", AS_OF, M.VALIDATE, [T.CONSUMER], draft=True)
    status, board = api.get("/dashboard", period="all")
    assert status == 200 and board["raised"] == 2 and board["period"] == "all"
    counts = {s["value"]: s["count"] for s in board["stages"]}
    assert counts["AWAITING_EXCEPTIONS"] == 1 and counts["VALIDATED"] == 1
    assert {n["tenant_id"] for n in board["nbfc_status"]} == {"nbfc_001", "nbfc_002"}
    assert board["recent"][0]["stage_label"] in ("Awaiting exceptions", "Validated, files pending")
    _, tracker = api.get("/batches", stage="VALIDATED", period="all")
    assert [r["batch_id"] for r in tracker["requests"]] == [v]
    assert api.get("/batches", stage="COMPLETED", period="all")[1]["requests"] == []
    assert api.get("/batches", stage="NOPE")[0] == 400
    assert api.get("/dashboard", period="bogus")[1]["period"] == "month"          # falls back to this month
    _, one = api.get("/dashboard", period="all", tenant="nbfc_002")
    assert one["raised"] == 1 and one["nbfc_status"] is None
