MATCH (m:Method)-[:GRANTS]->(:Account {id: $account_id})
WHERE m.source = 'policy'
DETACH DELETE m
