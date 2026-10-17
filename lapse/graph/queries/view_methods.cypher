MATCH (m:Method)-[:GRANTS]->(target)
WHERE $account_id = '' OR target.id = $account_id
OPTIONAL MATCH (m)-[n:NEEDS]->(need)
RETURN m AS method, target.id AS target_id,
       collect({id: need.id, role: n.as, label: coalesce(need.label, need.display)}) AS needs
ORDER BY m.id
