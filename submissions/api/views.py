"""API routes (all under /api): dashboard, tracker, files, new request, exceptions step, request detail (submit,
generate, downloads), findings (with exclude / override into a draft request), rules & policies, audit.

The NBFC chosen in the frontend's top bar is passed as ?tenant= (or "tenant" in the JSON body); empty = all NBFCs.
Errors are JSON {"error": message} with a 4xx status; actions answer {"message": ..., ...}.
"""

from __future__ import annotations

import logging
import math
import re
import secrets
from datetime import date, datetime, time, timedelta

from flask import Blueprint, Response, abort, current_app, g, jsonify, request
from sqlalchemy import select

from submissions.adjustments import (
    AdjustmentError, AdjustmentNotFoundError, AdjustmentScope, applied_summary, parse_keys, parse_override_value,
)
from submissions.api import ApiServices
from submissions.api.auth import current_user
from submissions.canonical.schema import ENTITY_TABLES
from submissions.db import utcnow
from submissions.dispatch import dispatch_batch
from submissions.enums import (
    AdjustmentKind, BatchStatus, BureauCode, Outcome, OverrideField, ReportingCycle, RequestStatus, RunMode, SnapshotStatus,
    SubmissionType,
)
from submissions.ops import audit
from submissions.pipeline import available_types, enabled_types
from submissions.requests import (
    DuplicateActiveRequestError, InvalidTransitionError, RequestNotFoundError, RequestValidationError, stages,
)
from submissions.requests.stages import Period, Stage
from submissions.snapshot import SnapshotNotFoundError
from submissions.storage import StoredFileNotFound
from submissions.tenants import InactiveTenantError, TenantNotFoundError
from submissions.users import UserRepository
from submissions.validation import custom as custom_rules
from submissions.validation import parameters as rule_parameters
from submissions.validation import results, rules

bp = Blueprint("api", __name__)
log = logging.getLogger(__name__)
PAGE_SIZE = 200
TRACKER_PAGE = 50
QUEUE_SLOW = timedelta(minutes=10)
EXPORT_URL_SECONDS = 300


def svc() -> ApiServices:
    return current_app.extensions["submissions"]


def body() -> dict:
    return request.get_json(silent=True) or {}


def arg(name: str, default=None):
    """A value from the JSON body (POST) or the query string."""
    value = body().get(name) if request.method == "POST" else None
    return value if value is not None else request.args.get(name, default)


def message(text: str, status: int = 200, **extra):
    return jsonify(message=text, **extra), status


def fail(text: str, status: int = 400):
    abort(status, text)


def last_month_end(today: date | None = None) -> date:
    return (today or date.today()).replace(day=1) - timedelta(days=1)


def selected_tenant() -> str | None:
    """The deployment's NBFC when configured (whatever the page sends); otherwise the `tenant` argument (None = all).
    Unknown ids are refused."""
    if svc().tenant:
        return svc().tenant
    tenant_id = arg("tenant") or None
    if tenant_id and tenant_id not in {t.tenant_id for t in svc().tenants.list(active_only=False)}:
        fail(f"Unknown NBFC {tenant_id}")
    return tenant_id


def options(enum) -> list[dict]:
    return [{"value": e.value, "label": getattr(e, "label", e.value)} for e in enum]


def row_json(r) -> dict:
    return {"request_id": r.request_id, "batch_id": r.batch_id, "tenant_id": r.tenant_id, "run_mode": r.run_mode,
            "as_of_date": r.as_of_date, "submission_type": r.submission_type, "bureau_code": r.bureau_code,
            "snapshot_id": r.snapshot_id, "reporting_cycle": r.reporting_cycle, "requested_by": r.requested_by,
            "requested_at": r.requested_at, "status": r.status, "attempt_count": r.attempt_count,
            "started_at": r.started_at, "finished_at": r.finished_at, "output_file_name": r.output_file_name,
            "has_file": bool(r.output_file_path), "has_exceptions": bool(r.exceptions_file_path),
            "output_location": r.output_file_path, "total_records": r.total_records,
            "accepted_records": r.accepted_records, "rejected_records": r.rejected_records,
            "duplicate_records": r.duplicate_records, "excluded_accounts": r.excluded_accounts,
            "overridden_accounts": r.overridden_accounts, "error_message": r.error_message}


def request_json(r: stages.Request, now: datetime) -> dict:
    """A request (validation batch + its file generations) as the dashboard and tracker show it."""
    return {"batch_id": r.batch_id, "tenant_id": r.tenant_id, "as_of_date": r.first.as_of_date,
            "submission_types": [x.submission_type for x in r.rows], "stage": r.stage, "stage_label": r.stage.label,
            "records": r.records, "accepted": r.accepted, "excluded": r.excluded, "overridden": r.overridden,
            "files": [f.bureau_code for f in r.files_done], "requested_by": r.first.requested_by,
            "created_at": r.created_at, "last_activity": r.last_activity, "scheduled": r.scheduled,
            "age_seconds": r.age(now)}


def batch_json(b) -> dict:
    return {"batch_id": b.batch_id, "tenant_id": b.tenant_id, "run_mode": b.run_mode, "as_of_date": b.as_of_date,
            "requested_by": b.requested_by, "requested_at": b.requested_at, "submission_types": b.submission_types,
            "bureau_codes": b.bureau_codes, "status": b.status, "status_counts": b.status_counts}


def dispatch(batch_id: str) -> None:
    """Start the worker for the batch's PENDING rows (after the commit). A failure here is repaired by recovery."""
    try:
        dispatch_batch(svc().dispatcher, svc().requests, batch_id)
    except Exception:  # noqa: BLE001  the row is saved; the recovery job re-dispatches it
        log.exception("Dispatch of batch %s failed; recovery will retry it", batch_id)


