MATCH (p:Plan)
OPTIONAL MATCH (p)-[h:HAS_STEP]->(c:Change)
WITH p, c, h ORDER BY h.order
WITH p, collect(c) AS steps
RETURN p AS plan, steps ORDER BY p.created_at DESC, p.id
