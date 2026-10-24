-- GENERATED from the tenant mapping (version 0b9e11683ec9dc1d). Do not edit.
SELECT  -- party_phone.phone1
    (b.customer_id) AS party_key,
    (b.phone1_number) AS phone_number,
    (b.phone1_extension) AS extension,
    CASE (b.phone1_type) WHEN 'MOBILE' THEN 'MOBILE' WHEN 'HOME' THEN 'HOME' WHEN 'OFFICE' THEN 'OFFICE' WHEN 'OTHER' THEN 'NOT_CLASSIFIED' ELSE (b.phone1_type) END AS phone_type,
    (1) AS priority
FROM nbfc_001.borrower_demographics b
WHERE b.phone1_number IS NOT NULL
UNION ALL
SELECT  -- party_phone.phone2
    (b.customer_id) AS party_key,
    (b.phone2_number) AS phone_number,
    (b.phone2_extension) AS extension,
    CASE (b.phone2_type) WHEN 'MOBILE' THEN 'MOBILE' WHEN 'HOME' THEN 'HOME' WHEN 'OFFICE' THEN 'OFFICE' WHEN 'OTHER' THEN 'NOT_CLASSIFIED' ELSE (b.phone2_type) END AS phone_type,
    (2) AS priority
FROM nbfc_001.borrower_demographics b
WHERE b.phone2_number IS NOT NULL
UNION ALL
SELECT  -- party_phone.phone3
    (b.customer_id) AS party_key,
    (b.phone3_number) AS phone_number,
    (b.phone3_extension) AS extension,
    CASE (b.phone3_type) WHEN 'MOBILE' THEN 'MOBILE' WHEN 'HOME' THEN 'HOME' WHEN 'OFFICE' THEN 'OFFICE' WHEN 'OTHER' THEN 'NOT_CLASSIFIED' ELSE (b.phone3_type) END AS phone_type,
    (3) AS priority
FROM nbfc_001.borrower_demographics b
WHERE b.phone3_number IS NOT NULL
UNION ALL
SELECT  -- party_phone.phone4
    (b.customer_id) AS party_key,
    (b.phone4_number) AS phone_number,
    (b.phone4_extension) AS extension,
    CASE (b.phone4_type) WHEN 'MOBILE' THEN 'MOBILE' WHEN 'HOME' THEN 'HOME' WHEN 'OFFICE' THEN 'OFFICE' WHEN 'OTHER' THEN 'NOT_CLASSIFIED' ELSE (b.phone4_type) END AS phone_type,
    (4) AS priority
FROM nbfc_001.borrower_demographics b
WHERE b.phone4_number IS NOT NULL;
