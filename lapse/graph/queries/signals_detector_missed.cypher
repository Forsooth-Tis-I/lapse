MATCH (p:Plan)-[:HAS_STEP]->(done:Change {status: 'done'}),
      (e:Evidence)-[:MENTIONS]->(r:Root), (e)-[:SUPPORTS]->(a:Account)
WHERE done.from_root = r.id AND e.date <= $now
OPTIONAL MATCH (other:Change)-[:FOR]->(a)
WHERE other.from_root = r.id
WITH p, r, a, other WHERE other IS NULL
RETURN DISTINCT r AS root, a.id AS account_id, p.new_root AS new_root, p.created_at AS created_at
ORDER BY created_at DESC
