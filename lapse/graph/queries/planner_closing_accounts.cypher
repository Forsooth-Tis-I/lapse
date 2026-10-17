MATCH (host:Account)<-[:NEEDS]-(m:Method)-[:GRANTS]->(r:Root:Email {id: $root_id})
WHERE m.kind = 'mailbox'
RETURN DISTINCT host.id AS account_id, coalesce(host.display, host.id) AS account_label
ORDER BY account_id
