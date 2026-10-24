-- 013: the translations a snapshot was validated with. Validation copies the type's active rows of
-- ref_code_translation here; the generated code rules and the file writer read this copy, so an edit to
-- ref_code_translation after validation cannot change a file. Snapshots validated before this migration have no
-- copy: re-validate them (new request) before generating files.

CREATE TABLE snapshot_code_translation (
    snapshot_id   BIGINT       NOT NULL,
    code_list     VARCHAR(40)  NOT NULL,
    code          VARCHAR(40)  NOT NULL COMMENT 'Canonical value',
    output_code   VARCHAR(20)  NOT NULL,
    PRIMARY KEY (snapshot_id, code_list, code),
    CONSTRAINT fk_snapshot_code_translation_snapshot FOREIGN KEY (snapshot_id)
        REFERENCES extract_snapshot (snapshot_id) ON DELETE CASCADE
) COMMENT = 'Active translations frozen when the snapshot was validated: the code rules and the file both use this copy, so a file matches what was validated (kept after retention: no personal data)';
