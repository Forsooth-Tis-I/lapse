UNWIND $roots AS props
MERGE (r:Root {id: props.id})
ON CREATE SET r.status = 'active', r.confirmed = true
SET r:Device, r += props
