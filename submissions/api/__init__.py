"""JSON API behind the static frontend (frontend/): raise requests, capture exceptions, follow results.

The API only writes request rows (then dispatches them) and reads results; the worker Lambdas do the work.
On AWS it runs in a Lambda behind API Gateway (submissions.lambda_handlers.api). Locally:
  python -m submissions.api        (serves the frontend too, with SUBMISSIONS_FRONTEND_DIR=frontend)
"""

from __future__ import annotations

from dataclasses import dataclass

from flask import Flask, g, jsonify, request, send_from_directory
from sqlalchemy import Engine
from werkzeug.exceptions import HTTPException

from submissions.adjustments import AdjustmentRepository
from submissions.bureaus import BureauRepository
from submissions.config import Settings
from submissions.db import make_engine
from submissions.dispatch import Dispatcher, make_dispatcher
from submissions.requests import RequestRepository
from submissions.snapshot import SnapshotRepository
from submissions.storage import FileStore, make_store
from submissions.tenants import TenantRepository


@dataclass(frozen=True)
class ApiServices:
    engine: Engine
    store: FileStore                 # generated files (S3 in real use)
    dispatcher: Dispatcher           # starts the worker for PENDING rows
    exports: object | None           # (s3 client, bucket) for CSV exports, or None: streamed by the API
    requests: RequestRepository
    tenants: TenantRepository
    bureaus: BureauRepository
    snapshots: SnapshotRepository
    adjustments: AdjustmentRepository
    tenant: str | None = None        # the one NBFC this deployment serves (Settings.tenant); None = all


def create_app(settings: Settings | None = None, engine: Engine | None = None, store: FileStore | None = None,
               dispatcher: Dispatcher | None = None, exports=None) -> Flask:
    settings = settings or Settings.from_env()
    engine = engine or make_engine(settings.database_url)
    if exports is None and settings.jobs_bucket:
        import boto3
        exports = (boto3.client("s3", region_name=settings.s3_region), settings.jobs_bucket)
    app = Flask(__name__, static_folder=None)
    from submissions.api.serialize import ApiJSONProvider
    app.json = ApiJSONProvider(app)
    app.config.update(MAX_CONTENT_LENGTH=1024 * 1024)
    app.extensions["submissions"] = ApiServices(
        engine=engine, store=store or make_store(settings), dispatcher=dispatcher or make_dispatcher(settings),
        exports=exports, requests=RequestRepository(engine), tenants=TenantRepository(engine),
        bureaus=BureauRepository(engine), snapshots=SnapshotRepository(engine), adjustments=AdjustmentRepository(engine),
        tenant=settings.tenant)

    from submissions.api import auth, views

    @app.before_request
    def _identify():
        if request.path.startswith("/api/"):
            g.identity = auth.identify(settings.auth, settings.cognito_client_id)

    @app.errorhandler(HTTPException)
    def _error(exc: HTTPException):
        return jsonify(error=exc.description), exc.code

    @app.after_request
    def _no_store(resp):
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    app.register_blueprint(views.bp, url_prefix="/api")

    if settings.frontend_dir:                            # local development only: on AWS CloudFront serves it
        root = settings.frontend_dir.resolve()

        @app.get("/")
        @app.get("/<path:path>")
        def _frontend(path: str = "index.html"):
            return send_from_directory(root, path if (root / path).is_file() else "index.html")

    return app
