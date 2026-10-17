UNWIND $edges AS edge
MATCH (target), (need)
WHERE target.id = edge.target AND need.id = edge.need
  AND (target:Root OR target:Account) AND (need:Root OR need:Account)
CREATE (target)-[:DERIVED {scenario: $sid, basis: $basis, method: edge.method,
  method_label: edge.method_label, round: edge.round}]->(need)
