"""One NBFC per deployment (Settings.tenant / SUBMISSIONS_TENANT): the API applies it whatever the page sends."""

from datetime import date

import pytest

from submissions.config import Settings
from submissions.enums import RunMode, SubmissionType

AS_OF = date(2026, 9, 30)


@pytest.fixture
def api(engine, tmp_path, dispatcher):
    """API of a deployment that serves nbfc_001 only."""
    from submissions.api import create_app
    from tests.conftest import Api
    app = create_app(Settings("sqlite://", "sqlite://", tmp_path, tenant="nbfc_001"), engine=engine,
                     dispatcher=dispatcher)
    app.config.update(TESTING=True)
    return Api(app.test_client())


def test_meta_lists_only_the_deployment_tenant(api):
    status, meta = api.get("/meta")
    assert status == 200 and meta["tenant"] == "nbfc_001"
    assert [t["tenant_id"] for t in meta["tenants"]] == ["nbfc_001"]


def test_new_request_uses_the_deployment_tenant(api, requests_repo):
    status, data = api.post("/requests", tenant_id="nbfc_002", as_of_date=str(AS_OF), submission_types=["CONSUMER"])
    assert status == 201
    assert requests_repo.list_batch(data["batch_id"])[0].tenant_id == "nbfc_001"


def test_other_tenants_data_is_not_visible(api, requests_repo):
    other = requests_repo.create_batch("nbfc_002", AS_OF, RunMode.VALIDATE, [SubmissionType.CONSUMER])
    mine = requests_repo.create_batch("nbfc_001", AS_OF, RunMode.VALIDATE, [SubmissionType.CONSUMER])
    assert api.get(f"/batches/{other}")[0] == 404
    assert api.get(f"/batches/{mine}")[0] == 200
    status, data = api.get("/batches", tenant="nbfc_002")                       # the argument is ignored
    assert status == 200 and {b["tenant_id"] for b in data["batches"]} == {"nbfc_001"}


def test_settings_require_a_tenant(monkeypatch):
    monkeypatch.setenv("SUBMISSIONS_DATABASE_URL", "sqlite://")
    monkeypatch.delenv("SUBMISSIONS_TENANT", raising=False)
    with pytest.raises(RuntimeError, match="SUBMISSIONS_TENANT"):
        Settings.from_env()
    monkeypatch.setenv("SUBMISSIONS_TENANT", "nbfc_001")
    assert Settings.from_env().tenant == "nbfc_001"
