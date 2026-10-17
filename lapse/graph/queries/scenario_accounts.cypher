MATCH (a:Account)
OPTIONAL MATCH (a)-[:USES]->(r:Root)
RETURN a AS account, collect(DISTINCT r.id) AS roots
ORDER BY a.id
