-- GENERATED from the tenant mapping (version 689bebdfcd7107c4). Do not edit.
SELECT  -- cheque_dishonour.main
    (c.facility_id) AS account_key,
    (c.bounce_date) AS dishonour_date,
    (c.amount) AS amount,
    (c.cheque_no) AS instrument_number,
    (c.times) AS dishonour_count,
    (c.cheque_date) AS cheque_issue_date,
    CASE (c.reason) WHEN 'INSUFF' THEN 'INSUFFICIENT_FUNDS' WHEN 'CLOSED' THEN 'ACCOUNT_CLOSED' ELSE (c.reason) END AS reason
FROM nbfc_002.facility_cheque_bounce c;
