// A declared use asserts that the account of $service signed in with root $login_root exists.
// Reuse a discovered account with the same login; otherwise create it with the ingest id.
// A provider's own mailbox is not an external login email (no self-loop: Outlook code -> Outlook).
MATCH (login:Root {id: $login_root})
MERGE (s:Service {id: $service.id}) SET s += $service
MERGE (a:Account {service_id: $service.id, identifier: $identifier})
ON CREATE SET a.id = $account_id, a.display = $service.name + ' · ' + $identifier,
              a.status = 'active', a.modelled = $service.modelled, a.source = 'declared'
MERGE (a)-[:OF]->(s)
FOREACH (_ IN CASE WHEN coalesce(login.hosted_by_service, '') <> $service.id THEN [1] ELSE [] END |
  MERGE (a)-[u:USES {role: 'login_email'}]->(login)
  ON CREATE SET u.confirmed = true, u.confidence = 1.0, u.source = 'declared'
)
RETURN a.id AS account_id
