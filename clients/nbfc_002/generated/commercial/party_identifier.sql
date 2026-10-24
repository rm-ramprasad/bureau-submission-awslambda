-- GENERATED from the tenant mapping (version 689bebdfcd7107c4). Do not edit.
SELECT  -- party_identifier.pan
    (b.customer_id) AS party_key,
    ('PAN') AS id_type,
    (b.pan) AS id_number,
    NULL AS issue_date,
    NULL AS expiry_date
FROM nbfc_002.business_borrower b
WHERE b.pan IS NOT NULL
UNION ALL
SELECT  -- party_identifier.cin
    (b.customer_id) AS party_key,
    ('CIN') AS id_type,
    (b.cin) AS id_number,
    NULL AS issue_date,
    NULL AS expiry_date
FROM nbfc_002.business_borrower b
WHERE b.cin IS NOT NULL
UNION ALL
SELECT  -- party_identifier.tin
    (b.customer_id) AS party_key,
    ('TIN') AS id_type,
    (b.tin) AS id_number,
    NULL AS issue_date,
    NULL AS expiry_date
FROM nbfc_002.business_borrower b
WHERE b.tin IS NOT NULL
UNION ALL
SELECT  -- party_identifier.service_tax
    (b.customer_id) AS party_key,
    ('SERVICE_TAX') AS id_type,
    (b.service_tax) AS id_number,
    NULL AS issue_date,
    NULL AS expiry_date
FROM nbfc_002.business_borrower b
WHERE b.service_tax IS NOT NULL
UNION ALL
SELECT  -- party_identifier.udyam
    (b.customer_id) AS party_key,
    ('UDYAM') AS id_type,
    (b.udyam) AS id_number,
    NULL AS issue_date,
    NULL AS expiry_date
FROM nbfc_002.business_borrower b
WHERE b.udyam IS NOT NULL
UNION ALL
SELECT  -- party_identifier.company_registration
    (b.customer_id) AS party_key,
    ('COMPANY_REGISTRATION') AS id_type,
    (b.company_reg_no) AS id_number,
    NULL AS issue_date,
    NULL AS expiry_date
FROM nbfc_002.business_borrower b
WHERE b.company_reg_no IS NOT NULL
UNION ALL
SELECT  -- party_identifier.ckyc
    (b.customer_id) AS party_key,
    ('CKYC') AS id_type,
    (b.ckyc) AS id_number,
    NULL AS issue_date,
    NULL AS expiry_date
FROM nbfc_002.business_borrower b
WHERE b.ckyc IS NOT NULL;
