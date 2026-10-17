MATCH (p:Plan {id: $plan_id})
UNWIND $steps AS props
MATCH (a:Account {id: props.account_id})
CREATE (c:Change) SET c = props
CREATE (p)-[:HAS_STEP {order: props.order}]->(c)
CREATE (c)-[:FOR]->(a)
