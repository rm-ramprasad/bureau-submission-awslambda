# Runbook

Day-to-day operation of the bureau submission platform on AWS (serverless, ap-south-1, stack `bureau-submissions`).
Design: [SERVERLESS_PLAN.md](SERVERLESS_PLAN.md). Commands run from the project root in PowerShell, after `aws login`.

**App:** https://dmam8by1hzt4k.cloudfront.net (a company subdomain can be added later).

## What runs where

| Piece | AWS resource | Notes |
|---|---|---|
| Pages | S3 bucket (private) + CloudFront | `frontend/`, plain HTML + Alpine.js |
| Sign-in | Cognito user pool `bureau-submissions-users`, domain `bureau-submissions-openterrace` | Users are created by an admin; optional authenticator-app MFA |
| API | CloudFront `/api/*` → API Gateway HTTP API (JWT authorizer) → Lambda `ApiFunction` | Flask JSON API, 29 s limit |
| Validation | Lambda `ValidateWorker` (15 min) | Started by `jobs/validate/<id>.json` in the jobs bucket |
| File generation | Lambda `GenerateWorker` (5 min) | Started by `jobs/generate/<id>.json` |
| Scheduled and admin jobs | Lambda `JobsFunction` + EventBridge Scheduler | Recovery every 15 min, retention 02:00, ME/W1/W2/W3 runs 06:00 (India time) |
| Database | Existing RDS `analytics-poc-mysql-db` | URL in SSM `/bureau-submissions/database-url` (SecureString) |
| Generated files | `s3://opta-s3-demo/bureau-submissions/<tenant>/<batch>/` | Downloads use 60-second links |
| Failed runs | SQS dead-letter queue + e-mail alarm | |

Network (created in the console, not by the stack):
- the Lambdas use security group `sg-011b04f5bf9fd3826` in subnets `subnet-085829c8efdda82d2`, `subnet-03d60377cf847353d`;
- the RDS security group `sg-0fe6446f73a2841c2` allows 3306 from it;
- S3 gateway endpoint `vpce-0df20630a12226a09` on route table `rtb-06e3737d777c15ac0`.

There is no NAT: the Lambdas reach only RDS and S3.

## Deploying

| Change | Command | Time |
|---|---|---|
| Code, template, migrations | `.\deploy\deploy.ps1` | 2–5 min |
| Pages only (`frontend/`) | `.\deploy\deploy.ps1 -FrontendOnly` | under a minute |

`deploy.ps1`:
1. builds the Lambda zip (Linux wheels from `deploy/requirements-lambda.txt`);
2. reads the database URL from SSM and deploys the stack with `aws cloudformation package/deploy`;
3. writes `config.js` from the stack outputs, uploads `frontend/` and refreshes CloudFront;
4. applies pending migrations and makes sure the admin app user exists.

Settings that are not secret are in `deploy/stack-params.json`. No SAM CLI or Docker is needed.

- **Database URL format:** `mysql+pymysql://user:password@host:3306/db`. URL-encode `@ : / ? # % &` in the password.
- **To change the database URL:** update the SSM parameter, then run `.\deploy\deploy.ps1`; the Lambdas only pick it up at deploy time.
- **Rollback:** check out the previous commit and run `.\deploy\deploy.ps1`. Migrations are not undone.
- **If a first deploy fails** (stack in `ROLLBACK_COMPLETE`), delete the stack before deploying again:
  `aws cloudformation delete-stack --stack-name bureau-submissions`.

## Users

A user needs **both**:
- a Cognito login, which is how they sign in;
- an app user with the **same e-mail**, which decides whether they may use the app and whether they are an admin.

Otherwise the app shows "not registered" (audited as `LOGIN_DENIED`).

```powershell
$fn = aws cloudformation describe-stacks --stack-name bureau-submissions --query "Stacks[0].Outputs[?OutputKey=='JobsFunctionName'].OutputValue" --output text
$pool = aws cloudformation describe-stacks --stack-name bureau-submissions --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text

# 1. Cognito login: e-mails a temporary password, valid for 7 days
aws cognito-idp admin-create-user --user-pool-id $pool --username asha.k@company.in `
  --user-attributes Name=email,Value=asha.k@company.in Name=email_verified,Value=true --desired-delivery-mediums EMAIL

# 2. App user (add --admin for an administrator)
aws lambda invoke --function-name $fn --cli-binary-format raw-in-base64-out `
  --payload '{"job":"users","args":["add","asha.k","--email","asha.k@company.in","--name","Asha K"]}' out.json; Get-Content out.json
```

| Task | How |
|---|---|
| Resend the invite (new temporary password) | `aws cognito-idp admin-create-user --user-pool-id $pool --username <email> --message-action RESEND --desired-delivery-mediums EMAIL` |
| Forgotten password | The user clicks "Forgot your password?" on the sign-in page (code by e-mail) |
| Leaver | `aws cognito-idp admin-disable-user --user-pool-id $pool --username <email>`, and app `{"job":"users","args":["disable","asha.k"]}` |
| List app users | `{"job":"users","args":["list"]}` |
| Set the e-mail of an existing app user | `{"job":"users","args":["email","asha.k","asha.k@company.in"]}` |

Only the e-mail from the **newest** invite works; each resend replaces the temporary password.

