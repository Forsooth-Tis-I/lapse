MATCH (m:Method)
WHERE coalesce(m.source, 'policy') = 'policy' AND ($all_accounts OR m.account_id IN $account_ids)
DETACH DELETE m
