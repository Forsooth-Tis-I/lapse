MATCH (a:Account {id: $account_id})
CREATE (e:Evidence) SET e = $props
CREATE (e)-[:SUPPORTS]->(a)
WITH e
UNWIND $root_ids AS root_id
MATCH (r:Root {id: root_id})
CREATE (e)-[:MENTIONS]->(r)
