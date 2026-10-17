MATCH (target)-[d:DERIVED]->(need)
WHERE d.scenario = $scenario_id AND coalesce(d.basis, 'reached') = 'reached'
RETURN target.id AS target_id, need.id AS need_id,
       d.method AS method_id, d.method_label AS method_label, d.round AS round
ORDER BY d.round, target.id, need.id
