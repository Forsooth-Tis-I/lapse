MATCH (a:Account)
OPTIONAL MATCH (a)-[:OF]->(s:Service)
RETURN a AS account, s AS service
ORDER BY a.id
