MATCH (a:Account)
WHERE coalesce(a.status, 'active') = 'active'
  AND ($all_accounts OR a.id IN $account_ids)
OPTIONAL MATCH (a)-[u:USES]->(r:Root)
RETURN a AS account, collect({role: u.role, root_id: r.id}) AS uses
ORDER BY a.id
