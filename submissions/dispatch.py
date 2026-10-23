"""Start the work for PENDING requests.

On AWS each PENDING row gets a small job object in the jobs bucket:
  s3://<jobs bucket>/jobs/validate/<request_id>.json      -> validate worker Lambda
  s3://<jobs bucket>/jobs/generate/<request_id>.json      -> generate worker Lambda
An S3 event notification invokes the worker asynchronously (Lambda retries and an on-failure queue included). The
VPC reaches S3 through the free gateway endpoint, so starting work needs no NAT or interface endpoint.

Locally (and in tests) nothing is sent: the polling worker (`python -m submissions.worker`) claims PENDING rows itself.
Dispatch always happens after the row is committed; a lost dispatch is repaired by the recovery job, which
re-dispatches PENDING rows that have waited too long.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Protocol

from submissions.enums import RunMode
from submissions.requests import RequestRepository, SubmissionRequest

log = logging.getLogger(__name__)
JOBS_PREFIX = "jobs"


class Dispatcher(Protocol):
    def dispatch(self, requests: Iterable[SubmissionRequest]) -> None:
        """Start the work for these (PENDING) rows."""


class NoDispatch:
    """Local development and tests: the polling worker picks PENDING rows up."""

    def dispatch(self, requests: Iterable[SubmissionRequest]) -> None:
        return None


def job_key(req: SubmissionRequest) -> str:
    return f"{JOBS_PREFIX}/{'validate' if req.run_mode is RunMode.VALIDATE else 'generate'}/{req.request_id}.json"


def request_id_from_key(key: str) -> int:
    """jobs/<mode>/<request_id>.json -> request_id."""
    name = key.rsplit("/", 1)[-1]
    if not name.endswith(".json") or not name[:-5].isdigit():
        raise ValueError(f"Not a job key: {key!r}")
    return int(name[:-5])


class S3JobDispatcher:
    def __init__(self, client, bucket: str):
        self.client, self.bucket = client, bucket

    def dispatch(self, requests: Iterable[SubmissionRequest]) -> None:
        for req in requests:
            body = json.dumps({"request_id": req.request_id, "run_mode": str(req.run_mode)}).encode()
            # overwriting an earlier job object for the same row is fine: it re-triggers the worker
            self.client.put_object(Bucket=self.bucket, Key=job_key(req), Body=body, ContentType="application/json",
                                   ServerSideEncryption="AES256")
            log.info("Dispatched request %s (%s)", req.request_id, req.run_mode)


def dispatch_batch(dispatcher: Dispatcher, requests: RequestRepository, batch_id: str) -> None:
    """Dispatch the PENDING rows of a batch (after create / submit)."""
    dispatcher.dispatch(r for r in requests.list_batch(batch_id) if r.status.value == "PENDING")


def make_dispatcher(settings) -> Dispatcher:
    if not settings.jobs_bucket:
        return NoDispatch()
    import boto3
    return S3JobDispatcher(boto3.client("s3", region_name=settings.s3_region), settings.jobs_bucket)
