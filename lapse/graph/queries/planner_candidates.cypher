MATCH (a:Account)-[u:USES]->(r:Root {id: $root_id})
WHERE coalesce(a.status, 'active') = 'active'
OPTIONAL MATCH (a)-[:OF]->(s:Service)
RETURN a.id AS account_id, a.display AS account_label, a.service_id AS service_id,
       coalesce(a.modelled, true) AS modelled, s.doc_url AS doc_url, collect(DISTINCT u.role) AS roles
ORDER BY account_id