def parse_date(value: str | None, label: str) -> date:
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        fail(f"{label}: enter a date as YYYY-MM-DD")


# ---------------------------------------------------------------- session, metadata, health
@bp.get("/me")
def me():
    i = g.identity
    return jsonify(username=i.username, display_name=i.display_name, email=i.email, is_admin=i.is_admin)


@bp.post("/session")
def session_start():
    """Called by the frontend right after sign-in: records the login."""
    if g.identity.email:
        UserRepository(svc().engine).record_login(g.identity.username)
    audit.record(svc().engine, current_user(), "LOGIN", target=current_user(), ip=request.remote_addr)
    return message("Signed in.")


@bp.post("/session/end")
def session_end():
    audit.record(svc().engine, current_user(), "LOGOUT", target=current_user())
    return message("Signed out.")


@bp.get("/meta")
def meta():
    """Choices the pages need: NBFCs, submission types, bureaus, cycles, stages, periods, outcomes, fields."""
    s = svc()
    offered = enabled_types() if not s.tenant else available_types(s.tenants.get(s.tenant))
    return jsonify(
        tenant=s.tenant,
        tenants=[{"tenant_id": t.tenant_id, "display_name": t.display_name, "is_active": t.is_active}
                 for t in s.tenants.list(active_only=False) if not s.tenant or t.tenant_id == s.tenant],
        submission_types=[{"value": t.value, "label": t.value.title(), "enabled": t in offered}
                          for t in SubmissionType],
        bureaus=options(BureauCode), cycles=options(ReportingCycle), stages=options(Stage), periods=options(Period),
        statuses=options(BatchStatus), modes=options(RunMode), outcomes=results.OUTCOME_ORDER,
        override_fields=options(OverrideField), default_as_of=last_month_end())


@bp.get("/health")
def health():
    """Queue health: how long the oldest PENDING request has waited (replaces the worker heartbeat banner)."""
    oldest = svc().requests.oldest_pending()
    waited = utcnow() - oldest if oldest else None
    return jsonify(oldest_pending_at=oldest, waiting_seconds=waited, slow=bool(waited and waited > QUEUE_SLOW))


# ---------------------------------------------------------------- dashboard / tracker / files
def _period() -> Period:
    try:
        return Period(request.args.get("period") or Period.THIS_MONTH.value)
    except ValueError:
        return Period.THIS_MONTH


@bp.get("/dashboard")
def dashboard():
    s, now = svc(), utcnow()
    period, tenant_id = _period(), selected_tenant()
    board = stages.build_dashboard(s.engine, tenant_id, period, now)
    nbfc_status = None
    if not tenant_id:                                    # all NBFCs: who has (not) submitted
        active = s.tenants.list()
        latest = stages.latest_per_tenant(s.engine, [x.tenant_id for x in active])
        nbfc_status = [{"tenant_id": x.tenant_id, "display_name": x.display_name,
                        "latest": request_json(latest[x.tenant_id], now) if x.tenant_id in latest else None}
                       for x in active]
    return jsonify(
        period=period, raised=board.raised, scheduled=board.scheduled,
        stages=[{"value": st, "label": st.label, "count": board.count(st), "oldest_age": board.oldest_age(st)}
                for st in Stage],
        completion_rate=board.completion_rate, acceptance_rate=board.acceptance_rate,
        records=board.total("records"), excluded=board.total("excluded"), overridden=board.total("overridden"),
        files_generated=board.files_generated, records_submitted=board.records_submitted,
        attention=[{"reason": a.reason, **request_json(a.request, now)} for a in board.attention],
        bureaus=board.bureaus, recent=[request_json(r, now) for r in board.requests[:10]], nbfc_status=nbfc_status)


@bp.get("/batches")
def batches():
    """The tracker: runs with filters and paging, or (stage / period given) requests by stage."""
    s = svc()
    stage_arg, period_arg = request.args.get("stage"), request.args.get("period")
    tenant_id = selected_tenant()
    if stage_arg or period_arg:                          # request view (dashboard click-through)
        try:
            stage = Stage(stage_arg) if stage_arg else None
        except ValueError:
            fail(f"Unknown stage {stage_arg}")
        now = utcnow()
        reqs = stages.load_requests(s.engine, tenant_id, _period().start(now))
        if stage:
            reqs = [r for r in reqs if r.stage is stage]
        return jsonify(view="requests", requests=[request_json(r, now) for r in reqs])
    flt = {k: request.args.get(k) or "" for k in ("status", "mode", "bureau", "from", "to")}
    try:
        mode = RunMode(flt["mode"]) if flt["mode"] else None
        bureau = BureauCode(flt["bureau"]) if flt["bureau"] else None
        status = BatchStatus(flt["status"]) if flt["status"] else None
        start = datetime.combine(date.fromisoformat(flt["from"]), time()) if flt["from"] else None
        end = datetime.combine(date.fromisoformat(flt["to"]) + timedelta(days=1), time()) if flt["to"] else None
    except ValueError:
        fail("Check the filters (dates as YYYY-MM-DD)")
    found = s.requests.list_batches(limit=2000, tenant_id=tenant_id, run_mode=mode, bureau_code=bureau,
                                    requested_from=start, requested_to=end)
    if status:
        found = [b for b in found if b.status is status]
    page = max(1, request.args.get("page", 1, type=int))
    return jsonify(view="runs", total=len(found), page=page, pages=max(1, math.ceil(len(found) / TRACKER_PAGE)),
                   batches=[batch_json(b) for b in found[(page - 1) * TRACKER_PAGE:page * TRACKER_PAGE]])


