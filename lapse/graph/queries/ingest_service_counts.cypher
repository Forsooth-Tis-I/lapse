MATCH (a:Account)
RETURN a.service_id AS service_id, count(a) AS accounts ORDER BY service_id
