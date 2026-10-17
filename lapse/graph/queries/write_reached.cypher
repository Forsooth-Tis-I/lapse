MATCH (s:Scenario {id: $sid})
UNWIND $reached AS item
MATCH (n) WHERE n.id = item.node_id AND (n:Root OR n:Account)
CREATE (s)-[:REACHED {round: item.round, via: item.via_method}]->(n)
