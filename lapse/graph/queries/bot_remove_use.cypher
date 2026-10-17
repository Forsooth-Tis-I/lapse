MATCH (a:Account {id: $account_id})-[u:USES {role: $role}]->(r:Root {id: $root_id})
DELETE u
RETURN a.id AS id
