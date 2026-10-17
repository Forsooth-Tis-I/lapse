MATCH path=(a:Account)-[:DERIVED*1..8]->(email:Email)-[mailbox:DERIVED]->(host:Account)
WHERE a.id IN $accounts AND mailbox.scenario = $sid AND mailbox.basis = 'reached'
  AND all(edge IN relationships(path) WHERE edge.scenario = $sid AND edge.basis = 'reached')
RETURN host.id AS account_id, CASE WHEN host.service_id = 'google' THEN 'Gmail' ELSE host.display END AS label, collect(DISTINCT a.id) AS accounts
ORDER BY account_id
