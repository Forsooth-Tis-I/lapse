MATCH (a:Account {service_id: $service_id})
OPTIONAL MATCH (a)-[:USES {role: 'login_email'}]->(r:Email)
WITH a, collect(r.address) AS emails
OPTIONAL MATCH (e:Evidence {id: $evidence_id})-[:SUPPORTS]->(a)
WITH a, emails, count(e) > 0 AS observed
OPTIONAL MATCH (c:Change {account_id: a.id, role: 'login_email'}), (target:Email {id: c.to_root})
WHERE c.status IN ['running', 'awaiting_user']
RETURN a AS account, emails, observed, collect(target.address) AS pending_emails
ORDER BY a.id
