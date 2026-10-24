-- 014: canonical model 1.1 (commercial). New columns on c_party, c_party_address, c_account and new tables
-- c_relationship, c_guarantor, c_security, c_cheque_dishonour. All nullable: consumer snapshots leave them NULL.
-- Reference rows (new code lists, commercial translations) are seeded after the migrations (submissions.reference).

ALTER TABLE c_party
    ADD COLUMN short_name VARCHAR(20) COMMENT 'Business borrower short name',
    ADD COLUMN legal_constitution VARCHAR(40) COMMENT 'codes: legal_constitution Commercial borrowers',
    ADD COLUMN business_category VARCHAR(40) COMMENT 'codes: business_category',
    ADD COLUMN industry_type VARCHAR(40) COMMENT 'codes: industry_type',
    ADD COLUMN incorporation_date DATE,
    ADD COLUMN activity_class_1 VARCHAR(5) COMMENT 'RBI BSR activity / occupation classification',
    ADD COLUMN activity_class_2 VARCHAR(5),
    ADD COLUMN activity_class_3 VARCHAR(5),
    ADD COLUMN hsn_code VARCHAR(20),
    ADD COLUMN sales_amount NUMERIC(20, 2) COMMENT 'Sales of the previous financial year',
    ADD COLUMN sales_year DATE COMMENT 'Financial year of sales_amount (any date in it)',
    ADD COLUMN employee_count INTEGER,
    ADD COLUMN credit_rating VARCHAR(10),
    ADD COLUMN rating_agency VARCHAR(40) COMMENT 'codes: rating_agency',
    ADD COLUMN rating_date DATE,
    ADD COLUMN rating_expiry_date DATE;

ALTER TABLE c_party_address
    ADD COLUMN city VARCHAR(40),
    ADD COLUMN district VARCHAR(40),
    ADD COLUMN country VARCHAR(40) COMMENT 'codes: country';

ALTER TABLE c_account
    ADD COLUMN branch_code VARCHAR(15) COMMENT 'Member branch that granted the facility',
    ADD COLUMN previous_branch_code VARCHAR(15),
    ADD COLUMN previous_account_number VARCHAR(50),
    ADD COLUMN sanctioned_amount NUMERIC(20, 2) COMMENT 'Sanctioned / notional amount (in currency)',
    ADD COLUMN currency VARCHAR(40) COMMENT 'codes: currency Currency of sanctioned_amount. Other amounts are INR',
    ADD COLUMN drawing_power NUMERIC(20, 2),
    ADD COLUMN restructured_notional_amount NUMERIC(20, 2) COMMENT 'Derivatives only',
    ADD COLUMN maturity_date DATE,
    ADD COLUMN renewal_date DATE,
    ADD COLUMN asset_classification_date DATE,
    ADD COLUMN overdue_bucket_1 NUMERIC(20, 2) COMMENT 'Overdue 1-30 days',
    ADD COLUMN overdue_bucket_2 NUMERIC(20, 2) COMMENT 'Overdue 31-60 days',
    ADD COLUMN overdue_bucket_3 NUMERIC(20, 2) COMMENT 'Overdue 61-90 days',
    ADD COLUMN overdue_bucket_4 NUMERIC(20, 2) COMMENT 'Overdue 91-180 days',
    ADD COLUMN overdue_bucket_5 NUMERIC(20, 2) COMMENT 'Overdue above 180 days',
    ADD COLUMN status_date DATE COMMENT 'Date credit_facility_status (or closure) took effect',
    ADD COLUMN restructuring_reason VARCHAR(40) COMMENT 'codes: restructuring_reason',
    ADD COLUMN npa_contracts_amount NUMERIC(20, 2) COMMENT 'Derivatives only',
    ADD COLUMN security_coverage VARCHAR(40) COMMENT 'codes: coverage',
    ADD COLUMN guarantee_coverage VARCHAR(40) COMMENT 'codes: coverage',
    ADD COLUMN remark VARCHAR(100),
    ADD COLUMN wilful_default_date DATE COMMENT 'Set = classified as wilful defaulter on this date',
    ADD COLUMN suit_reference VARCHAR(25),
    ADD COLUMN suit_amount NUMERIC(20, 2),
    ADD COLUMN suit_date DATE,
    ADD COLUMN dispute_id VARCHAR(20),
    ADD COLUMN other_lenders VARCHAR(42) COMMENT 'Other banks / FIs (consortium)',
    ADD COLUMN ufce_amount NUMERIC(20, 2) COMMENT 'Unhedged foreign currency exposure',
    ADD COLUMN ufce_date DATE;