@bp.get("/files")
def files():
    s = svc()
    try:
        bureau = BureauCode(request.args["bureau"]) if request.args.get("bureau") else None
    except ValueError:
        fail("Unknown bureau")
    period = _period() if request.args.get("period") else Period.ALL
    page = max(1, request.args.get("page", 1, type=int))
    rows, total = s.requests.list_files(selected_tenant(), bureau, period.start(utcnow()), TRACKER_PAGE,
                                        (page - 1) * TRACKER_PAGE)
    return jsonify(total=total, page=page, pages=max(1, math.ceil(total / TRACKER_PAGE)),
                   location=s.store.describe(), files=[row_json(r) for r in rows])


# ---------------------------------------------------------------- new request (always Validate, as a draft)
@bp.post("/requests")
def create_request():
    s, b = svc(), body()
    types = b.get("submission_types") or []
    try:
        tenant = s.tenants.get_active(s.tenant or b.get("tenant_id") or "")
    except (TenantNotFoundError, InactiveTenantError):
        fail("Select an active NBFC.")
    as_of = parse_date(b.get("as_of_date"), "As-of date")
    try:
        not_enabled = [t for t in types if SubmissionType(t) not in available_types(tenant)]
        if not_enabled:
            raise RequestValidationError(f"Not set up for this NBFC: {', '.join(not_enabled)} (no mapping file)")
        batch_id = s.requests.create_batch(tenant.tenant_id, as_of, RunMode.VALIDATE, types, (),
                                           b.get("reporting_cycle") or None, current_user(), draft=True)
    except (RequestValidationError, DuplicateActiveRequestError) as exc:
        fail(str(exc))
    except ValueError:
        fail("Check the selections.")
    audit.record(s.engine, current_user(), "RUN_CREATED", tenant_id=tenant.tenant_id, target=batch_id,
                 as_of=as_of, mode=str(RunMode.VALIDATE), types=types, status="DRAFT")
    return message(f"Request {batch_id} created. Add any exclusions or overrides, then submit it for validation.",
                   201, batch_id=batch_id)


# ---------------------------------------------------------------- request (batch) detail
@bp.get("/batches/<batch_id>")
def batch(batch_id: str):
    s = svc()
    rows = s.requests.list_batch(batch_id)
    if not rows or (s.tenant and rows[0].tenant_id != s.tenant):
        fail(f"No request {batch_id}", 404)
    snapshots = []
    for snapshot_id in sorted({r.snapshot_id for r in rows if r.snapshot_id}):
        try:
            snap = s.snapshots.get(snapshot_id)
        except SnapshotNotFoundError:
            continue
        snapshots.append({"snapshot": snap, "records": results.record_counts(s.engine, snapshot_id),
                          "report": results.report(s.engine, snapshot_id, rules.report_hints(snap.submission_type)),
                          "adjusted": applied_summary(s.engine, snapshot_id)})
    validated = {x["snapshot"].snapshot_id for x in snapshots if x["snapshot"].status is SnapshotStatus.VALIDATED}
    generate_from = [{"request_id": r.request_id, "submission_type": r.submission_type, "snapshot_id": r.snapshot_id,
                      "bureaus": [p.bureau_code for p in s.bureaus.list(r.tenant_id, r.submission_type)]}
                     for r in rows if r.run_mode is RunMode.VALIDATE and r.status is RequestStatus.SUCCEEDED
                     and r.snapshot_id in validated]
    tenant = s.tenants.get(rows[0].tenant_id)
    return jsonify(batch_id=batch_id, tenant={"tenant_id": tenant.tenant_id, "display_name": tenant.display_name},
                   rows=[row_json(r) for r in rows], snapshots=snapshots, generate_from=generate_from,
                   active=any(r.status in (RequestStatus.PENDING, RequestStatus.RUNNING) for r in rows))


@bp.post("/batches/<batch_id>/generate")
def generate_from_validation(batch_id: str):
    s, b = svc(), body()
    try:
        source = s.requests.get(int(b["request_id"]))
    except (KeyError, TypeError, ValueError, RequestNotFoundError):
        fail("Choose the validation to generate from")
    if source.batch_id != batch_id or source.run_mode is not RunMode.VALIDATE or source.snapshot_id is None:
        fail("That is not a validation of this request")
    bureaus = b.get("bureau_codes") or []
    adjusted = applied_summary(s.engine, source.snapshot_id)
    try:
        if (adjusted.excluded_accounts or adjusted.overridden_accounts) and not b.get("confirm_adjustments"):
            raise RequestValidationError("Confirm the excluded loans and overrides before generating.")
        if not bureaus:
            raise RequestValidationError("Select at least one bureau")
        active = {p.bureau_code.value for p in s.bureaus.list(source.tenant_id, source.submission_type)}
        missing = [f"{x} ({source.submission_type.value})" for x in bureaus if x not in active]
        if missing:
            raise RequestValidationError(f"No active bureau profile: {', '.join(missing)}")
        new_batch = s.requests.create_batch(source.tenant_id, source.as_of_date, RunMode.GENERATE,
                                            [source.submission_type], bureaus, source.reporting_cycle, current_user(),
                                            snapshot_id=source.snapshot_id)
    except (RequestValidationError, DuplicateActiveRequestError, ValueError) as exc:
        fail(str(exc))
    audit.record(s.engine, current_user(), "GENERATE_FROM_VALIDATION", tenant_id=source.tenant_id, target=new_batch,
                 snapshot_id=source.snapshot_id, bureaus=bureaus)
    if adjusted.excluded_accounts or adjusted.overridden_accounts:
        audit.record(s.engine, current_user(), "ADJUSTMENTS_CONFIRMED", tenant_id=source.tenant_id, target=new_batch,
                     snapshot_id=source.snapshot_id, excluded_loans=adjusted.excluded_accounts,
                     overridden_loans=adjusted.overridden_accounts,
                     request_ids=[r.request_id for r in s.requests.list_batch(new_batch)])
    dispatch(new_batch)
    return message("File generation queued from the validated snapshot.", 201, batch_id=new_batch)


