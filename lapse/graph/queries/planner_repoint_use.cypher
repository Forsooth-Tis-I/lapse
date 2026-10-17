MATCH (a:Account {id: $account_id})-[u:USES {role: $role}]->(:Root {id: $from_root}),
      (replacement:Root {id: $to_root})
MERGE (a)-[next:USES {role: $role}]->(replacement)
SET next = properties(u)
DELETE u
