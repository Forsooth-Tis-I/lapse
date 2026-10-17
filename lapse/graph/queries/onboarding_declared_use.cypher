// User-declared dependency: the account of $service_id that signs in with email root $account_root
// uses root $root_id in role $role. Confirmed, because the user stated it.
MATCH (login:Root {id: $account_root})
MATCH (a:Account {service_id: $service_id})
WHERE toLower(a.identifier) = toLower(login.address)
MATCH (r:Root {id: $root_id})
MERGE (a)-[u:USES {role: $role}]->(r)
SET u.confirmed = true, u.confidence = 1.0, u.source = 'declared'
RETURN DISTINCT a.id AS account_id
