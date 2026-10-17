MATCH (a:Account)-[u:USES]->(r:Root)
WHERE $account_id = '' OR a.id = $account_id
RETURN a.id AS account_id, r.id AS root_id, u.role AS role,
       coalesce(u.confirmed, false) AS confirmed,
       coalesce(u.confidence, 0.5) AS confidence,
       coalesce(u.evidence_ids, []) AS evidence_ids
ORDER BY a.id, r.id, u.role
