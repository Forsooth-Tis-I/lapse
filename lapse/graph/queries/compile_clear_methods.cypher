MATCH (m:Method)
WHERE $all_accounts OR m.account_id IN $account_ids
DETACH DELETE m
