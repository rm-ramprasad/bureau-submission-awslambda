# Roadmap

Open work only. Done work is described in [ARCHITECTURE.md](ARCHITECTURE.md) and [PIPELINE.md](PIPELINE.md), and is in
the git history.

## Inputs needed

| Item | What is needed | Blocks |
|---|---|---|
| Base LMS schema | The real standard LMS schema and one NBFC customisation sample, to write `clients/_base/consumer.yaml` for real and make the mock data realistic | Onboarding real NBFCs |
| Bureau values per NBFC | Real member IDs, header tags and file-name formats (`bureau_profile`; placeholders today) | First live submission |
| CIC sample file | Re-confirm the encoding decision: segment tags without a length prefix (`PNN01`), no separator or line break between records (`encoding:` in `submissions/types/consumer/layout.yaml`). If a bureau differs, add a per-bureau layout override (`extends:`) | First live submission |
| Re-runs and retention | Keep every version of a generated file, or only the latest? Retention period (90 days today) | — |
| Commercial: location type for individuals | Individuals reported commercially (constitution 90) have consumer-style addresses (`PERMANENT`, `RESIDENCE` …) with no commercial location type (8.4); today untranslated, so flagged. Which code should they get? | Commercial for individual borrowers |
| Commercial: weekly / fortnightly / daily repayment | No code in 8.18; reported as 08 Others (`types/commercial/codes.yaml`). Confirm with the CIC | — |
| Commercial: cheque dishonoured on a closed account | §7.8 says report it; catalogue 8.20 has only 01 Insufficient Funds. `ACCOUNT_CLOSED` is untranslated (flagged). Which code? | — |
| Commercial: CR 26 Open / Closed by Payment | Derived from `date_closed` when no special status is set (layout, phase 4). Confirm this matches how the CIC reads it | — |
| Commercial: CR 35 Wilful Default | 1 when `wilful_default_date` is set or the status is a consumer-style wilful status. Confirm with an NBFC how wilful default is held in the LMS | — |
| TH history | Is a one-time historical load of account history needed? If so: should validation findings on history rows (e.g. an invalid asset class) drop TH fields like other segments? Today TH is written as loaded (`drops: false` and `check: not_null` in the layout) | — |

## Product

- **NBFCs & bureaus page:** a read-only view of tenants and bureau profiles (the sidebar shows it as "soon").
- **Findings trends:** trends across runs from the kept `validation_summary`.
- **Commercial pipeline:** needs its spec.
- **NeSL pipeline:** its own spec.

## Operations and AWS

- **Users:** add e-mails for any existing app users (`users email`) and send their Cognito invites (RUNBOOK "Users").
- **Deploy from GitHub:** a GitHub Actions workflow with an IAM role through OIDC (no stored keys):
  - `frontend/**` changes run `deploy.ps1 -FrontendOnly`;
  - other changes run `-BackendOnly`.
  This also replaces deploying as the root user.
- **Hardening:**
  - make the RDS instance not publicly accessible;
  - remove the `49.43.251.101/32` rule from its security group;
  - add a monthly budget alert (for example $5).
- **Company subdomain:** an ACM certificate in us-east-1, a CloudFront alias, and the Cognito callback URLs.
- **Company identity provider:** federate it in Cognito (SAML/OIDC) when needed; no code change.
- **More capacity:** if usage grows, request a higher Lambda concurrency quota (10 today).
