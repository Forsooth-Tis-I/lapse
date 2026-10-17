MATCH (m:Method)-[:GRANTS]->(target)
WHERE m.account_id IN $account_ids
RETURN DISTINCT target.id AS target_id
