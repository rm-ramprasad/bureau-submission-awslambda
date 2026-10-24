"""The standard pipeline: tenant mapping -> canonical snapshot -> the type's rule pack -> the type's file per bureau.

Every submission type that maps an LMS through clients/<tenant>/<type>.yaml uses it; a type only supplies its file
writer (types/<type>/file.py).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from submissions.adapters.extract import run_extract
from submissions.adapters.mapping import load_mapping, mapping_file
from submissions.adjustments.summary import adjustments_csv
from submissions.bureaus import BureauProfile
from submissions.formats.tudf.engine import FileStats
from submissions.pipeline.base import Services
from submissions.requests import RequestResult, SubmissionRequest
from submissions.snapshot import Snapshot
from submissions.tenants import Tenant
from submissions.validation.engine import ValidationResult, validate_snapshot
from submissions.validation.results import FindingFilter, findings_csv
from submissions.validation.rules import load_rule_set

# (services, request, snapshot, bureau, created) -> (file content, stats)
FileWriter = Callable[[Services, SubmissionRequest, Snapshot, BureauProfile, datetime], tuple[bytes, FileStats]]


class MappedPipeline:
    def __init__(self, write_file: FileWriter):
        self.write_file = write_file

    def build_snapshot(self, services: Services, tenant: Tenant, request: SubmissionRequest,
                       owner: str) -> tuple[int, ValidationResult]:
        if not tenant.mapping_path:
            raise ValueError(f"Tenant {tenant.tenant_id} has no mapping file configured")
        mapping = load_mapping(mapping_file(services.base_dir, tenant.mapping_path, request.submission_type))
        extract = run_extract(tenant=tenant, mapping=mapping, submission_type=request.submission_type,
                              as_of_date=request.as_of_date, app_engine=services.app_engine,
                              source_engine=services.source_engine, snapshots=services.snapshots, owner=owner,
                              batch_id=request.batch_id)
        rules = load_rule_set(services.app_engine, tenant.tenant_id, request.submission_type)
        result = validate_snapshot(services.app_engine, services.snapshots, extract.snapshot_id, rules)
        return extract.snapshot_id, result

    def generate_file(self, services: Services, tenant: Tenant, request: SubmissionRequest, snapshot: Snapshot,
                      bureau: BureauProfile) -> RequestResult:
        created = datetime.now()
        content, stats = self.write_file(services, request, snapshot, bureau, created)
        if stats.written == 0:
            raise ValueError(f"No accepted records to submit: all {stats.total_records} records were rejected by "
                             f"validation. Review the findings of snapshot {snapshot.snapshot_id} (no file written).")
        name = bureau.file_name(created, snapshot.as_of_date, request.reporting_cycle)
        if Path(name).name != name:
            raise ValueError(f"File name {name!r} from the bureau profile must not contain a path")
        folder = f"{tenant.tenant_id}/{request.batch_id}"
        file_uri = services.store.put(f"{folder}/{name}", content, "text/plain")   # never overwrites
        csv_text = ("".join(findings_csv(services.app_engine, snapshot.snapshot_id, FindingFilter()))
                    + adjustments_csv(services.app_engine, snapshot.snapshot_id))
        exceptions_uri = services.store.put(f"{folder}/{Path(name).stem}.exceptions.csv",
                                            csv_text.encode("utf-8"), "text/csv")
        return RequestResult(output_file_name=name, output_file_path=file_uri,
                             exceptions_file_path=exceptions_uri, total_records=stats.total_records,
                             accepted_records=stats.written, rejected_records=stats.rejected,
                             duplicate_records=stats.duplicates)
