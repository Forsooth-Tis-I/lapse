MATCH (s:Scenario)
RETURN s.id AS id
ORDER BY s.created_at DESC, s.id DESC
SKIP 20
