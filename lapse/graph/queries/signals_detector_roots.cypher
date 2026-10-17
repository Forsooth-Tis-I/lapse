MATCH (r:Root)
OPTIONAL MATCH (e:Evidence)-[:MENTIONS]->(r)
RETURN r AS root, collect(e.date) AS seen
ORDER BY r.id
