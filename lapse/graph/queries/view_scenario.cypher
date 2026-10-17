MATCH (s:Scenario {id: $scenario_id})
OPTIONAL MATCH (s)-[r:REACHED]->(n)
RETURN s.result_json AS result_json, collect({id: n.id, round: r.round}) AS reached
