"""Serverless pieces: SSO users, job dispatch through S3, the worker / jobs / API Lambda handlers."""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from submissions import lambda_handlers as L
from submissions.bureaus.seed import seed as seed_bureaus
from submissions.dispatch import NoDispatch, S3JobDispatcher, job_key, request_id_from_key
from submissions.enums import RequestStatus as S, RunMode as M, SubmissionType as T
from submissions.ops.tables import audit_event
from submissions.pipeline import Services
from submissions.snapshot import SnapshotRepository
from submissions.storage import LocalFileStore
from submissions.users import UserError, UserRepository, main as users_cli
from submissions.worker.runner import Worker

ROOT = Path(__file__).resolve().parent.parent
AS_OF = date(2026, 9, 30)


# ---------------------------------------------------------------- users (SSO)
def test_users_are_matched_by_email(engine):
    users = UserRepository(engine)
    users.add("asha.k", "Asha K", " Asha.K@Company.IN ")
    assert users.find_by_email("asha.k@company.in").username == "asha.k"
    with pytest.raises(UserError, match="already belongs"):
        users.add("asha2", "Asha 2", "asha.k@company.in")
    with pytest.raises(UserError, match="valid e-mail"):
        users.add("bob", "Bob", "bob-at-company")
    users.add("bob", "Bob", "bob@company.in")
    with pytest.raises(UserError, match="already belongs"):
        users.set_email("bob", "asha.k@company.in")
    users.set_email("bob", "robert@company.in")
    assert users.find_by_email("robert@company.in").username == "bob" and users.find_by_email(None) is None


def test_users_cli(engine, capsys):
    assert users_cli(["add", "asha.k", "--email", "asha.k@company.in", "--name", "Asha K", "--admin"], engine) == 0
    assert users_cli(["disable", "asha.k"], engine) == 0
    assert users_cli(["list"], engine) == 0
    out = capsys.readouterr().out
    assert "asha.k@company.in" in out and "disabled" in out and "admin" in out
    assert users_cli(["enable", "nobody"], engine) == 1
    with engine.connect() as conn:
        assert list(conn.execute(select(audit_event.c.action))) == [("USER_ADDED",), ("USER_DISABLED",)]


# ---------------------------------------------------------------- dispatch
class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)


def test_s3_dispatcher_writes_one_job_object_per_row(requests_repo):
    v = requests_repo.create_batch("nbfc_001", AS_OF, M.VALIDATE, [T.CONSUMER])
    g = requests_repo.create_batch("nbfc_002", AS_OF, M.GENERATE, [T.CONSUMER], ["CIBIL"], snapshot_id=1)
    rows = requests_repo.list_batch(v) + requests_repo.list_batch(g)
    s3 = FakeS3()
    S3JobDispatcher(s3, "jobs-bucket").dispatch(rows)
    assert [p["Key"] for p in s3.puts] == [f"jobs/validate/{rows[0].request_id}.json",
                                           f"jobs/generate/{rows[1].request_id}.json"]
    assert json.loads(s3.puts[0]["Body"]) == {"request_id": rows[0].request_id, "run_mode": "VALIDATE"}
    assert all(p["Bucket"] == "jobs-bucket" and p["ServerSideEncryption"] == "AES256" for p in s3.puts)
    assert request_id_from_key(job_key(rows[1])) == rows[1].request_id
    with pytest.raises(ValueError):
        request_id_from_key("jobs/validate/../x.json")
    assert NoDispatch().dispatch(rows) is None


# ---------------------------------------------------------------- handlers
@pytest.fixture
def worker(engine, lms_engine, requests_repo, tenant_repo, bureau_repo, tmp_path):
    seed_bureaus(bureau_repo, ["nbfc_001"])
    services = Services(app_engine=engine, source_engine=lms_engine, snapshots=SnapshotRepository(engine),
                        base_dir=ROOT, store=LocalFileStore(tmp_path))
    return Worker(services, requests_repo, tenant_repo, bureau_repo, worker_id="lambda-validate")


def s3_event(*keys) -> dict:
    return {"Records": [{"s3": {"bucket": {"name": "jobs"}, "object": {"key": k}}} for k in keys]}


