MATCH (r:Root {id: $root_id})
MERGE (s:Signal {kind: $kind, root_id: $root_id, deadline_key: $deadline_key})
ON CREATE SET s += $props
SET s.title = $props.title, s.detail = $props.detail, s.status = coalesce(s.status, 'open')
MERGE (s)-[:ABOUT]->(r)
RETURN s AS signal, coalesce(s.detector_notified, false) AS notified
