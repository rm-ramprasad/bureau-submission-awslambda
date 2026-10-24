-- GENERATED from the tenant mapping (version 0b9e11683ec9dc1d). Do not edit.
SELECT  -- party.main
    (b.customer_id) AS party_key,
    (CONCAT_WS(' ', b.first_name, b.middle_name, b.last_name)) AS full_name,
    (b.birth_date) AS birth_date,
    CASE (b.sex) WHEN 'M' THEN 'MALE' WHEN 'F' THEN 'FEMALE' WHEN 'T' THEN 'TRANSGENDER' ELSE (b.sex) END AS gender,
    CASE (b.occupation) WHEN 'SALARIED' THEN 'SALARIED' WHEN 'PROFESSIONAL' THEN 'SELF_EMPLOYED_PROFESSIONAL' WHEN 'SELF_EMPLOYED' THEN 'SELF_EMPLOYED' WHEN 'OTHER' THEN 'OTHERS' ELSE (b.occupation) END AS occupation,
    (b.income_amount) AS income,
    CASE (b.income_basis) WHEN 'GROSS' THEN 'GROSS' WHEN 'NET' THEN 'NET' ELSE (b.income_basis) END AS income_basis,
    CASE (b.income_period) WHEN 'MONTHLY' THEN 'MONTHLY' WHEN 'ANNUAL' THEN 'ANNUAL' ELSE (b.income_period) END AS income_period
FROM nbfc_001.borrower_demographics b;
