# Bureau Submission Platform: Serverless Architecture Plan

> This replaces the EC2 hosting (decision 19 in `submissions-extract/OVERALL_PLAN.md`).
> All functional requirements stay the same: the request flow, pipeline, validation, formatter, audit and rules.
> Two things change on purpose: the UI becomes a **static frontend**, and sign-in becomes **Cognito SSO with company
> identities**.
> Decisions were made using the AWS serverless and AWS auth guidance.
> Last updated 23-10-2026.

---

## 1. Decisions per component

| Component | Decision | Why |
|---|---|---|
| **Web UI** | **Static frontend**: plain HTML pages + **Alpine.js** (one vendored file, no build step), in a private **S3 bucket behind CloudFront** (Origin Access Control) | No server for the UI at all and no cold start for pages. It deploys independently of the backend (`s3 sync`). There is no Node, npm or bundler to maintain. React was rejected as more upkeep than a 5-user internal tool needs. |
| **Sign-in** | **Amazon Cognito user pool, managed login**, **federated to the company identity provider** (SAML/OIDC). No Cognito passwords and no self sign-up. The browser does the authorization-code + PKCE flow with **oidc-client-ts** (one vendored file; public client, no secret). Tokens are kept in sessionStorage. | Company SSO and MFA come from the company identity provider. The app keeps no passwords. |
| **Who may use the app** | The signed-in e-mail must be **registered and active in `app_user`**, which also holds the admin flag. Otherwise the API returns 403 and audits `LOGIN_DENIED`. | Offboarding and roles stay in the app; the identity provider's app assignment limits who can reach it at all. |
| **API** | **API Gateway HTTP API** + **JWT authorizer** (Cognito issuer, app client audience) on every route, in front of one **Lambda (Flask JSON API via apig-wsgi)** | The authorizer verifies every token before Lambda runs, so there's no in-app JWT verification and no internet access needed. HTTP API is about 70% cheaper than a REST API, and none of REST's extras (WAF, usage plans) are needed. |
| **One origin** | CloudFront routes `/api/*` to the HTTP API and everything else to the S3 bucket | Same origin, so no CORS. Only one URL to give users. |
| **Validate worker** | Lambda (On-Demand), timeout 900 s, reserved concurrency 2 | Runs take under 10 minutes, well inside Lambda's 15-minute ceiling, and traffic is about 10 runs a month. |
| **Generate worker** | A separate Lambda, timeout 300 s, reserved concurrency 4 | Short runs with different sizing. |
| **Starting work** | The API writes a job object `jobs/{validate,generate}/<request_id>.json` to a **jobs bucket**. An **S3 event** invokes the worker **asynchronously** (2 retries, then an SQS dead-letter queue). | It reaches S3 through the **free S3 gateway endpoint**, so there's **no NAT and no interface endpoint**. The atomic claim on the request row makes duplicate deliveries harmless. |
| **Orchestration** | None | Validate → Files is gated by a person (review findings, confirm exceptions). Request status in MySQL is the source of truth. |
| **Scheduled jobs** | **EventBridge Scheduler** → one `jobs` Lambda: schedule (ME/W1–3), retention (nightly), recovery (every 15 min) | Recovery also re-dispatches PENDING rows that waited more than 10 minutes, which covers a lost dispatch. |
| **Admin** | The `jobs` Lambda via `aws lambda invoke`: `migrate`, `users add/email/disable/enable/list` | No servers or Session Manager needed. |
| **Database** | **Existing RDS MySQL, unchanged** | Exclusions and overrides are joined in SQL, so the LMS schemas must be on the app's server. No RDS Proxy: concurrency is capped at about 8 connections. |
| **Files** | **Existing S3 bucket and prefix**. Downloads: audit, then a **60 s presigned link**. The findings CSV is written to the jobs bucket (`exports/`, expires after 1 day) and handed out as a link. | Avoids the Lambda (6 MB) and API Gateway (30 s) response limits. The bucket stays private. |
| **Packaging** | **Zip** on the managed `python3.14` runtime (about 20 MB). No container image or ECR. | Under the zip limits. Built by `sam build`. |
| **Secrets** | Database URL passed at deploy as a NoEcho parameter (read from SSM Parameter Store SecureString by the deploy script) into the Lambda environment, which is encrypted at rest | Free, and needs no SSM endpoint at runtime. |
| **IaC** | **AWS SAM** (`template.yaml`) | |
| **Domain** | Default `*.cloudfront.net` and Cognito prefix domain for now; a company subdomain later (configuration only) | |
| **WAF** | Not for now | |

## 2. Architecture

```
 Browser ── https://<id>.cloudfront.net ─┬─ /*      → S3 (static frontend, private, OAC)
   │                                     └─ /api/*  → API Gateway HTTP API (JWT authorizer) → λ api (Flask JSON)
   └── sign-in: Cognito managed login → company identity provider (SSO)               │ insert row (MySQL)
                                                                                      │ put jobs/<mode>/<id>.json
                                                    jobs bucket ── S3 event (async) ──┴──┬──────────────────────┐
                                                                                         ▼                      ▼
                                                                                 λ validate-worker      λ generate-worker
                                                                                 extract → validate     format → S3 file
 EventBridge Scheduler ──▶ λ jobs  (schedule · retention · recovery/re-dispatch · migrate · users)

 Existing private subnets (RDS VPC): all λ ── RDS MySQL (3306, SG to SG)
                                            └─ S3 gateway endpoint (free) → files bucket + jobs bucket
```

## 3. Cost (about 10 uses a month)

