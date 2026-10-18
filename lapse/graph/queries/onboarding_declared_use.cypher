// Identity has already been resolved and checked for superseded declarations.
MATCH (a:Account {id: $account_id})
MATCH (r:Root {id: $root_id})
MERGE (a)-[u:USES {role: $role}]->(r)
SET u.confirmed = true, u.confidence = 1.0, u.source = 'declared'
RETURN DISTINCT a.id AS account_id