## Scheduled runs

EventBridge Scheduler runs the `JobsFunction` (India time):

| When | Job |
|---|---|
| Every 15 minutes | `recovery`: frees runs whose Lambda died, re-starts PENDING runs that waited more than 10 minutes |
| Daily 02:00 | `retention` (90 days): purges snapshot rows, findings and files; summaries are kept |
| 2nd of the month, 06:00 | `schedule ME`: validation runs for every active NBFC (as of last month-end) |
| 10th / 17th / 24th, 06:00 | `schedule W1` / `W2` / `W3` |

Scheduled runs are always **validations**: the team reviews findings, then generates files in the app.

Run a job by hand: `aws lambda invoke --function-name $fn --cli-binary-format raw-in-base64-out --payload '<json>' out.json`, with
- `{"job":"schedule","cycle":"ME","as_of":"2026-09-30","tenants":["nbfc_001"]}`
- `{"job":"retention","days":90,"dry_run":true}`
- `{"job":"recovery"}`
- `{"job":"migrate"}`

## Monitoring and troubleshooting

- **Alarm e-mails** go to the admin e-mail. They cover a failed worker run (dead-letter queue), API errors and scheduled-job errors. The SNS subscription must be confirmed once.
- **Logs** (CloudWatch, 30 days): `aws logs tail /aws/lambda/<function name> --since 1h --follow`. Function names are in the stack's resources. API access logs are in `/aws/apigateway/bureau-submissions`.
- **The app sidebar** says "Runs waiting …" when a submitted run has waited more than 10 minutes.

| Symptom | Cause / action |
|---|---|
| "Incorrect username or password" at first sign-in | A temporary password from an older invite. Resend the invite and use the newest e-mail |
| "not registered for Bureau Submissions" | Add the app user with the same e-mail (see Users) |
| Run stays PENDING | Recovery re-starts it within 15 minutes. If not, check the `ValidateWorker` / `GenerateWorker` logs and the dead-letter queue |
| `QueuePool limit … reached` | Too many connections per Lambda (`submissions/lambda_handlers.py`, `engine()`) |
| `Could not parse SQLAlchemy URL` | The SSM database URL lacks `mysql+pymysql://` or has unencoded characters. Fix it, then redeploy |
| `Can't connect to MySQL server` / timeouts | The RDS security group lost the 3306 rule from `sg-011b04f5bf9fd3826` |
| S3 calls time out | The S3 gateway endpoint is missing from the route table |
| "Cannot move request from PENDING to PENDING" | A double click on Retry: the run was already re-queued |
| `Snapshot build failed: <entity>: ...` | Mapping SQL error: `python -m submissions.adapters.check clients/<tenant>/mapping.yaml --schema <schema>`, fix, Retry |
| `No bureau profile for …` | Add the bureau's profile for that NBFC (`bureau_profile`) |
| Many `UCRF.ENUM.*` findings | Client codes missing from the mapping lookups (`python -m submissions.onboarding.dry_run --tenant <id>`) |
| "Already open (draft, pending or running)" | One open request per NBFC, date and type: submit or discard the draft |
| `… must be on the app's MySQL server` | Exclusions and overrides are joined in SQL: the LMS schema must be on the app's MySQL server |

Lambda concurrency: this account's limit is **10** concurrent Lambda executions in total, so none are reserved per function. More users or NBFCs: request a higher "Concurrent executions" quota in Service Quotas (free).

## Audit

The **Audit** page (table `audit_event`) records:
- sign-ins (`LOGIN`, `LOGOUT`, `LOGIN_DENIED`);
- requests, exceptions, confirmations, downloads and CSV exports;
- rule and parameter changes, with reasons;
- scheduled runs, recovery and purges;
- user administration (`USER_ADDED`, `USER_DISABLED`, …; actor `admin-lambda`).

## Local development

```powershell
$env:SUBMISSIONS_DATABASE_URL = "mysql+pymysql://user:pass@localhost:3306/submissions"
$env:SUBMISSIONS_AUTH = "none"; $env:SUBMISSIONS_FRONTEND_DIR = "frontend"
.\.venv\Scripts\python -m submissions.api        # http://127.0.0.1:5000 (pages + API)
.\.venv\Scripts\python -m submissions.worker     # second terminal: polls for PENDING runs
.\.venv\Scripts\python -m pytest
```

Locally nothing is dispatched to S3 (no `SUBMISSIONS_JOBS_BUCKET`); the polling worker picks runs up.

## Migrations so far

| File | Adds |
|---|---|
| 001–005 | Requests, tenants, canonical model (`c_*`), validation, operations (heartbeat, audit) |
| 006 | Exclusions and overrides: `submission_adjustment`, frozen `snapshot_adjustment`, `snapshot_adjustment_effect`, view `v_snapshot_adjustment`, request counts |
| 007 | `submission_adjustment.batch_id`: exceptions belong to a request (DRAFT status) |
| 008 | `validation_parameter`: per-NBFC rule parameter overrides |
| 009 | `validation_rule.definition` / `created_by`: custom rules built without SQL |
| 010 | `app_user`: in-app login |
| 011 | SSO: `app_user.email`; password columns removed |

A new migration is a new numbered file in `migrations/`; `deploy.ps1` applies it. Never edit an applied file.
