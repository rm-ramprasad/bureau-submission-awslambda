"""AWS Lambda entry points (template.yaml). All run inside the VPC next to RDS, on the same code package.

  api       API Gateway HTTP API (payload 2.0) -> the Flask JSON API
  worker    S3 "job object created" event -> run that one request (validate or generate worker function)
  jobs      EventBridge Scheduler / `aws lambda invoke` -> recovery | retention | migrate | users

Clients and engines are created once per execution environment and reused while it stays warm.
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
from datetime import timedelta
from functools import cache
from pathlib import Path
from urllib.parse import unquote_plus

from submissions.config import Settings
from submissions.db import make_engine
from submissions.logging_config import configure_logging

TASK_ROOT = Path(__file__).resolve().parent.parent       # clients/ and migrations/ are packaged next to the code
log = logging.getLogger(__name__)


@cache
def settings() -> Settings:
    s = Settings.from_env()
    configure_logging(s.log_level)
    return s


@cache
def engine():
    # The extract holds a connection while it writes the snapshot over another one, so allow a few per environment
    # (at most 5; with the account's concurrency cap of 10 that stays within the RDS instance's connection limit).
    return make_engine(settings().database_url, pool_size=2, max_overflow=3, pool_recycle=280)


# ---------------------------------------------------------------- API
@cache
def _api():
    from apig_wsgi import make_lambda_handler
    from submissions.api import create_app
    return make_lambda_handler(create_app(settings(), engine=engine()), binary_support=True)


def api(event, context):
    return _api()(event, context)


# ---------------------------------------------------------------- workers
class RetryLater(Exception):
    """Raised so Lambda retries the asynchronous invocation (the snapshot is being built by another invocation)."""


@cache
def _worker():
    from submissions.bureaus import BureauRepository
    from submissions.ops.recovery import RecoverySettings
    from submissions.pipeline import Services
    from submissions.requests import RequestRepository
    from submissions.snapshot import SnapshotRepository
    from submissions.storage import make_store
    from submissions.tenants import TenantRepository
    from submissions.worker.runner import Worker
    s, app = settings(), engine()
    source = app if s.source_database_url == s.database_url else make_engine(s.source_database_url)
    services = Services(app_engine=app, source_engine=source, snapshots=SnapshotRepository(app), base_dir=TASK_ROOT,
                        store=make_store(s))
    return Worker(services, RequestRepository(app), TenantRepository(app), BureauRepository(app),
                  worker_id=os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "lambda-worker"),
                  recovery=RecoverySettings(run_timeout=RUN_TIMEOUT, build_timeout=RUN_TIMEOUT))


RUN_TIMEOUT = timedelta(minutes=20)        # longer than the worker Lambda timeout (15 min): the run is dead by then


def worker(event, context):
    """One S3 event (usually one record) per invocation; each record is one dispatched request."""
    from submissions.dispatch import request_id_from_key
    w = _worker()
    for record in event.get("Records", []):
        request_id = request_id_from_key(unquote_plus(record["s3"]["object"]["key"]))
        log.info("Running request %s", request_id)
        if not w.run_request(request_id):
            raise RetryLater(f"Request {request_id}: its snapshot is being built by another run; retrying later")
    return {"ok": True}


# ---------------------------------------------------------------- scheduled and admin jobs
PENDING_GRACE = timedelta(minutes=10)


def _recovery() -> dict:
    """Release or fail runs whose Lambda died, then re-dispatch PENDING rows that were never picked up."""
    from submissions.db import utcnow
    from submissions.dispatch import make_dispatcher
    from submissions.ops.recovery import RecoverySettings, recover
    from submissions.requests import RequestRepository
    from submissions.snapshot import SnapshotRepository
    requests = RequestRepository(engine())
    result = recover(engine(), requests, SnapshotRepository(engine()),
                     RecoverySettings(run_timeout=RUN_TIMEOUT, build_timeout=RUN_TIMEOUT))
    stale = requests.pending_before(utcnow() - PENDING_GRACE)
    make_dispatcher(settings()).dispatch(stale)
    return {"released": result.released, "failed": result.failed, "snapshots_failed": result.snapshots_failed,
            "redispatched": [r.request_id for r in stale]}


def _retention(event) -> dict:
    from submissions.ops.retention import purge
    from submissions.storage import make_store
    days = int(event.get("days", 90))
    if days < 1:
        raise ValueError("days must be at least 1")
    result = purge(engine(), timedelta(days=days), make_store(settings()), dry_run=bool(event.get("dry_run")))
    return {"snapshots": result.snapshots, "files": len(result.files), "dry_run": bool(event.get("dry_run"))}


def _users(event) -> dict:
    from submissions.users import main
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main([str(a) for a in event.get("args", [])], engine=engine(), actor="admin-lambda")
        except SystemExit as exc:                      # argparse: usage errors
            code = exc.code
    return {"exit_code": code, "output": out.getvalue() + err.getvalue()}


def jobs(event, context):
    job = (event or {}).get("job")
    log.info("Job %s", job)
    if job == "recovery":
        return _recovery()
    if job == "retention":
        return _retention(event)
    if job == "migrate":
        from submissions.migrate import apply_migrations
        from submissions.reference import seed
        from submissions.bureaus import BureauRepository
        from submissions.bureaus.seed import seed_missing
        applied = apply_migrations(engine(), TASK_ROOT / "migrations")
        result = {"applied": applied, "reference": seed(engine())}       # reference rows after the schema
        if settings().tenant:                                             # placeholder profiles it lacks, never edits
            result["bureau_profiles_added"] = seed_missing(BureauRepository(engine()), settings().tenant)
        return result
    if job == "users":
        return _users(event)
    raise ValueError(f"Unknown job {job!r}: use recovery, retention, migrate or users")
