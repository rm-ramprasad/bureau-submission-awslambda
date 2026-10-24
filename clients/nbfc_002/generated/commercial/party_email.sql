-- GENERATED from the tenant mapping (version 689bebdfcd7107c4). Do not edit.
SELECT  -- party_email.main
    (a.customer_id) AS party_key,
    (a.email) AS email,
    (a.seq) AS priority
FROM nbfc_002.business_address a
WHERE a.email IS NOT NULL;