def _row_action(request_id: int, action: str):
    s = svc()
    try:
        req = s.requests.get(request_id)
        getattr(s.requests, action)(request_id)
    except RequestNotFoundError:
        fail(f"No request {request_id}", 404)
    except (InvalidTransitionError, DuplicateActiveRequestError) as exc:
        fail(str(exc), 409)
    audit.record(s.engine, current_user(), "REQUEST_RETRIED" if action == "requeue" else "REQUEST_CANCELLED",
                 tenant_id=req.tenant_id, target=request_id, batch_id=req.batch_id)
    if action == "requeue":
        try:
            s.dispatcher.dispatch([s.requests.get(request_id)])
        except Exception:  # noqa: BLE001  recovery re-dispatches it
            log.exception("Dispatch of request %s failed; recovery will retry it", request_id)
    return message(f"Request {request_id}: {'re-queued' if action == 'requeue' else 'cancelled'}.",
                   batch_id=req.batch_id)


@bp.post("/requests/<int:request_id>/retry")
def retry(request_id: int):
    return _row_action(request_id, "requeue")


@bp.post("/requests/<int:request_id>/cancel")
def cancel(request_id: int):
    return _row_action(request_id, "cancel")


@bp.get("/requests/<int:request_id>/<kind>")
def download(request_id: int, kind: str):
    """Audit the download, then hand out a short-lived S3 link ({"url": ...}). A locally stored file (development)
    is streamed instead."""
    s = svc()
    if kind not in ("file", "exceptions"):
        fail("Unknown download", 404)
    try:
        req = s.requests.get(request_id)
    except RequestNotFoundError:
        fail(f"No request {request_id}", 404)
    uri = req.output_file_path if kind == "file" else req.exceptions_file_path
    if req.status is not RequestStatus.SUCCEEDED or not uri:
        fail(f"Request {request_id} has no {kind} to download (status {req.status.value}). "
             "It may not have finished, or retention has removed the file.", 404)
    if not s.store.owns(uri):
        log.warning("Download refused for request %s: %s is outside the configured store", request_id, uri)
        fail(f"The file for request {request_id} was saved at {uri}, which is not in the storage this app "
             f"is configured for ({s.store.describe()}). Check that the API and the workers use the same "
             "SUBMISSIONS_STORAGE / bucket / prefix settings, or regenerate the file.", 404)
    name = req.output_file_name if kind == "file" and req.output_file_name else uri.replace("\\", "/").rsplit("/", 1)[-1]
    mimetype = "text/csv" if name.endswith(".csv") else "text/plain"
    try:
        url = s.store.download_url(uri, name, mimetype)
    except StoredFileNotFound:
        fail(f"The file {uri} no longer exists in storage (deleted or purged). Regenerate it from the validation.", 404)
    audit.record(s.engine, current_user(), "FILE_DOWNLOADED", tenant_id=req.tenant_id, target=request_id,
                 kind=kind, file=name, location=uri)
    if url:
        return jsonify(url=url, file_name=name)
    return Response(s.store.read_chunks(uri), mimetype=mimetype,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- exceptions: step 2 of a request
def _request_row(batch_id: str):
    """The request's row for the chosen submission type (?type= / body type; default the first)."""
    rows = svc().requests.list_batch(batch_id)
    if not rows or rows[0].run_mode is not RunMode.VALIDATE:
        fail(f"No request {batch_id}", 404)
    wanted = arg("type")
    return rows, next((r for r in rows if r.submission_type.value == wanted), rows[0])


def _require_draft(row) -> None:
    if row.status is not RequestStatus.DRAFT:
        fail("This request was already submitted, so its exceptions are locked. For more exceptions, create a new "
             "request for the same date.", 409)


@bp.get("/exceptions")
def exceptions():
    """Requests waiting for their exceptions (drafts), for the selected NBFC."""
    drafts = [b for b in svc().requests.list_batches(limit=100, tenant_id=selected_tenant())
              if b.status is BatchStatus.DRAFT]
    return jsonify(drafts=[batch_json(b) for b in drafts])


@bp.get("/batches/<batch_id>/exceptions")
def request_exceptions(batch_id: str):
    s = svc()
    rows, row = _request_row(batch_id)
    history = bool(request.args.get("history"))
    frozen, effects = {}, {}
    if row.snapshot_id:
        frozen = s.adjustments.frozen(row.snapshot_id)
        for e in s.adjustments.applied(row.snapshot_id):
            effects.setdefault(e.adjustment_id, []).append(e)
    is_draft = row.status is RequestStatus.DRAFT
    items = []
    for a in s.adjustments.list(AdjustmentScope.of(row), include_removed=history):
        hits = effects.get(a.adjustment_id, [])
        if not a.is_active:
            status = "REMOVED"
        elif is_draft:
            status = "WILL_APPLY"
        elif a.adjustment_id not in frozen:
            status = "WAITING"
        else:
            status = "NOT_FOUND" if frozen[a.adjustment_id] == 0 else "APPLIED"
        old = next((h.old_value for h in hits if h.action == "OVERRIDE"), None)
        items.append({**{k: getattr(a, k) for k in ("adjustment_id", "kind", "field", "override_value", "reason",
                                                     "created_by", "created_at", "removed_by", "removed_at")},
                      "key": a.key, "field_label": a.field.label if a.field else None, "is_active": a.is_active,
                      "status": status, "loans_affected": frozen.get(a.adjustment_id), "old_value": old,
                      "excluded_loans": sum(h.action == "EXCLUDE" for h in hits)})
    tenant = s.tenants.get(row.tenant_id)
    return jsonify(batch_id=batch_id, tenant={"tenant_id": tenant.tenant_id, "display_name": tenant.display_name},
                   rows=[row_json(r) for r in rows], row=row_json(row), is_draft=is_draft, history=history,
                   adjustments=items)


@bp.post("/batches/<batch_id>/exceptions/exclude")
def add_exclusions(batch_id: str):
    s, b = svc(), body()
    _, row = _request_row(batch_id)
    _require_draft(row)
    kind = AdjustmentKind.EXCLUDE_CUSTOMER if b.get("kind") == "customer" else AdjustmentKind.EXCLUDE_ACCOUNT
    try:
        result = s.adjustments.add_exclusions(AdjustmentScope.of(row), kind, parse_keys(b.get("keys") or ""),
                                              b.get("reason"), current_user())
    except AdjustmentError as exc:
        fail(str(exc))
    if result.added:
        audit.record(s.engine, current_user(), "ADJUSTMENT_ADDED", tenant_id=row.tenant_id, target=batch_id,
                     kind=str(kind), keys=result.added[:200], count=len(result.added), reason=b.get("reason") or None)
    what = "customer(s)" if kind is AdjustmentKind.EXCLUDE_CUSTOMER else "loan(s)"
    text = f"{len(result.added)} {what} added to the exclusions."
    if result.already_present:
        text += f" Already excluded: {', '.join(result.already_present[:10])}."
    return message(text, added=result.added, already_present=result.already_present)


@bp.post("/batches/<batch_id>/exceptions/override")
def add_override(batch_id: str):
    s, b = svc(), body()
    _, row = _request_row(batch_id)
    _require_draft(row)
    try:
        field = OverrideField(b.get("field") or "")
    except ValueError:
        fail("Choose the field to override.")
    account = (b.get("account_number") or "").strip()
    try:
        value = parse_override_value(field, str(b.get("value") or ""))
        new_id, replaced = s.adjustments.add_override(AdjustmentScope.of(row), account, field, value,
                                                      b.get("reason"), current_user())
    except AdjustmentError as exc:
        fail(str(exc))
    audit.record(s.engine, current_user(), "ADJUSTMENT_ADDED", tenant_id=row.tenant_id, target=batch_id,
                 kind=str(AdjustmentKind.OVERRIDE), adjustment_id=new_id, account_number=account,
                 field=field.value, value=str(value), replaced=replaced, reason=b.get("reason") or None)
    return message(f"Override saved: {account} {field.label} = {value}"
                   f"{' (replaces the previous one)' if replaced else ''}.", adjustment_id=new_id)


@bp.post("/batches/<batch_id>/exceptions/<int:adjustment_id>/remove")
def remove_adjustment(batch_id: str, adjustment_id: int):
    s = svc()
    _, row = _request_row(batch_id)
    try:
        adj = s.adjustments.get(adjustment_id)
    except AdjustmentNotFoundError:
        fail("No such exception", 404)
    if adj.batch_id != batch_id:
        fail("No such exception", 404)
    _require_draft(row)
    try:
        s.adjustments.remove(adjustment_id, current_user())
    except AdjustmentError as exc:
        fail(str(exc))
    audit.record(s.engine, current_user(), "ADJUSTMENT_REMOVED", tenant_id=adj.tenant_id, target=batch_id,
                 adjustment_id=adjustment_id, kind=str(adj.kind), key=adj.key,
                 field=adj.field.value if adj.field else None)
    return message(f"Removed: {adj.kind.value.replace('_', ' ').lower()} {adj.key}.")


@bp.post("/batches/<batch_id>/submit")
def submit_request(batch_id: str):
    """Step 3: lock the exceptions and queue the validation (DRAFT -> PENDING)."""
    s = svc()
    rows, _ = _request_row(batch_id)
    try:
        s.requests.submit_draft(batch_id)
    except InvalidTransitionError as exc:
        fail(str(exc), 409)
    counts = {r.submission_type.value: len(s.adjustments.list(AdjustmentScope.of(r))) for r in rows}
    audit.record(s.engine, current_user(), "RUN_SUBMITTED", tenant_id=rows[0].tenant_id, target=batch_id,
                 adjustments=counts)
    dispatch(batch_id)
    return message("Submitted for validation. Excluded records are left out of the extract; validation runs on the "
                   "rest. This page refreshes until it finishes.")


@bp.post("/batches/<batch_id>/discard")
def discard_request(batch_id: str):
    """Cancel a draft request (its exceptions stay in the history)."""
    s = svc()
    rows, _ = _request_row(batch_id)
    drafts = [r for r in rows if r.status is RequestStatus.DRAFT]
    if not drafts:
        fail("Only a draft request can be discarded.", 409)
    for r in drafts:
        s.requests.cancel(r.request_id)
    audit.record(s.engine, current_user(), "REQUEST_CANCELLED", tenant_id=rows[0].tenant_id, target=batch_id,
                 batch_id=batch_id, draft=True)
    return message(f"Draft request {batch_id} discarded.")


# ---------------------------------------------------------------- findings -> exceptions of a new draft request
def _draft_for(snap) -> str:
    """The open draft request for the snapshot's NBFC, date and type; created if there is none."""
    s = svc()
    draft = s.requests.open_draft(snap.tenant_id, snap.as_of_date, snap.submission_type)
    if draft:
        return draft
    source = s.requests.list_batch(snap.batch_id) if snap.batch_id else []
    cycle = source[0].reporting_cycle if source else None
    draft = s.requests.create_batch(snap.tenant_id, snap.as_of_date, RunMode.VALIDATE, [snap.submission_type], (),
                                    cycle, current_user(), draft=True)
    audit.record(s.engine, current_user(), "RUN_CREATED", tenant_id=snap.tenant_id, target=draft,
                 as_of=snap.as_of_date, mode=str(RunMode.VALIDATE), types=[snap.submission_type.value],
                 status="DRAFT", source=f"findings of snapshot {snap.snapshot_id}")
    return draft


def _snapshot(snapshot_id: int):
    try:
        snap = svc().snapshots.get(snapshot_id)
    except SnapshotNotFoundError:
        fail(f"No snapshot {snapshot_id}", 404)
    if svc().tenant and snap.tenant_id != svc().tenant:
        fail(f"No snapshot {snapshot_id}", 404)
    return snap


def _finding_account(snapshot_id: int):
    """(snapshot, account_number) for the account_key posted from the Findings page."""
    snap = _snapshot(snapshot_id)
    account = ENTITY_TABLES["account"]
    with svc().engine.connect() as conn:
        number = conn.execute(select(account.c.account_number).where(
            account.c.snapshot_id == snapshot_id, account.c.account_key == (body().get("account_key") or ""))
        ).scalar()
    if not number:
        fail("That loan is not in this snapshot (it may have been purged).", 404)
    return snap, number


def _open_draft(snap) -> str:
    try:
        return _draft_for(snap)
    except (RequestValidationError, DuplicateActiveRequestError) as exc:
        fail(f"Cannot open a new request for this date: {exc}", 409)


@bp.post("/snapshots/<int:snapshot_id>/exclude")
def exclude_from_findings(snapshot_id: int):
    s = svc()
    snap, number = _finding_account(snapshot_id)
    draft = _open_draft(snap)
    (row,) = [r for r in s.requests.list_batch(draft) if r.submission_type is snap.submission_type]
    result = s.adjustments.add_exclusions(AdjustmentScope.of(row), AdjustmentKind.EXCLUDE_ACCOUNT, [number],
                                          f"From findings of snapshot #{snapshot_id}", current_user())
    if result.added:
        audit.record(s.engine, current_user(), "ADJUSTMENT_ADDED", tenant_id=snap.tenant_id, target=draft,
                     kind=str(AdjustmentKind.EXCLUDE_ACCOUNT), keys=result.added, count=1,
                     reason=f"From findings of snapshot #{snapshot_id}")
    return message(f"Loan {number} {'added to' if result.added else 'is already in'} the exclusions of draft request "
                   f"{draft}. Submit that request to validate without it.", batch_id=draft)


@bp.post("/snapshots/<int:snapshot_id>/override")
def override_from_findings(snapshot_id: int):
    """Opens (or creates) the draft; the frontend then shows its Exceptions step with the override pre-filled."""
    snap, number = _finding_account(snapshot_id)
    draft = _open_draft(snap)
    return jsonify(batch_id=draft, type=snap.submission_type, account=number, field=body().get("field") or None)


def _filter(snap) -> results.FindingFilter:
    """Filter from the query string; ?category= is resolved to that category's rule IDs in this snapshot."""
    cat = request.args.get("category") or None
    hints = rules.report_hints(snap.submission_type)
    if cat and cat not in hints.categories:
        fail(f"Unknown category {cat}")
    rule_ids = results.category_rule_ids(svc().engine, snap.snapshot_id, cat, hints) if cat else None
    return results.FindingFilter(rule_ids=rule_ids, **{k: request.args.get(k) or None for k in (
        "rule_id", "outcome", "account_key", "party_key")})


@bp.get("/snapshots/<int:snapshot_id>/findings")
def findings(snapshot_id: int):
    s = svc()
    snap = _snapshot(snapshot_id)
    flt = _filter(snap)
    page = max(1, request.args.get("page", 1, type=int))
    rows, total = results.findings(s.engine, snapshot_id, flt, PAGE_SIZE, (page - 1) * PAGE_SIZE)
    return jsonify(snapshot=snap, report=results.report(s.engine, snapshot_id, rules.report_hints(snap.submission_type)),
                   records=results.record_counts(s.engine, snapshot_id), findings=rows, total=total, filter=flt,
                   page=page, pages=max(1, math.ceil(total / PAGE_SIZE)),
                   overridable=[f.value for f in OverrideField])


@bp.get("/snapshots/<int:snapshot_id>/findings.csv")
def findings_csv(snapshot_id: int):
    """CSV export. On AWS it is written to the jobs bucket (exports/, expires after a day) and handed out as a
    short-lived link, which avoids the API's response size and time limits; locally it is streamed."""
    s = svc()
    snap = _snapshot(snapshot_id)
    name = f"findings-{snap.tenant_id}-{snap.as_of_date:%Y%m%d}-{snapshot_id}.csv"
    chunks = results.findings_csv(s.engine, snapshot_id, _filter(snap))
    audit.record(s.engine, current_user(), "FINDINGS_EXPORTED", tenant_id=snap.tenant_id, target=snapshot_id)
    if s.exports is None:
        return Response(chunks, mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})
    client, bucket = s.exports
    key = f"exports/{secrets.token_hex(16)}/{name}"
    client.put_object(Bucket=bucket, Key=key, Body="".join(chunks).encode(), ContentType="text/csv",
                      ServerSideEncryption="AES256")
    url = client.generate_presigned_url("get_object", ExpiresIn=EXPORT_URL_SECONDS, Params={
        "Bucket": bucket, "Key": key, "ResponseContentDisposition": f'attachment; filename="{name}"'})
    return jsonify(url=url, file_name=name)


