-- GENERATED from the tenant mapping (version 65bf646980b5af48). Do not edit.
SELECT  -- party_email.main
    (a.customer_id) AS party_key,
    (a.email) AS email,
    (a.seq) AS priority
FROM nbfc_001.business_address a
WHERE a.email IS NOT NULL;
