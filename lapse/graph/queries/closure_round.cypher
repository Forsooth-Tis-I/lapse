MATCH (m:Method)-[:GRANTS]->(t)
WHERE NOT t.id IN $have AND (NOT m.needs_password OR $pw)
  AND NOT m.id IN $disabled AND (t:Account OR t:Root)
WITH m, t, [(m)-[:NEEDS]->(n) | n.id] AS needs
WHERE (size(needs) > 0 OR m.needs_password = true)
  AND all(x IN needs WHERE x IN $have)
RETURN t.id AS gained, m.id AS via, needs,
       coalesce(t.display, t.label, t.id) AS label,
       CASE WHEN t:Account THEN 'Account' ELSE 'Root' END AS node_type,
       coalesce(m.label, m.id) AS method_label
ORDER BY gained, via