# ---------------------------------------------------------------- admin: rules & policies (per NBFC)
def _rule_kind(rule, custom_defs=None) -> str:
    if rule.source == "CUSTOM":
        return "Custom (form)" if custom_defs and rule.rule_id in custom_defs else "Custom SQL"
    if rule.generated:
        return "Generated"
    return {"sql": "SQL", "python": "Python", "cascade": "Record decision"}[rule.kind]


def _rules_type() -> SubmissionType:
    try:
        sub_type = SubmissionType(arg("type") or SubmissionType.CONSUMER.value)
    except ValueError:
        fail("Unknown submission type")
    if sub_type not in enabled_types():
        fail(f"{sub_type} is not available yet")
    return sub_type


def _tenant_required(what: str) -> str:
    tenant_id = selected_tenant()
    if not tenant_id:
        fail(f"Select an NBFC: {what} are per NBFC.")
    return tenant_id


def _rule_json(rule, values) -> dict:
    return {"rule_id": rule.rule_id, "source": rule.source, "entity": rule.entity, "segment": rule.segment,
            "field": rule.field, "outcome": rule.outcome, "enabled": rule.enabled, "kind": rule.kind,
            "message": rule_parameters.render_message(rule.message, values), "sql": rule.sql, "python": rule.python}


@bp.get("/rules")
def rules_page():
    s = svc()
    tenant_id = selected_tenant()
    sub_type = _rules_type()
    custom_defs = custom_rules.definitions(s.engine, tenant_id, sub_type) if tenant_id else {}
    definitions = rule_parameters.builtin_parameters(sub_type)
    overridden = rule_parameters.overrides(s.engine, tenant_id, sub_type) if tenant_id else {}
    values = {n: overridden[n]["value"] if n in overridden else p.default for n, p in definitions.items()}
    entries = rules.catalogue(s.engine, tenant_id or "", sub_type)
    return jsonify(
        tenant_id=tenant_id, submission_type=sub_type,
        rules=[{**_rule_json(e.effective, values), "kind_label": _rule_kind(e.default, custom_defs),
                "default": {"enabled": e.default.enabled, "outcome": e.default.outcome}, "changed": e.changed,
                "policy": e.policy} for e in entries],
        parameters=[{"name": p.name, "type": p.type, "label": p.label, "description": p.description,
                     "used_by": p.used_by, "min": p.min, "max": p.max, "default": p.text(p.default),
                     "value": p.text(values[p.name]), "override": overridden.get(p.name)}
                    for p in definitions.values()],
        custom={rid: {**d.__dict__, "describe": d.describe()} for rid, d in custom_defs.items()},
        checks=custom_rules.CHECKS, operators=custom_rules.OPERATORS, fields=custom_rules.fields(),
        outcomes=[o.value for o in Outcome])


