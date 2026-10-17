MATCH (a:Account {id: $account_id}), (r:Root {id: $root_id})
OPTIONAL MATCH (later:Evidence)-[:SUPPORTS]->(a)
WHERE later.repoint_role = $role AND later.observed_order > $order
WITH a, r, count(later) AS newer
WHERE newer = 0
MERGE (a)-[u:USES {role: $role}]->(r)
SET u.observed_order = CASE WHEN coalesce(u.observed_order, '') > $order THEN u.observed_order ELSE $order END,
    u.confirmed = coalesce(u.confirmed, false) OR $confirmed,
    u.confidence = CASE WHEN coalesce(u.confidence, 0.0) > $confidence THEN u.confidence ELSE $confidence END,
    u.evidence_ids = coalesce(u.evidence_ids, []) + [id IN $evidence_ids WHERE NOT id IN coalesce(u.evidence_ids, [])]
