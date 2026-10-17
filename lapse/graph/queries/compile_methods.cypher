UNWIND $methods AS method
MATCH (target) WHERE target.id = method.target_id AND (target:Account OR target:Root)
CREATE (m:Method) SET m = method.props
CREATE (m)-[:GRANTS]->(target)