def _definition(b: dict) -> custom_rules.Definition:
    entity, _, field_name = (b.get("field") or "").partition(".")
    other_entity, _, other = (b.get("other_field") or "").partition(".")
    when_entity, _, when = (b.get("when_field") or "").partition(".")
    if other and other_entity != entity:
        raise custom_rules.CustomRuleError("Compare: pick a field of the same record type")
    if when and when_entity != entity:
        raise custom_rules.CustomRuleError("Condition: pick a field of the same record type")
    return custom_rules.Definition(
        name=(b.get("name") or "").strip().upper(), entity=entity, field=field_name,
        check=b.get("check") or "", outcome=b.get("outcome") or "", message=(b.get("message") or "").strip(),
        values=_lines(b.get("values")), min=str(b.get("min") or "").strip() or None,
        max=str(b.get("max") or "").strip() or None, pattern=(b.get("pattern") or "").strip() or None,
        operator=b.get("operator") or None, other_field=other or None, when_field=when or None,
        when_values=_lines(b.get("when_values")))


def _lines(raw) -> list[str]:
    """Values as a list, or typed one per line / comma-separated (spaces inside a value are kept)."""
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    return [v.strip() for v in re.split(r"[\n,]", raw or "") if v.strip()]


@bp.post("/rules/custom/preview")
def preview_custom_rule():
    """Count the findings on the latest validation. Nothing is saved."""
    s = svc()
    tenant_id = _tenant_required("custom rules")
    sub_type = _rules_type()
    try:
        rule = custom_rules.build(tenant_id, _definition(body()))
    except custom_rules.CustomRuleError as exc:
        fail(str(exc))
    snap = s.snapshots.latest(tenant_id, sub_type)
    if snap is None:
        return jsonify(snapshot=None, sql=rule.sql)
    count, examples = custom_rules.preview(s.engine, rule, snap.snapshot_id,
                                           rule_parameters.load_parameters(s.engine, tenant_id, sub_type))
    return jsonify(snapshot=snap, count=count, examples=examples, sql=rule.sql)


