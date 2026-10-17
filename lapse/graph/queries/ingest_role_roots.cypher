MATCH (:Account {id: $account_id})-[u:USES {role: $role}]->(r:Root)
WHERE coalesce(u.observed_order, '') <= $order
RETURN r.id AS root_id
