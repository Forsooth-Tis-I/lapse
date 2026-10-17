MATCH (:Account {id: $account_id})-[u:USES]->(:Root {id: $from_root})
WHERE u.role IN $roles
DELETE u
