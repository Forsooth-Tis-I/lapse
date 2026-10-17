MATCH (e:Evidence)-[:SUPPORTS]->(a:Account {id: $account_id})
RETURN DISTINCT e AS evidence
ORDER BY e.date DESC, e.id