| Item | Monthly |
|---|---|
| Lambda (always-free tier: 1M requests, 400,000 GB-s) | $0 |
| API Gateway HTTP API, CloudFront (always-free 1 TB / 10M requests), S3 | about $0 |
| Cognito (5 federated users; check the current feature plan) | about $0 |
| SQS DLQ, EventBridge Scheduler | about $0 |
| CloudWatch logs (30-day retention) | under $1 |
| **Total** | **about $1**, excluding the existing RDS and files bucket |

There are no fixed hourly charges: no NAT, interface endpoints, load balancer or EC2.

## 4. Status

**Done (local, tested; 390 passed, 1 skipped):**
- Code copied from `submissions-extract` into this new local repo (git init, no remote yet).
- `submissions/web` (Jinja pages, CSRF, password login) **removed**, replaced by `submissions/api` (JSON).
  - SSO identity is read from the authorizer-verified ID token and checked against `app_user`.
  - Presigned downloads, CSV export link, and queue health in place of the worker heartbeat.
- `submissions/dispatch.py`: S3 job objects, or no dispatch locally, where the polling worker still runs.
- `submissions/lambda_handlers.py`: `api`, `worker` (S3 event → run one request; retries when the snapshot is busy), and `jobs`.
- `RequestRepository.claim(id)`, `pending_before`, `oldest_pending`.
- Migration **011**: `app_user.email`; password columns dropped.
- `users` CLI is e-mail based (`add --email`, `email`, `disable`, `enable`, `list`).
- Tests ported to the API; new tests for dispatch, handlers and SSO.

**Done (23-10-2026): static frontend (`frontend/`)**
- Plain HTML + Alpine.js 3.14.9 and oidc-client-ts 3.1.0, both vendored in `frontend/vendor/` (no CDN, no build). `app.css` is carried over.
- Pages: dashboard, new request, exceptions (list + request step), tracker (runs / requests by stage), request, findings, files, audit, rules & policies (parameters, custom rules with preview), callback, signed-out.
- `js/core.js`: Cognito sign-in (code + PKCE; tokens in sessionStorage), API client, page shell, NBFC selector, flash messages, formatting. `config.js` holds `auth: "none"` locally; the deploy writes the Cognito settings.
- Checked locally (SQLite with both mock NBFCs, API + polling worker):
  - the full flow through the API: create → exceptions → submit → validated (2 applied, 1 not found) → confirm → 2 bureau files → download → audit;
  - every page rendered in headless Chrome with data and no errors.
- Not yet checked: clicking through in a real browser, and the Cognito sign-in (needs the deployed user pool).

**Done (23-10-2026): infrastructure as code, not deployed yet**
- `template.yaml` passes `cfn-lint` with no findings. It covers:
  - Cognito (admin-created users, TOTP MFA optional);
  - the HTTP API with a JWT authorizer on every route;
  - CloudFront with the UI bucket (OAC, security headers, `/api/*` to the API);
  - the jobs bucket with S3 → worker triggers;
  - the four Lambdas, with DLQ, Scheduler jobs and alarms by e-mail;
  - a Lambda security group with the RDS ingress rule, and an optional S3 gateway endpoint.
- `deploy/deploy.ps1`:
  - builds the zip (Linux wheels, 38 MB) and runs `aws cloudformation package/deploy`, so no SAM CLI or Docker is needed;
  - writes `config.js` from the stack outputs, then syncs the frontend and invalidates CloudFront;
  - runs the migrations and adds the admin app user.
- EC2 files (Dockerfile, compose, Caddy, cron, update scripts) removed from this repo.

**Done (23-10-2026): live on AWS** at https://dmam8by1hzt4k.cloudfront.net (stack `bureau-submissions`, ap-south-1).
- **Network, created in the console:** Lambda SG `sg-011b04f5bf9fd3826`, RDS ingress, S3 gateway endpoint `vpce-0df20630a12226a09`. The default VPC's subnets are public with no NAT; the Lambdas have no public IP, so they reach only RDS and S3.
- **Fixes found on deploy:**
  - per-function `CodeUri`, because `cloudformation package` ignores Globals;
  - no reserved concurrency: the account limit is 10;
  - Cognito user pool not retained, to avoid orphans on a failed create;
  - DB URL needs `mysql+pymysql://`;
  - DB pool of 5 per Lambda, because the extract uses two connections;
  - Retry/Cancel disabled while busy.
- **Verified end to end by the user:** Cognito sign-in → request → validation (56 / 48 / 8) → findings and CSV → generate → download.
- RUNBOOK, README and `env.example.ps1` rewritten for the serverless setup.

**Next:**
1. First git commit of this repo (remote later).
2. Other existing app users: add e-mails (`users email`) and Cognito invites.
3. ~~Retire the EC2~~ Done 23-10-2026: instance `i-080783c59045ca2ca` terminated, its disk deleted, Elastic IP `52.66.49.134` released. The old https://52-66-49-134.sslip.io address no longer works. Its security group `sg-0945fe12331ab8cd0` and that group's 3306 rule on the RDS security group were removed too.
4. Optional:
   - RDS not publicly accessible, and remove the `49.43.251.101/32` rule;
   - deploy with an IAM user/role instead of root;
   - a $5 budget alert;
   - a company subdomain.

## 5. Open questions

1. **Identity provider (decided 23-10-2026): AWS only for now.**
   - Users are in the Cognito user pool itself: an admin creates them (e-mail invite), there's no self sign-up, and TOTP MFA is available.
   - A company identity provider (for example IAM Identity Center or Entra ID over SAML) can be federated later as a Cognito setting, with no code change.
2. Existing `app_user` rows need e-mail addresses (`users email <username> <email>`) before switching over.
