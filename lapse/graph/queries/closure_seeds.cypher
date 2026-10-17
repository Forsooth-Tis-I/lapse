MATCH (n)
WHERE n.id IN $seeds AND (n:Root OR n:Account)
RETURN n.id AS id, coalesce(n.display, n.label, n.id) AS label,
       CASE WHEN n:Account THEN 'Account' ELSE 'Root' END AS node_type
ORDER BY id
