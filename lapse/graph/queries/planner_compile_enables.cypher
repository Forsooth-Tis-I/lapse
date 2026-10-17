MATCH (m:Method)-[:GRANTS]->(target:Account {id: $account_id}), (m)-[:NEEDS]->(n)
WHERE m.needs_password = false
WITH m, target, collect(n) AS needs
WHERE size(needs) = 1
UNWIND needs AS source
MERGE (source)-[:ENABLES]->(target)
