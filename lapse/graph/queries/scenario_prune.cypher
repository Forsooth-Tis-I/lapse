MATCH (s:Scenario) WHERE s.id IN $ids DETACH DELETE s
