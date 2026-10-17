MATCH (a:Account {id: $account_id})-[u:USES {role: $role}]->(r:Root {id: $root_id})
SET u.confirmed = true, u.confidence = 1.0
RETURN a.id AS id
