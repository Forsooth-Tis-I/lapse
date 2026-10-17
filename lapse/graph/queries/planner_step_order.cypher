MATCH (p:Plan {id: $plan_id})-[:HAS_STEP]->(a:Change), (p)-[:HAS_STEP]->(b:Change)
WHERE b.order = a.order + 1
CREATE (a)-[:BEFORE]->(b)
