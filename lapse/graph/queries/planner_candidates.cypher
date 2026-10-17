MATCH (a:Account)-[u:USES]->(r:Root {id: $root_id})
WHERE coalesce(a.status, 'active') = 'active'
RETURN DISTINCT a.id AS account_id, a.display AS account_label, a.service_id AS service_id, u.role AS role
ORDER BY account_id, role
