# Bureau Submissions

Generates credit bureau submission files (UCRF consumer now; commercial and NeSL later) for one NBFC. Each customer
has their own AWS account with their LMS on RDS; this app is deployed alongside it (same `bureau-submissions` stack,
app tables on the same RDS server) and serves that one NBFC (`SUBMISSIONS_TENANT`). The steps:
1. A user creates a request.
2. They add exceptions (excluded loans, overrides), if any.
3. They validate the request.
4. They generate and download one file per bureau.

It runs serverless on AWS:
- a static frontend (S3 + CloudFront) with Cognito sign-in;
- a JSON API and worker Lambdas over the existing RDS MySQL.

## Documents

| Document | For |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Scope, decisions, AWS architecture, data model, request flow, UI, security, cost, code layout |
| [docs/PIPELINE.md](docs/PIPELINE.md) | How a file is produced: canonical model, NBFC mappings, snapshot, validation rules, formatter |
| [RUNBOOK.md](RUNBOOK.md) | Operating the app on AWS: **deployment rules**, users, scheduled jobs, monitoring, troubleshooting |
| [ONBOARDING.md](ONBOARDING.md) | Adding a new NBFC |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Open work and inputs still needed |
| [docs/specs/UCRF_Consumer_v3.74_Spec.md](docs/specs/UCRF_Consumer_v3.74_Spec.md) | The consumer file specification |

## Setup

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
Copy-Item env.example.ps1 env.ps1      # fill in the database URL; env.ps1 is not committed
. .\env.ps1
```

## Database

```powershell
.\.venv\Scripts\python -m submissions.migrate                           # applies migrations/NNN_*.sql once each
.\.venv\Scripts\python -m submissions.tenants.seed                      # mock tenants nbfc_001, nbfc_002 (two layouts; a deployment uses one)
.\.venv\Scripts\python -m submissions.bureaus.seed nbfc_001 nbfc_002   # PLACEHOLDER bureau profiles per tenant
```

- **Seed order:** tenants must exist before their bureau profiles (foreign key).
- **Schema changes:** a new numbered file in `migrations/`; never edit an applied one. If you change a platform table, also update its definition in `submissions/*/tables.py`.
- **Canonical model changes:** made only in `submissions/canonical/model.yaml`. Bump `canonical_version` and add a migration. `python -m submissions.canonical.generate --out <file>` emits the full CREATE script as a reference.

Mock LMS data: `mock_data/mock_lms.sql` creates the schemas `nbfc_001` (base layout) and `nbfc_002` (customised layout), with the same 52 test scenarios:
`.\.venv\Scripts\python mock_data/generate_mock_data.py --load "mysql+pymysql://user:pass@host:3306/"`.

## Local development

The API serves the pages too when `SUBMISSIONS_FRONTEND_DIR=frontend`. `SUBMISSIONS_TENANT` picks the NBFC
(`nbfc_001` base layout, `nbfc_002` customised layout). Locally there is no sign-in
(`SUBMISSIONS_AUTH=none`). A polling worker runs the submitted requests; on AWS, worker Lambdas do this.

```powershell
.\.venv\Scripts\python -m submissions.api        # http://127.0.0.1:5000 (pages + /api)
.\.venv\Scripts\python -m submissions.worker     # second terminal; --once to process what is pending and exit
```

Generated files go to `SUBMISSIONS_OUTPUT_DIR` (`output/`) with `SUBMISSIONS_STORAGE=local`, or to S3 with `s3` and the
bucket settings. Existing files are never overwritten.

## NBFC mappings

`clients/_base/consumer.yaml` maps the standard LMS layout. Each NBFC's `clients/<tenant>/consumer.yaml` extends it and
lists only the differences (format: `submissions/adapters/mapping.py`; step by step: [ONBOARDING.md](ONBOARDING.md)).

```powershell
.\.venv\Scripts\python -m submissions.adapters.check clients/nbfc_002/consumer.yaml --schema nbfc_002 --as-of 2026-09-30
.\.venv\Scripts\python -m submissions.adapters.compiler clients/nbfc_002/consumer.yaml --schema nbfc_002 --out clients/nbfc_002/generated/consumer
```

## Tests

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\cfn-lint -- template.yaml          # when template.yaml changed
```

To also check that the SQL migrations match the code's table definitions, run the tests against an **empty** scratch MySQL database:
`$env:SUBMISSIONS_TEST_MYSQL_URL = "mysql+pymysql://user:password@localhost:3306/submissions_test"`, then `pytest tests/test_migrate.py`.

## Deploying

```powershell
.\deploy\deploy.ps1 -FrontendOnly    # frontend/ changed
.\deploy\deploy.ps1 -BackendOnly     # submissions/, clients/, migrations/, template.yaml changed
.\deploy\deploy.ps1                  # both (backend first)
```

Rules (what goes where, migrations, secrets, rollback): [RUNBOOK.md "Deploying"](RUNBOOK.md#deploying).
