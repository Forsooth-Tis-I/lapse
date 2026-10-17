MATCH (e:Evidence {id: $evidence_id})
UNWIND $root_ids AS root_id
MATCH (r:Root {id: root_id})
MERGE (e)-[:MENTIONS]->(r)