CREATE TABLE c_relationship (
	row_id BIGINT NOT NULL AUTO_INCREMENT,
	snapshot_id BIGINT NOT NULL,
	party_key VARCHAR(50) COMMENT 'The borrower',
	relationship_type VARCHAR(40) COMMENT 'codes: relationship_type',
	control_percentage NUMERIC(5, 2) COMMENT 'Shares held (in either direction) in percent',
	related_key VARCHAR(50) COMMENT 'Source key of the related party or guarantor',
	related_type VARCHAR(40) COMMENT 'codes: related_type',
	full_name VARCHAR(150) COMMENT 'Entity name or individual full name',
	name_prefix VARCHAR(15) COMMENT 'Individuals - Mr, Ms, Dr ...',
	business_category VARCHAR(40) COMMENT 'codes: business_category',
	industry_type VARCHAR(40) COMMENT 'codes: industry_type',
	gender VARCHAR(40) COMMENT 'codes: gender',
	birth_date DATE,
	incorporation_date DATE,
	pan VARCHAR(20),
	voter_id VARCHAR(30),
	passport VARCHAR(30),
	driving_licence VARCHAR(30),
	aadhaar VARCHAR(30),
	ration_card VARCHAR(30),
	company_registration VARCHAR(30),
	cin VARCHAR(30),
	din VARCHAR(12),
	tin VARCHAR(30),
	service_tax VARCHAR(30),
	ckyc VARCHAR(30),
	udyam VARCHAR(30),
	address_line_1 VARCHAR(200),
	address_line_2 VARCHAR(200),
	address_line_3 VARCHAR(200),
	city VARCHAR(40),
	district VARCHAR(40),
	state_code VARCHAR(40) COMMENT 'codes: state_code',
	pin_code VARCHAR(20),
	country VARCHAR(40) COMMENT 'codes: country',
	mobile VARCHAR(60) COMMENT 'Comma-separated numbers allowed',
	telephone VARCHAR(60),
	telephone_area_code VARCHAR(6),
	fax VARCHAR(60),
	fax_area_code VARCHAR(6),
	PRIMARY KEY (row_id),
	FOREIGN KEY(snapshot_id) REFERENCES extract_snapshot (snapshot_id) ON DELETE CASCADE
)COMMENT='A party related to a business borrower (director, partner, holding company ...). Commercial';

CREATE INDEX ix_c_relationship_party_key ON c_relationship (snapshot_id, party_key);

CREATE TABLE c_guarantor (
	row_id BIGINT NOT NULL AUTO_INCREMENT,
	snapshot_id BIGINT NOT NULL,
	account_key VARCHAR(50),
	related_key VARCHAR(50) COMMENT 'Source key of the related party or guarantor',
	related_type VARCHAR(40) COMMENT 'codes: related_type',
	full_name VARCHAR(150) COMMENT 'Entity name or individual full name',
	name_prefix VARCHAR(15) COMMENT 'Individuals - Mr, Ms, Dr ...',
	business_category VARCHAR(40) COMMENT 'codes: business_category',
	industry_type VARCHAR(40) COMMENT 'codes: industry_type',
	gender VARCHAR(40) COMMENT 'codes: gender',
	birth_date DATE,
	incorporation_date DATE,
	pan VARCHAR(20),
	voter_id VARCHAR(30),
	passport VARCHAR(30),
	driving_licence VARCHAR(30),
	aadhaar VARCHAR(30),
	ration_card VARCHAR(30),
	company_registration VARCHAR(30),
	cin VARCHAR(30),
	din VARCHAR(12),
	tin VARCHAR(30),
	service_tax VARCHAR(30),
	ckyc VARCHAR(30),
	udyam VARCHAR(30),
	address_line_1 VARCHAR(200),
	address_line_2 VARCHAR(200),
	address_line_3 VARCHAR(200),
	city VARCHAR(40),
	district VARCHAR(40),
	state_code VARCHAR(40) COMMENT 'codes: state_code',
	pin_code VARCHAR(20),
	country VARCHAR(40) COMMENT 'codes: country',
	mobile VARCHAR(60) COMMENT 'Comma-separated numbers allowed',
	telephone VARCHAR(60),
	telephone_area_code VARCHAR(6),
	fax VARCHAR(60),
	fax_area_code VARCHAR(6),
	guarantee_invocation_date DATE,
	PRIMARY KEY (row_id),
	FOREIGN KEY(snapshot_id) REFERENCES extract_snapshot (snapshot_id) ON DELETE CASCADE
)COMMENT='A guarantor of a credit facility. Commercial';

CREATE INDEX ix_c_guarantor_account_key ON c_guarantor (snapshot_id, account_key);

CREATE TABLE c_security (
	row_id BIGINT NOT NULL AUTO_INCREMENT,
	snapshot_id BIGINT NOT NULL,
	account_key VARCHAR(50),
	security_value NUMERIC(20, 2),
	currency VARCHAR(40) COMMENT 'codes: currency',
	security_type VARCHAR(40) COMMENT 'codes: security_type',
	security_classification VARCHAR(40) COMMENT 'codes: security_classification',
	valuation_date DATE,
	PRIMARY KEY (row_id),
	FOREIGN KEY(snapshot_id) REFERENCES extract_snapshot (snapshot_id) ON DELETE CASCADE
)COMMENT='A tangible security for a credit facility. Commercial';

CREATE INDEX ix_c_security_account_key ON c_security (snapshot_id, account_key);

CREATE TABLE c_cheque_dishonour (
	row_id BIGINT NOT NULL AUTO_INCREMENT,
	snapshot_id BIGINT NOT NULL,
	account_key VARCHAR(50),
	dishonour_date DATE,
	amount NUMERIC(20, 2),
	instrument_number VARCHAR(30),
	dishonour_count INTEGER,
	cheque_issue_date DATE COMMENT 'Only for a single dishonoured cheque',
	reason VARCHAR(40) COMMENT 'codes: dishonour_reason',
	PRIMARY KEY (row_id),
	FOREIGN KEY(snapshot_id) REFERENCES extract_snapshot (snapshot_id) ON DELETE CASCADE
)COMMENT='An inward cheque dishonoured on a credit facility. Commercial';

CREATE INDEX ix_c_cheque_dishonour_account_key ON c_cheque_dishonour (snapshot_id, account_key);
