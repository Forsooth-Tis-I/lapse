MATCH (t:Turn {id: $id}), (n)
WHERE n.id IN $entities AND (n:Account OR n:Root)
MERGE (t)-[:ABOUT]->(n)
RETURN n.id AS id
