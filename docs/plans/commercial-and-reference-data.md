# Plan: Commercial UCRF + per-type modules + reference data in the database

Status as of 24-10-2026. Phase 1 + 1b done, **not committed**; 434 tests pass (1 skipped: MySQL parity), consumer
golden files byte-identical. Next: phase 1c (or straight to phase 2, see below).
Spec: [docs/specs/Commercial_UCRF_V3_10.md](../specs/Commercial_UCRF_V3_10.md).

## Decisions (agreed)

| # | Topic | Decision |
|---|---|---|
| 1 | Canonical model | **One** model for all submission types (`submissions/canonical/model.yaml`): entities, columns, types, keys only. No type knowledge (no `required`, no file field refs, no file codes). Snapshot **tables**, not views. |
| 2 | Canonical values | Code columns hold **standard values** (e.g. `FEMALE`, `HOUSING_LOAN`, `MAHARASHTRA`). Mappings translate client codes in; each file writer translates out. |
| 3 | Product / status taxonomies | **Option (a)**: one neutral taxonomy per concept (e.g. one product list covering consumer account types *and* commercial credit types); each type translates to its own codes. |
| 4 | Modules per type | Separate, no overlaps: `submissions/types/<type>/` with `codes.yaml`, `requirements.yaml`, `rules.yaml`, `layout.yaml`, `pipeline.py`. A new type (NeSL, MFI) = new folder + reference rows. |
| 5 | Mappings | One file per type per NBFC: `clients/<tenant>/consumer.yaml`, `commercial.yaml` (+ `clients/_base/<type>.yaml`). Commercial vs consumer is usually a `where:` filter on the same LMS tables; a type may also use different source tables. |
| 6 | Reads / writes | One extract per submission type → own snapshot → own rule pack → one file per bureau. |
| 7 | **Master of reference data** | **The database**, editable without a deploy (see below). Logic stays in the repo. |
| 8 | Commercial file | Pipe-delimited, CRLF, **trailing `|` at the end of every line**. LMS has all segments (BS/AS/RS/CR/GS/SS/CD). |
| 9 | Commercial member IDs | Placeholders in `bureau_profile` (table, editable without deploy). |

### Data in the database, logic in the repo

| Kind | Examples | Master |
|---|---|---|
| Reference data | Translations (`FEMALE → 1`), code groups (card types), PIN ranges, bureau member IDs, rule parameters | **Database** |
| Canonical code lists | `ref_code` values | **Database**, guarded: adding is free; renaming/deleting a value used by rules or mappings is blocked |
| Logic | Rule SQL, record decision (cascade), file layouts, canonical tables | **Repo** (tests + golden files, deploy) |

Safeguards to build with DB-master:
1. Seed is **insert-missing only** (YAML = initial data for a new installation / customer account; never overwrites edits).
2. Admin page **Reference data** (like Rules & policies) with checks: translation points at an existing canonical value; output code fits the spec length; canonical values used by rules cannot be deleted.
3. Every change audited (`audit_event`: who, when, old → new).
4. **Freeze per snapshot**: validation records the translations it used; file generation uses that copy, so the file matches what was validated.
5. Export to YAML (review, or copy to another customer account).
6. No reference values hard-coded in Python: PIN ranges from `ref_state_pin`; phone/ID/state constants in checks become rule settings or `ref_code_group` rows.

## Phases

| Phase | Content | DDL | State |
|---|---|---|---|
| 1 | Generalise engines: record keys in model, pack discovery / prefix / categories / cascade from the pack | No | **Done** (uncommitted), 429 tests passed at that point |
| 1b | Per-type folders, canonical values, reference tables, consumer rewritten — consumer files byte-identical (golden tests) | Yes (012) | **Done** (uncommitted), 434 passed |
| 1c | DB-master safeguards 1–6 above | Yes (snapshot translation copy, maybe audit fields) | **1 done** (seed insert-missing). Left: 4 (freeze per snapshot), 6 (no hard-coded reference values), then 2, 3, 5 (admin page) after commercial |
| 2 | Commercial model: extend `c_party` / `c_party_address` / `c_account`; new `c_relationship`, `c_guarantor`, `c_security`, `c_cheque_dishonour`; neutral product/status taxonomy (union of both specs); commercial mock data + `clients/_base/commercial.yaml` | Yes | Not started |
| 3 | `types/commercial/rules.yaml` + cascade (record = facility × borrower via `c_account_holder`; borrower reject rejects all its facilities; RS optional for credit type 9026) | Seed rows | Not started |
| 4 | Generic pipe-delimited engine (`formats/delimited/`) + `types/commercial/layout.yaml`; golden tests; TS counts; CRLF + trailing pipe | No | Not started |
| 5 | Register commercial pipeline, bureau profiles (placeholder member IDs, `Commercial-<cycle>…` names), report categories | Seed rows | Not started |

## Phase 1b: what was built (24-10-2026)

- `model.yaml`: neutral code values (exact inverses of the consumer codes); no `required` / `ucrf` on columns; `keys:` per entity.
- `submissions/types/`: loader for `types/*/codes.yaml` + `requirements.yaml`; `types/consumer/` holds codes, requirements, rules, layout, `file.py` (was `formats/ucrf_consumer`), `pipeline.py` (`PIPELINE`; `pipeline/__init__.py` discovers type folders).
- Reference tables `ref_code_translation`, `ref_code_group` (migration 012); `submissions/reference.py` seeds **insert-missing only** after migrations and provides `active_translations()`.
- Layout key `translate: <code_list>`; `when`, `default`, formatter args and the history asset-class map use canonical values. Translations are read from the DB at file time (**not yet frozen per snapshot**: 1c item 4).
- Mappings per type: `clients/{_base,_template,<t>}/consumer.yaml` with `submission_type: CONSUMER`; lookups give canonical values, checked against the column's code list; required columns from `requirements.yaml`; `mapping_file()` resolves `tenant.mapping_path` as the client folder (an old `…/mapping.yaml` value still works). New tenants copy every `_template/*.yaml`. Compiled SQL under `clients/<t>/generated/consumer/`.
- `canonical/generate.py` prints DDL only (no INSERTs, no `--check`); the "003 matches the model" tests were removed.
- Validation: REQUIRED rules from `requirements.yaml`; ENUM rules check active `ref_code_translation` rows for the snapshot's type.
- Behaviour note: a client code that equals a canonical value (e.g. nbfc_002 `MALE`) passes through as valid without a lookup.
- Docs updated: PIPELINE, ARCHITECTURE (reference data), README, ONBOARDING, RUNBOOK, CLAUDE.md.

## Next steps

1. Review and commit 1b (big diff: moves under `submissions/types/`, `clients/*/consumer.yaml`).
2. 1c item 4: freeze the translations used per snapshot at validation; file generation reads that copy (DDL: new table, e.g. `snapshot_code_translation`).
3. 1c item 6: remaining hard-coded reference values in checks (phone/ID/state constants) → rule settings or `ref_code_group`.
4. Phase 2 (commercial model) onwards. Admin page (1c items 2, 3, 5) after commercial.

## Deploy notes (when 1b ships)

- DDL: migration 012 **has been executed (24-10-2026)**: frozen, never edit it; further DDL starts at 013. Flag later ones before deploying.
- Existing snapshots hold consumer file codes, not canonical values: re-validate (new request) before generating files from them.
- RDS `tenant.mapping_path` values point at `…/mapping.yaml`: the code reads that as the folder, so no data update is needed (optionally set them to `clients/<t>`).
- The first `migrate` after deploying 012 fills the new reference tables (seed inserts missing rows).
