MATCH (a:Account {service_id: $service_id})
OPTIONAL MATCH (a)-[:USES {role: 'login_email'}]->(login:Email)
WITH a, collect(toLower(login.address)) AS emails
WHERE a.id = $account_id OR toLower(a.identifier) = $identifier
   OR $identifier IN emails OR $identifier IN coalesce(a.previous_identifiers, [])
RETURN a AS account, emails
