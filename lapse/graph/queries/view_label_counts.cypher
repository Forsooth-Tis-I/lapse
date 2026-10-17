MATCH (n)
UNWIND labels(n) AS label
RETURN label, count(*) AS count
ORDER BY label
