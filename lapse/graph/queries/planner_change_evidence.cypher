MATCH (c:Change {id: $change_id}), (e:Evidence {id: $evidence_id}), (a:Account {id: c.account_id})
MERGE (e)-[:SUPPORTS]->(a)
SET c.evidence_id = e.id
