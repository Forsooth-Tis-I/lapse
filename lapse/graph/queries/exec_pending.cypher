MATCH (c:Change), (a:Account {id: c.account_id}), (old:Root {id: c.from_root})
WHERE c.status IN ['awaiting_user', 'running'] AND c.started_at IS NOT NULL AND coalesce(c.exec_active, false) = false
OPTIONAL MATCH (new:Root {id: c.to_root})
OPTIONAL MATCH (e:Evidence)-[:SUPPORTS]->(a)
RETURN c AS change, a AS account, old AS old_root, new AS new_root, collect(e) AS evidence
