MATCH (p:Plan {id: $plan_id})
OPTIONAL MATCH (p)-[h:HAS_STEP]->(c:Change)
WITH p, c, h ORDER BY h.order
RETURN p AS plan, collect(c) AS steps
