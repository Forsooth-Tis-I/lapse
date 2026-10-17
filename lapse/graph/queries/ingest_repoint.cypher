MATCH (e:Evidence {id: $evidence_id})-[:SUPPORTS]->(a:Account {id: $account_id})
SET e.repoint_role = $role
WITH a
OPTIONAL MATCH (later:Evidence)-[:SUPPORTS]->(a)
WHERE later.repoint_role = $role AND later.observed_order > $order
WITH a, count(later) AS newer
WHERE newer = 0
MATCH (a)-[u:USES {role: $role}]->(r:Root)
WHERE r.id <> $root_id AND coalesce(u.observed_order, '') <= $order
DELETE u
