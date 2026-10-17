MATCH (m:Method)-[:GRANTS]->(target), (m)-[:NEEDS]->(n)
WHERE m.needs_password = false
  AND ($all_accounts OR target.id IN $target_ids)
WITH m, target, collect(n) AS needs
WHERE size(needs) = 1
UNWIND needs AS source
MERGE (source)-[:ENABLES]->(target)