def test_worker_handler_runs_the_dispatched_request_once(worker, requests_repo, monkeypatch):
    monkeypatch.setattr(L, "_worker", lambda: worker)
    v = requests_repo.create_batch("nbfc_001", AS_OF, M.VALIDATE, [T.CONSUMER])
    (row,) = requests_repo.list_batch(v)
    assert L.worker(s3_event(job_key(row)), None) == {"ok": True}
    done = requests_repo.get(row.request_id)
    assert done.status is S.SUCCEEDED and done.worker_id == "lambda-validate" and done.attempt_count == 1
    L.worker(s3_event(job_key(row)), None)                                       # duplicate delivery: skipped
    assert requests_repo.get(row.request_id).attempt_count == 1


def test_worker_handler_asks_lambda_to_retry_when_the_snapshot_is_busy(worker, requests_repo, monkeypatch):
    monkeypatch.setattr(L, "_worker", lambda: worker)
    from submissions.worker.runner import SnapshotBusy
    monkeypatch.setattr(worker, "_snapshot", lambda req, tenant: (_ for _ in ()).throw(SnapshotBusy("building")))
    v = requests_repo.create_batch("nbfc_001", AS_OF, M.VALIDATE, [T.CONSUMER])
    (row,) = requests_repo.list_batch(v)
    with pytest.raises(L.RetryLater):
        L.worker(s3_event(job_key(row)), None)
    assert requests_repo.get(row.request_id).status is S.PENDING                 # released for the retry


@pytest.fixture
def jobs_env(engine, monkeypatch, tmp_path):
    from submissions.config import Settings
    monkeypatch.setattr(L, "engine", lambda: engine)
    monkeypatch.setattr(L, "settings", lambda: Settings("sqlite://", "sqlite://", tmp_path, tenant="nbfc_001"))
    sent = []
    monkeypatch.setattr("submissions.dispatch.make_dispatcher",
                        lambda settings: type("D", (), {"dispatch": lambda self, rows: sent.extend(
                            r.request_id for r in rows)})())
    return sent


def test_jobs_recovery_redispatches_requests_that_were_never_picked_up(jobs_env, requests_repo, clock):
    v = requests_repo.create_batch("nbfc_001", AS_OF, M.VALIDATE, [T.CONSUMER])   # requested at the fake clock
    result = L.jobs({"job": "recovery"}, None)
    assert result["redispatched"] == [requests_repo.list_batch(v)[0].request_id] == jobs_env


def test_jobs_users_and_unknown(jobs_env, engine):
    out = L.jobs({"job": "users", "args": ["add", "asha.k", "--email", "asha.k@company.in", "--name", "Asha K"]}, None)
    assert out["exit_code"] == 0 and "add: asha.k done" in out["output"]
    assert L.jobs({"job": "users", "args": ["bogus"]}, None)["exit_code"] == 2
    assert UserRepository(engine).find("asha.k").email == "asha.k@company.in"
    with pytest.raises(ValueError, match="Unknown job"):
        L.jobs({"job": "nope"}, None)
    assert L.jobs({"job": "retention", "days": 90, "dry_run": True}, None)["dry_run"] is True


def test_api_handler_serves_http_api_events(engine, monkeypatch, tmp_path):
    from submissions.config import Settings
    L._api.cache_clear()
    monkeypatch.setattr(L, "engine", lambda: engine)
    monkeypatch.setattr(L, "settings", lambda: Settings("sqlite://", "sqlite://", tmp_path))
    event = {"version": "2.0", "routeKey": "$default", "rawPath": "/api/meta", "rawQueryString": "",
             "headers": {"host": "x.execute-api.ap-south-1.amazonaws.com"},
             "requestContext": {"http": {"method": "GET", "path": "/api/meta", "sourceIp": "10.0.0.1",
                                         "protocol": "HTTP/1.1"}, "stage": "$default"},
             "isBase64Encoded": False}
    resp = L.api(event, None)
    L._api.cache_clear()
    assert resp["statusCode"] == 200 and "nbfc_001" in resp["body"]
    assert {k.lower(): v for k, v in resp["headers"].items()}["cache-control"] == "no-store"
