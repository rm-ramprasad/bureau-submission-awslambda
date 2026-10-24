-- GENERATED from the tenant mapping (version 0b9e11683ec9dc1d). Do not edit.
SELECT  -- party_address.address1
    (b.customer_id) AS party_key,
    (b.address1_line1) AS address_line_1,
    (b.address1_line2) AS address_line_2,
    (b.address1_line3) AS address_line_3,
    (b.address1_city) AS address_line_4,
    NULL AS address_line_5,
    CASE (b.address1_state) WHEN 'Jammu & Kashmir' THEN 'JAMMU_KASHMIR' WHEN 'Himachal Pradesh' THEN 'HIMACHAL_PRADESH' WHEN 'Punjab' THEN 'PUNJAB' WHEN 'Chandigarh' THEN 'CHANDIGARH' WHEN 'Uttarakhand' THEN 'UTTARAKHAND' WHEN 'Haryana' THEN 'HARYANA' WHEN 'Delhi' THEN 'DELHI' WHEN 'Rajasthan' THEN 'RAJASTHAN' WHEN 'Uttar Pradesh' THEN 'UTTAR_PRADESH' WHEN 'Bihar' THEN 'BIHAR' WHEN 'Sikkim' THEN 'SIKKIM' WHEN 'Arunachal Pradesh' THEN 'ARUNACHAL_PRADESH' WHEN 'Nagaland' THEN 'NAGALAND' WHEN 'Manipur' THEN 'MANIPUR' WHEN 'Mizoram' THEN 'MIZORAM' WHEN 'Tripura' THEN 'TRIPURA' WHEN 'Meghalaya' THEN 'MEGHALAYA' WHEN 'Assam' THEN 'ASSAM' WHEN 'West Bengal' THEN 'WEST_BENGAL' WHEN 'Jharkhand' THEN 'JHARKHAND' WHEN 'Odisha' THEN 'ODISHA' WHEN 'Orissa' THEN 'ODISHA' WHEN 'Chhattisgarh' THEN 'CHHATTISGARH' WHEN 'Madhya Pradesh' THEN 'MADHYA_PRADESH' WHEN 'Gujarat' THEN 'GUJARAT' WHEN 'Maharashtra' THEN 'MAHARASHTRA' WHEN 'Andhra Pradesh' THEN 'ANDHRA_PRADESH' WHEN 'Karnataka' THEN 'KARNATAKA' WHEN 'Goa' THEN 'GOA' WHEN 'Kerala' THEN 'KERALA' WHEN 'Tamil Nadu' THEN 'TAMIL_NADU' WHEN 'Puducherry' THEN 'PUDUCHERRY' WHEN 'Telangana' THEN 'TELANGANA' WHEN 'Ladakh' THEN 'LADAKH' WHEN 'Foreign' THEN 'FOREIGN' WHEN 'APO' THEN 'APO' ELSE (b.address1_state) END AS state_code,
    (b.address1_pin_code) AS pin_code,
    COALESCE(CASE (b.address1_type) WHEN 'PERM' THEN 'PERMANENT' WHEN 'RES' THEN 'RESIDENCE' WHEN 'OFF' THEN 'OFFICE' WHEN 'OTH' THEN 'NOT_CATEGORIZED' WHEN 'MORT' THEN 'MORTGAGE_PROPERTY' ELSE (b.address1_type) END, 'NOT_CATEGORIZED') AS address_category,
    CASE (b.address1_tenure) WHEN 'OWN' THEN 'OWNED' WHEN 'RENT' THEN 'RENTED' ELSE (b.address1_tenure) END AS residence_code,
    (1) AS priority
FROM nbfc_001.borrower_demographics b
WHERE b.address1_line1 IS NOT NULL
UNION ALL
SELECT  -- party_address.address2
    (b.customer_id) AS party_key,
    (b.address2_line1) AS address_line_1,
    (b.address2_line2) AS address_line_2,
    (b.address2_line3) AS address_line_3,
    (b.address2_city) AS address_line_4,
    NULL AS address_line_5,
    CASE (b.address2_state) WHEN 'Jammu & Kashmir' THEN 'JAMMU_KASHMIR' WHEN 'Himachal Pradesh' THEN 'HIMACHAL_PRADESH' WHEN 'Punjab' THEN 'PUNJAB' WHEN 'Chandigarh' THEN 'CHANDIGARH' WHEN 'Uttarakhand' THEN 'UTTARAKHAND' WHEN 'Haryana' THEN 'HARYANA' WHEN 'Delhi' THEN 'DELHI' WHEN 'Rajasthan' THEN 'RAJASTHAN' WHEN 'Uttar Pradesh' THEN 'UTTAR_PRADESH' WHEN 'Bihar' THEN 'BIHAR' WHEN 'Sikkim' THEN 'SIKKIM' WHEN 'Arunachal Pradesh' THEN 'ARUNACHAL_PRADESH' WHEN 'Nagaland' THEN 'NAGALAND' WHEN 'Manipur' THEN 'MANIPUR' WHEN 'Mizoram' THEN 'MIZORAM' WHEN 'Tripura' THEN 'TRIPURA' WHEN 'Meghalaya' THEN 'MEGHALAYA' WHEN 'Assam' THEN 'ASSAM' WHEN 'West Bengal' THEN 'WEST_BENGAL' WHEN 'Jharkhand' THEN 'JHARKHAND' WHEN 'Odisha' THEN 'ODISHA' WHEN 'Orissa' THEN 'ODISHA' WHEN 'Chhattisgarh' THEN 'CHHATTISGARH' WHEN 'Madhya Pradesh' THEN 'MADHYA_PRADESH' WHEN 'Gujarat' THEN 'GUJARAT' WHEN 'Maharashtra' THEN 'MAHARASHTRA' WHEN 'Andhra Pradesh' THEN 'ANDHRA_PRADESH' WHEN 'Karnataka' THEN 'KARNATAKA' WHEN 'Goa' THEN 'GOA' WHEN 'Kerala' THEN 'KERALA' WHEN 'Tamil Nadu' THEN 'TAMIL_NADU' WHEN 'Puducherry' THEN 'PUDUCHERRY' WHEN 'Telangana' THEN 'TELANGANA' WHEN 'Ladakh' THEN 'LADAKH' WHEN 'Foreign' THEN 'FOREIGN' WHEN 'APO' THEN 'APO' ELSE (b.address2_state) END AS state_code,
    (b.address2_pin_code) AS pin_code,
    COALESCE(CASE (b.address2_type) WHEN 'PERM' THEN 'PERMANENT' WHEN 'RES' THEN 'RESIDENCE' WHEN 'OFF' THEN 'OFFICE' WHEN 'OTH' THEN 'NOT_CATEGORIZED' WHEN 'MORT' THEN 'MORTGAGE_PROPERTY' ELSE (b.address2_type) END, 'NOT_CATEGORIZED') AS address_category,
    CASE (b.address2_tenure) WHEN 'OWN' THEN 'OWNED' WHEN 'RENT' THEN 'RENTED' ELSE (b.address2_tenure) END AS residence_code,
    (2) AS priority
