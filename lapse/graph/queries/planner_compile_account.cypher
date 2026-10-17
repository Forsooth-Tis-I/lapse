MATCH (a:Account {id: $account_id}) WHERE coalesce(a.status, 'active') = 'active'
OPTIONAL MATCH (a)-[u:USES]->(r:Root)
RETURN a AS account, collect({role: u.role, root_id: r.id}) AS uses
