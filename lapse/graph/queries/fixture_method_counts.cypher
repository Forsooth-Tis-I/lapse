MATCH (a:Account)
OPTIONAL MATCH (m:Method)-[:GRANTS]->(a)
RETURN a.id AS account_id, a.modelled AS modelled, count(m) AS method_count
ORDER BY a.id
