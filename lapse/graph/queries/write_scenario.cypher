CREATE (s:Scenario) SET s = $props
WITH s
UNWIND $seeds AS seed
MATCH (r:Root {id: seed})
CREATE (s)-[:SEED]->(r)
