// Lockout of an email root: the mailbox is gone, and so is the account that hosted it.
// A college deleting a student's account removes the whole account, not just the inbox,
// so every method that grants the hosting account is disabled too.
MATCH (m:Method)-[:GRANTS]->(r:Root:Email)
WHERE m.kind = 'mailbox' AND r.id IN $lost
OPTIONAL MATCH (m)-[:NEEDS]->(host:Account)
OPTIONAL MATCH (hm:Method)-[:GRANTS]->(host)
WITH collect(DISTINCT m.id) + collect(DISTINCT hm.id) AS ids
UNWIND ids AS id
WITH DISTINCT id
WHERE id IS NOT NULL
RETURN id
ORDER BY id
