-- GENERATED from the tenant mapping (version 689bebdfcd7107c4). Do not edit.
SELECT  -- party_address.main
    (a.customer_id) AS party_key,
    (a.line1) AS address_line_1,
    (a.line2) AS address_line_2,
    (a.line3) AS address_line_3,
    NULL AS address_line_4,
    NULL AS address_line_5,
    CASE (a.state) WHEN 'Jammu & Kashmir' THEN 'JAMMU_KASHMIR' WHEN 'Himachal Pradesh' THEN 'HIMACHAL_PRADESH' WHEN 'Punjab' THEN 'PUNJAB' WHEN 'Chandigarh' THEN 'CHANDIGARH' WHEN 'Uttarakhand' THEN 'UTTARAKHAND' WHEN 'Haryana' THEN 'HARYANA' WHEN 'Delhi' THEN 'DELHI' WHEN 'Rajasthan' THEN 'RAJASTHAN' WHEN 'Uttar Pradesh' THEN 'UTTAR_PRADESH' WHEN 'Bihar' THEN 'BIHAR' WHEN 'Sikkim' THEN 'SIKKIM' WHEN 'Arunachal Pradesh' THEN 'ARUNACHAL_PRADESH' WHEN 'Nagaland' THEN 'NAGALAND' WHEN 'Manipur' THEN 'MANIPUR' WHEN 'Mizoram' THEN 'MIZORAM' WHEN 'Tripura' THEN 'TRIPURA' WHEN 'Meghalaya' THEN 'MEGHALAYA' WHEN 'Assam' THEN 'ASSAM' WHEN 'West Bengal' THEN 'WEST_BENGAL' WHEN 'Jharkhand' THEN 'JHARKHAND' WHEN 'Odisha' THEN 'ODISHA' WHEN 'Chhattisgarh' THEN 'CHHATTISGARH' WHEN 'Madhya Pradesh' THEN 'MADHYA_PRADESH' WHEN 'Gujarat' THEN 'GUJARAT' WHEN 'Maharashtra' THEN 'MAHARASHTRA' WHEN 'Andhra Pradesh' THEN 'ANDHRA_PRADESH' WHEN 'Karnataka' THEN 'KARNATAKA' WHEN 'Goa' THEN 'GOA' WHEN 'Kerala' THEN 'KERALA' WHEN 'Tamil Nadu' THEN 'TAMIL_NADU' WHEN 'Puducherry' THEN 'PUDUCHERRY' WHEN 'Telangana' THEN 'TELANGANA' WHEN 'Ladakh' THEN 'LADAKH' WHEN 'Foreign' THEN 'FOREIGN' WHEN 'APO' THEN 'APO' ELSE (a.state) END AS state_code,
    (a.pin) AS pin_code,
    CASE (a.address_type) WHEN 'REG' THEN 'REGISTERED_OFFICE' WHEN 'BRANCH' THEN 'BRANCH_OFFICE' WHEN 'WH' THEN 'WAREHOUSE' WHEN 'PLANT' THEN 'PLANT_FACTORY' WHEN 'OTH' THEN 'OTHERS' WHEN 'MORT' THEN 'MORTGAGE_PROPERTY' ELSE (a.address_type) END AS address_category,
    NULL AS residence_code,
    (a.seq) AS priority,
    (a.city) AS city,
    (a.district) AS district,
    CASE (a.country) WHEN 'IN' THEN 'INDIA' WHEN 'SG' THEN 'SINGAPORE' WHEN 'CA' THEN 'CANADA' WHEN 'GB' THEN 'UNITED_KINGDOM' WHEN 'US' THEN 'UNITED_STATES_OF_AMERICA' WHEN 'AE' THEN 'UNITED_ARAB_EMIRATES' ELSE (a.country) END AS country
FROM nbfc_002.business_address a;