@bp.post("/rules/custom")
def save_custom_rule():
    s, b = svc(), body()
    tenant_id = _tenant_required("custom rules")
    sub_type = _rules_type()
    editing = b.get("editing") or None
    try:
        d = _definition(b)
        if editing and d.rule_id(tenant_id) != editing:
            raise custom_rules.CustomRuleError("The name of an existing rule cannot change; add a new rule instead")
        rule = custom_rules.build(tenant_id, d)
        reason = (b.get("reason") or "").strip()
        if not reason:
            raise custom_rules.CustomRuleError("Give a reason for the rule (it is kept in the audit trail)")
        custom_rules.save(s.engine, tenant_id, sub_type, d, current_user(), replace_existing=bool(editing))
    except custom_rules.CustomRuleError as exc:
        fail(str(exc))
    audit.record(s.engine, current_user(), "CUSTOM_RULE_CHANGED" if editing else "CUSTOM_RULE_ADDED",
                 tenant_id=tenant_id, target=rule.rule_id, reason=reason[:500], rule=d.describe(),
                 outcome=d.outcome, message=d.message)
    return message(f"{rule.rule_id} {'updated' if editing else 'added'}: {d.describe()}. "
                   "Applies to requests validated from now on.", rule_id=rule.rule_id)


@bp.post("/rules/custom/<rule_id>/delete")
def delete_custom_rule(rule_id: str):
    s = svc()
    tenant_id = _tenant_required("custom rules")
    d = custom_rules.definitions(s.engine, tenant_id, _rules_type()).get(rule_id)
    if not custom_rules.delete_rule(s.engine, tenant_id, rule_id):
        fail(f"No custom rule {rule_id}", 404)
    rules.clear_policy(s.engine, tenant_id, rule_id)
    audit.record(s.engine, current_user(), "CUSTOM_RULE_DELETED", tenant_id=tenant_id, target=rule_id,
                 rule=d.describe() if d else None, reason=(body().get("reason") or "").strip() or None)
    return message(f"{rule_id} deleted. Earlier findings keep its id.")


