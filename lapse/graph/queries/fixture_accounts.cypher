UNWIND $accounts AS props
MATCH (s:Service {id: props.service_id})
CREATE (a:Account) SET a = props
CREATE (a)-[:OF]->(s)
