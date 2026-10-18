CALL algo.betweenness({nodeLabels: ['Account', 'Root'], relationshipTypes: ['ENABLES'],
                       samplingSize: 1000, samplingSeed: 7})
YIELD node, score
MATCH (node)-[:ENABLES*1..8]->(next:Account)
WITH node, score, count(DISTINCT next) AS downstream,
     collect(DISTINCT coalesce(next.display, next.id)) AS downstream_labels
MATCH (before)-[:ENABLES*1..8]->(node)
WHERE before <> node
WITH node, score, downstream, downstream_labels, count(DISTINCT before) AS upstream
RETURN node.id AS id, coalesce(node.display, node.label, node.id) AS label,
       CASE WHEN node:Account THEN 'Account' ELSE 'Root' END AS node_type,
       score, upstream, downstream, upstream * downstream AS chains, downstream_labels
ORDER BY chains DESC, downstream DESC, id
LIMIT $limit
