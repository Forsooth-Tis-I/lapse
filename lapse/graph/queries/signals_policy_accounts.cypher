MATCH (a:Account)
WHERE a.service_id = $service_id AND coalesce(a.status, 'active') = 'active'
  AND coalesce(a[$exempt_property], false) = false
RETURN a.id AS id
ORDER BY a.id
