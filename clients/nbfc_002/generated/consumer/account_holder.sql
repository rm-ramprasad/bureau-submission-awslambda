-- GENERATED from the tenant mapping (version 5776d65ba15c222f). Do not edit.
SELECT  -- account_holder.main
    (a.loan_id) AS account_key,
    (a.customer_id) AS party_key,
    CASE (CASE WHEN a.party_role = 'PRIMARY' AND EXISTS (SELECT 1 FROM nbfc_002.account_details j WHERE j.loan_id = a.loan_id AND j.party_role = 'JOINT') THEN 'JOINT' ELSE a.party_role END) WHEN 'PRIMARY' THEN 'INDIVIDUAL' WHEN 'ADDON' THEN 'AUTHORISED_USER' WHEN 'GUARANTOR' THEN 'GUARANTOR' WHEN 'JOINT' THEN 'JOINT' WHEN 'DECEASED' THEN 'DECEASED' ELSE (CASE WHEN a.party_role = 'PRIMARY' AND EXISTS (SELECT 1 FROM nbfc_002.account_details j WHERE j.loan_id = a.loan_id AND j.party_role = 'JOINT') THEN 'JOINT' ELSE a.party_role END) END AS ownership_indicator
FROM nbfc_002.account_details a
WHERE a.disbursement_date <= :as_of_date;