@bp.post("/rules/parameters/<name>")
def save_rule_parameter(name: str):
    s, b = svc(), body()
    tenant_id = _tenant_required("parameters")
    sub_type = _rules_type()
    param = rule_parameters.builtin_parameters(sub_type).get(name)
    if param is None:
        fail(f"No parameter {name}", 404)
    before = rule_parameters.load_parameters(s.engine, tenant_id, sub_type)[name]
    reason = (b.get("reason") or "").strip()
    try:
        value = param.parse(b.get("value"))
        if value == before:
            return message(f"{param.label}: nothing changed.")
        if not reason:
            raise rule_parameters.ParameterError(f"{param.label}: give a reason for the change (kept in the audit trail)")
        rule_parameters.set_parameter(s.engine, tenant_id, sub_type, name, b.get("value"), current_user())
    except rule_parameters.ParameterError as exc:
        fail(str(exc))
    audit.record(s.engine, current_user(), "RULE_PARAMETER_CHANGED", tenant_id=tenant_id, target=name,
                 reason=reason[:500], before=param.text(before), after=param.text(value),
                 default=param.text(param.default), rules=list(param.used_by))
    return message(f"{param.label} = {param.text(value)} for {tenant_id}. Applies to requests validated from now on.")


@bp.post("/rules/parameters/<name>/reset")
def reset_rule_parameter(name: str):
    s = svc()
    tenant_id = _tenant_required("parameters")
    sub_type = _rules_type()
    param = rule_parameters.builtin_parameters(sub_type).get(name)
    if param is None:
        fail(f"No parameter {name}", 404)
    before = rule_parameters.load_parameters(s.engine, tenant_id, sub_type)[name]
    if rule_parameters.clear_parameter(s.engine, tenant_id, sub_type, name):
        audit.record(s.engine, current_user(), "RULE_PARAMETER_RESET", tenant_id=tenant_id, target=name,
                     before=param.text(before), after=param.text(param.default))
    return message(f"{param.label}: back to the default ({param.text(param.default)}) for {tenant_id}.")


@bp.post("/rules/<rule_id>")
def save_rule_policy(rule_id: str):
    s, b = svc(), body()
    tenant_id = _tenant_required("rule settings")
    sub_type = _rules_type()
    entry = next((e for e in rules.catalogue(s.engine, tenant_id, sub_type) if e.default.rule_id == rule_id), None)
    if entry is None:
        fail(f"No rule {rule_id}", 404)
    enabled = bool(b.get("enabled"))
    try:
        outcome = Outcome(b.get("outcome") or entry.default.outcome.value)
    except ValueError:
        fail(f"Unknown outcome {b.get('outcome')}")
    reason = (b.get("reason") or "").strip()
    if (enabled, outcome) == (entry.effective.enabled, entry.effective.outcome):
        return message(f"{rule_id}: nothing changed.")
    if not reason:
        fail(f"{rule_id}: give a reason for the change (it is kept in the audit trail).")
    if (enabled, outcome) == (entry.default.enabled, entry.default.outcome):
        rules.clear_policy(s.engine, tenant_id, rule_id)             # back to the default: no override row
    else:
        rules.set_policy(s.engine, tenant_id, rule_id,
                         is_enabled=None if enabled == entry.default.enabled else enabled,
                         outcome=None if outcome == entry.default.outcome else outcome)
    audit.record(s.engine, current_user(), "RULE_POLICY_CHANGED", tenant_id=tenant_id, target=rule_id,
                 reason=reason[:500], before={"enabled": entry.effective.enabled, "outcome": str(entry.effective.outcome)},
                 after={"enabled": enabled, "outcome": str(outcome)},
                 default={"enabled": entry.default.enabled, "outcome": str(entry.default.outcome)})
    return message(f"{rule_id}: {'on' if enabled else 'off'}, outcome {outcome.value} for {tenant_id}. "
                   "Applies to requests validated from now on.")


@bp.post("/rules/<rule_id>/reset")
def reset_rule_policy(rule_id: str):
    s = svc()
    tenant_id = _tenant_required("rule settings")
    before = rules.policies(s.engine, tenant_id).get(rule_id)
    if rules.clear_policy(s.engine, tenant_id, rule_id):
        audit.record(s.engine, current_user(), "RULE_POLICY_RESET", tenant_id=tenant_id, target=rule_id,
                     before={"enabled": before["is_enabled"], "outcome": before["outcome"]},
                     reason=(body().get("reason") or "").strip()[:500] or None)
    return message(f"{rule_id}: back to the default for {tenant_id}.")


# ---------------------------------------------------------------- audit
@bp.get("/audit")
def audit_log():
    s = svc()
    tenant_id = selected_tenant()
    flt = {k: request.args.get(k) or None for k in ("action", "actor", "target")}
    actions, actors = audit.choices(s.engine, tenant_id)
    return jsonify(events=audit.recent(s.engine, 200, tenant_id, flt["action"], flt["actor"], flt["target"]),
                   actions=actions, actors=actors)
