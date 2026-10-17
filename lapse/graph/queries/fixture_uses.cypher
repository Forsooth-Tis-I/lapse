UNWIND $uses AS props
MATCH (a:Account {id: props.account_id}), (r:Root {id: props.root_id})
CREATE (a)-[u:USES]->(r)
SET u.role = props.role, u.confirmed = props.confirmed, u.confidence = props.confidence,
    u.evidence_ids = props.evidence_ids
