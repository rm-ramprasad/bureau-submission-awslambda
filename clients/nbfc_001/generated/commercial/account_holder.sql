-- GENERATED from the tenant mapping (version 65bf646980b5af48). Do not edit.
SELECT  -- account_holder.main
    (f.facility_id) AS account_key,
    (f.customer_id) AS party_key,
    NULL AS ownership_indicator
FROM nbfc_001.business_facility f
WHERE f.sanction_date <= :as_of_date;
