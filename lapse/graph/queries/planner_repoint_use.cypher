MATCH (a:Account {id: $account_id})-[u:USES]->(:Root {id: $from_root}),
      (replacement:Root {id: $to_root})
WHERE u.role IN $roles
MERGE (a)-[next:USES {role: u.role}]->(replacement)
SET next = properties(u)
DELETE u