FROM nbfc_001.borrower_demographics b
WHERE b.address2_line1 IS NOT NULL
UNION ALL
SELECT  -- party_address.address3
    (b.customer_id) AS party_key,
    (b.address3_line1) AS address_line_1,
    (b.address3_line2) AS address_line_2,
    (b.address3_line3) AS address_line_3,
    (b.address3_city) AS address_line_4,
    NULL AS address_line_5,
    CASE (b.address3_state) WHEN 'Jammu & Kashmir' THEN 'JAMMU_KASHMIR' WHEN 'Himachal Pradesh' THEN 'HIMACHAL_PRADESH' WHEN 'Punjab' THEN 'PUNJAB' WHEN 'Chandigarh' THEN 'CHANDIGARH' WHEN 'Uttarakhand' THEN 'UTTARAKHAND' WHEN 'Haryana' THEN 'HARYANA' WHEN 'Delhi' THEN 'DELHI' WHEN 'Rajasthan' THEN 'RAJASTHAN' WHEN 'Uttar Pradesh' THEN 'UTTAR_PRADESH' WHEN 'Bihar' THEN 'BIHAR' WHEN 'Sikkim' THEN 'SIKKIM' WHEN 'Arunachal Pradesh' THEN 'ARUNACHAL_PRADESH' WHEN 'Nagaland' THEN 'NAGALAND' WHEN 'Manipur' THEN 'MANIPUR' WHEN 'Mizoram' THEN 'MIZORAM' WHEN 'Tripura' THEN 'TRIPURA' WHEN 'Meghalaya' THEN 'MEGHALAYA' WHEN 'Assam' THEN 'ASSAM' WHEN 'West Bengal' THEN 'WEST_BENGAL' WHEN 'Jharkhand' THEN 'JHARKHAND' WHEN 'Odisha' THEN 'ODISHA' WHEN 'Orissa' THEN 'ODISHA' WHEN 'Chhattisgarh' THEN 'CHHATTISGARH' WHEN 'Madhya Pradesh' THEN 'MADHYA_PRADESH' WHEN 'Gujarat' THEN 'GUJARAT' WHEN 'Maharashtra' THEN 'MAHARASHTRA' WHEN 'Andhra Pradesh' THEN 'ANDHRA_PRADESH' WHEN 'Karnataka' THEN 'KARNATAKA' WHEN 'Goa' THEN 'GOA' WHEN 'Kerala' THEN 'KERALA' WHEN 'Tamil Nadu' THEN 'TAMIL_NADU' WHEN 'Puducherry' THEN 'PUDUCHERRY' WHEN 'Telangana' THEN 'TELANGANA' WHEN 'Ladakh' THEN 'LADAKH' WHEN 'Foreign' THEN 'FOREIGN' WHEN 'APO' THEN 'APO' ELSE (b.address3_state) END AS state_code,
    (b.address3_pin_code) AS pin_code,
    COALESCE(CASE (b.address3_type) WHEN 'PERM' THEN 'PERMANENT' WHEN 'RES' THEN 'RESIDENCE' WHEN 'OFF' THEN 'OFFICE' WHEN 'OTH' THEN 'NOT_CATEGORIZED' WHEN 'MORT' THEN 'MORTGAGE_PROPERTY' ELSE (b.address3_type) END, 'NOT_CATEGORIZED') AS address_category,
    CASE (b.address3_tenure) WHEN 'OWN' THEN 'OWNED' WHEN 'RENT' THEN 'RENTED' ELSE (b.address3_tenure) END AS residence_code,
    (3) AS priority
FROM nbfc_001.borrower_demographics b
WHERE b.address3_line1 IS NOT NULL;
