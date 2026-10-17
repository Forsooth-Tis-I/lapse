MERGE (s:Signal {id: $props.id})
ON CREATE SET s.status = 'open'
SET s += $props
WITH s
MATCH (r:Root {id: s.root_id})
MERGE (s)-[:ABOUT]->(r)
