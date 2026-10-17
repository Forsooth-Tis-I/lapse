MATCH (m:Method)-[:GRANTS]->(r:Root:Email)
WHERE m.kind = 'mailbox' AND r.id IN $lost
RETURN m.id AS id
ORDER BY id
