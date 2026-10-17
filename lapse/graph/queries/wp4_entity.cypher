MATCH (n {id: $id})
WHERE $kind IN labels(n)
OPTIONAL MATCH (n)-[:OF]->(s:Service)
RETURN n AS entity, s AS service
