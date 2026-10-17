MATCH (e:Evidence {event: 'new_device'})-[:SUPPORTS]->(a:Account)-[:USES {role: 'totp_device'}]->(r:Root {kind: 'device'})
WHERE e.date <= $now AND NOT (e)-[:MENTIONS]->(r)
RETURN DISTINCT r AS root
