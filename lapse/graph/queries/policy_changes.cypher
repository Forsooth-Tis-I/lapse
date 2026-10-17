UNWIND $changes AS props
MATCH (s:Service {id: props.service_id})
CREATE (c:ChangeProcedure) SET c = props
CREATE (s)-[:HAS_CHANGE]->(c)
