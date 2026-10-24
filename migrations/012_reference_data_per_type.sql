-- 012: reference data per submission type. The c_* tables now hold canonical (standard) values such as FEMALE or
-- HOUSING_LOAN instead of consumer file codes. ref_code holds the canonical values, ref_code_translation what each
-- submission type writes for them, ref_code_group named sets of values a type's rules use.
-- The rows are not inserted here: submissions.reference seeds them right after the migrations (jobs Lambda
-- `migrate`, python -m submissions.migrate) from model.yaml and submissions/types/<type>/codes.yaml.
-- Existing snapshots hold the old consumer codes: re-validate them (new request) before generating files.

DELETE FROM ref_code;
DELETE FROM ref_state_pin;

ALTER TABLE ref_code
    MODIFY COLUMN code VARCHAR(40) NOT NULL,
    COMMENT = 'Canonical code lists: the standard values the c_* tables hold (model.yaml)';

ALTER TABLE ref_state_pin
    MODIFY COLUMN state_code VARCHAR(40) NOT NULL,
    COMMENT = 'Valid first two PIN digits per canonical state (model.yaml)';

CREATE TABLE ref_code_translation (
    submission_type   VARCHAR(20)  NOT NULL,
    code_list         VARCHAR(40)  NOT NULL,
    code              VARCHAR(40)  NOT NULL COMMENT 'Canonical value (ref_code)',
    output_code       VARCHAR(20)  NOT NULL COMMENT 'What this submission type''s file holds',
    is_active         BOOL         NOT NULL COMMENT '0 = reserved by the spec: not reportable',
    PRIMARY KEY (submission_type, code_list, code)
) COMMENT = 'Canonical value -> file code per submission type (types/<type>/codes.yaml). No row = not reportable';

CREATE TABLE ref_code_group (
    submission_type   VARCHAR(20)  NOT NULL,
    group_name        VARCHAR(40)  NOT NULL,
    code              VARCHAR(40)  NOT NULL COMMENT 'Canonical value',
    PRIMARY KEY (submission_type, group_name, code)
) COMMENT = 'Named sets of canonical values a submission type''s rules use (types/<type>/codes.yaml)';
