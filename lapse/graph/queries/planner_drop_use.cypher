MATCH (:Account {id: $account_id})-[u:USES {role: $role}]->(:Root {id: $from_root}) DELETE u
