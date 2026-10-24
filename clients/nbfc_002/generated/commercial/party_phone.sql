-- GENERATED from the tenant mapping (version 689bebdfcd7107c4). Do not edit.
SELECT  -- party_phone.mobile
    (a.customer_id) AS party_key,
    (a.mobile) AS phone_number,
    NULL AS extension,
    ('MOBILE') AS phone_type,
    (a.seq) AS priority
FROM nbfc_002.business_address a
WHERE a.mobile IS NOT NULL
UNION ALL
SELECT  -- party_phone.landline
    (a.customer_id) AS party_key,
    (CONCAT_WS('-', a.phone_area, a.phone)) AS phone_number,
    NULL AS extension,
    ('OFFICE') AS phone_type,
    (a.seq + 10) AS priority
FROM nbfc_002.business_address a
WHERE a.phone IS NOT NULL;
