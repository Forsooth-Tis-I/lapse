MATCH (e:Evidence)-[:SUPPORTS|MENTIONS]->(n)
WHERE n.id IN $ids
RETURN DISTINCT e AS evidence
ORDER BY e.date, e.id
