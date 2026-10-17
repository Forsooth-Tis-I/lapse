UNWIND $methods AS props
MATCH (s:Service {id: props.service_id})
CREATE (m:MethodTemplate) SET m = props
CREATE (s)-[:HAS_METHOD]->(m)
