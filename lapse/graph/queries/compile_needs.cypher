UNWIND $needs AS need
MATCH (m:Method {id: need.method_id}), (n)
WHERE n.id = need.node_id AND (n:Root OR n:Account)
CREATE (m)-[:NEEDS {as: need.role}]->(n)
