MATCH (e:PolicyEvent)
WHERE e.service_id IS NOT NULL AND e.diff IS NOT NULL
RETURN e.service_id AS service_id, e.diff AS diff
ORDER BY e.at, e.id
