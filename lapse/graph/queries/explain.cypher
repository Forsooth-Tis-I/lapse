MATCH (s:Scenario {id: $sid}), (target)-[d:DERIVED]->(need)
WHERE d.scenario = $sid
RETURN target.id AS target, coalesce(target.display, target.label, target.id) AS target_label,
       need.id AS need, coalesce(need.display, need.label, need.id) AS need_label,
       d.method AS method, d.method_label AS method_label, d.round AS round, d.basis AS basis
ORDER BY round, target, need
