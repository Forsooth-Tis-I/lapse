MERGE (s:Service {id: $service.id}) SET s += $service
MERGE (a:Account {id: $account.id})
ON CREATE SET a.status = 'active'
SET a += $account,
    a.first_seen = CASE WHEN a.first_seen IS NULL OR $at < a.first_seen THEN $at ELSE a.first_seen END,
    a.last_seen = CASE WHEN a.last_seen IS NULL OR $at > a.last_seen THEN $at ELSE a.last_seen END
MERGE (a)-[:OF]->(s)
MERGE (e:Evidence {id: $evidence.id}) SET e += $evidence
MERGE (e)-[:SUPPORTS]->(a)
