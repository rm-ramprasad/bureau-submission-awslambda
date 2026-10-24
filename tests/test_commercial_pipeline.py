"""Commercial (phase 5): the registered pipeline end to end through the worker, and per-NBFC availability."""

import shutil
from datetime import date
from pathlib import Path

from submissions.enums import BureauCode as B, RequestStatus as S, RunMode as M, SubmissionType as T
from submissions.pipeline import available_types, get_pipeline
from submissions.pipeline.mapped import MappedPipeline
from submissions.tenants import Tenant
from tests.test_worker import ROOT, snapshot_count, worker  # noqa: F401  (fixture)

AS_OF = date(2026, 9, 30)


def test_commercial_uses_the_standard_pipeline():
    assert isinstance(get_pipeline(T.COMMERCIAL), MappedPipeline) and isinstance(get_pipeline(T.CONSUMER), MappedPipeline)


def test_validate_both_types_then_generate_commercial(worker, requests_repo, engine):
    v = requests_repo.create_batch("nbfc_001", AS_OF, M.VALIDATE, [T.CONSUMER, T.COMMERCIAL])
    assert worker.run_once() == 2
    rows = {r.submission_type: r for r in requests_repo.list_batch(v)}
    assert all(r.status is S.SUCCEEDED for r in rows.values()), [r.error_message for r in rows.values()]
    assert snapshot_count(engine) == 2                                 # one snapshot per type
    com = rows[T.COMMERCIAL]
    assert (com.total_records, com.accepted_records, com.rejected_records) == (18, 16, 2)   # scenarios 14, 15

    g = requests_repo.create_batch("nbfc_001", AS_OF, M.GENERATE, [T.COMMERCIAL], [B.CIBIL, B.EXPERIAN],
                                   "ME", snapshot_id=com.snapshot_id)
    assert worker.run_once() == 2
    files = requests_repo.list_batch(g)
    assert all(r.status is S.SUCCEEDED for r in files), [r.error_message for r in files]
    assert {r.output_file_name[:len("Commercial-ME-30092026-CIBC")] for r in files} == {
        "Commercial-ME-30092026-CIBC", "Commercial-ME-30092026-EXPC"}
    content = Path(files[0].output_file_path).read_bytes()
    assert content.startswith(b"HD|") and content.endswith(b"|\r\n") and b"\r\nTS|" in content
    assert all((r.accepted_records, r.rejected_records) == (16, 2) for r in files)
    assert Path(files[0].exceptions_file_path).read_text(encoding="utf-8").count("CUCRF.REC.") >= 2


def test_types_are_offered_only_with_a_mapping(tmp_path):
    full = Tenant("nbfc_001", "One", "nbfc_001", "clients/nbfc_001")
    assert available_types(full, ROOT) == [T.CONSUMER, T.COMMERCIAL]
    folder = tmp_path / "clients" / "nbfc_009"
    folder.mkdir(parents=True)
    shutil.copy(ROOT / "clients" / "nbfc_001" / "consumer.yaml", folder)  # consumer only: no commercial portfolio
    assert available_types(Tenant("nbfc_009", "Nine", "nbfc_009", "clients/nbfc_009"), tmp_path) == [T.CONSUMER]
    assert available_types(Tenant("nbfc_009", "Nine", "nbfc_009", None), tmp_path) == []
