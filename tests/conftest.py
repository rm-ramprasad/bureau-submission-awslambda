from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.pool import StaticPool

import submissions.adjustments.tables  # noqa: F401  (registers tables on metadata, and the view)
import submissions.users  # noqa: F401  (app_user)
import submissions.bureaus.tables  # noqa: F401  (registers tables on metadata)
import submissions.canonical.schema  # noqa: F401
import submissions.ops.tables  # noqa: F401
import submissions.requests.tables  # noqa: F401
import submissions.validation.tables  # noqa: F401
from submissions.reference import seed as seed_reference
from submissions.bureaus import BureauRepository
from submissions.db import make_engine, metadata
from submissions.requests import RequestRepository
from submissions.tenants import TenantRepository
from submissions.tenants.seed import seed as seed_tenants


class FakeClock:
    def __init__(self, start: datetime = datetime(2026, 10, 21, 9, 0, 0)):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int = 1) -> None:
        self.now += timedelta(seconds=seconds)


LMS_SCHEMAS = ("nbfc_001", "nbfc_002")


def _concat_ws(sep, *args):
    return sep.join(str(a) for a in args if a is not None)


def sqlite_engine():
    """In-memory SQLite that behaves enough like the MySQL setup: FKs on, tenant schemas attached, CONCAT_WS."""
    eng = make_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _setup(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")  # SQLite ignores FKs unless asked; MySQL enforces them
        for schema in LMS_SCHEMAS:
            dbapi_conn.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
        dbapi_conn.create_function("CONCAT_WS", -1, _concat_ws)
        dbapi_conn.create_function("REGEXP_LIKE", 2,                     # MySQL 8 built-ins used by custom rules
                                   lambda v, p: None if v is None else int(re.search(p, str(v)) is not None))
        dbapi_conn.create_function("CHAR_LENGTH", 1, lambda v: None if v is None else len(str(v)))

    return eng


@pytest.fixture
def engine():
    eng = sqlite_engine()
    metadata.create_all(eng)
    seed_tenants(TenantRepository(eng, clock=lambda: datetime(2026, 10, 1)))  # nbfc_001, nbfc_002
    seed_reference(eng)                           # as on deploy: canonical codes + each type's translations
    yield eng
    eng.dispose()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def requests_repo(engine, clock):
    return RequestRepository(engine, clock=clock)


@pytest.fixture
def lms_engine():
    """A separate 'LMS server' with both mock tenant schemas loaded (for the stream strategy)."""
    from mock_data.generate_mock_data import load_into
    eng = sqlite_engine()
    load_into(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def tenant_repo(engine, clock):
    return TenantRepository(engine, clock=clock)


@pytest.fixture
def bureau_repo(engine, clock):
    return BureauRepository(engine, clock=clock)


class RecordingDispatcher:
    """Collects the rows the API dispatched (in tests the polling worker runs them)."""

    def __init__(self):
        self.dispatched: list[int] = []

    def dispatch(self, requests):
        self.dispatched += [r.request_id for r in requests]


class Api:
    """JSON test client for the API: get/post return (status, json)."""

    def __init__(self, client, tenant: str | None = None):
        self.client, self.tenant = client, tenant

    def get(self, path, headers=None, **query):
        if self.tenant and "tenant" not in query:
            query["tenant"] = self.tenant
        resp = self.client.get(f"/api{path}", query_string=query, headers=headers)
        return resp.status_code, resp.get_json(silent=True)

    def post(self, path, headers=None, **body):
        if self.tenant and "tenant" not in body:
            body["tenant"] = self.tenant
        resp = self.client.post(f"/api{path}", json=body, headers=headers)
        return resp.status_code, resp.get_json(silent=True)

    def raw(self, path, **query):
        return self.client.get(f"/api{path}", query_string=query)


@pytest.fixture
def dispatcher():
    return RecordingDispatcher()


@pytest.fixture
def make_api(engine, tmp_path, dispatcher):
    """make_api(store=None, tenant=None, **settings) -> Api on a test app (auth none unless given)."""
    from submissions.api import create_app
    from submissions.config import Settings

    def make(store=None, tenant=None, **settings):
        app = create_app(Settings("sqlite://", "sqlite://", tmp_path, **settings), engine=engine, store=store,
                         dispatcher=dispatcher)
        app.config.update(TESTING=True)
        return Api(app.test_client(), tenant)

    return make
