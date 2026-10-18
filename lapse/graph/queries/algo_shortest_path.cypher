MATCH (a), (b)
WHERE a.id = $from_id AND b.id = $to_id
  AND (a:Root OR a:Account) AND (b:Root OR b:Account)
CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['ENABLES'],
                   relDirection: 'outgoing', pathCount: 1})
YIELD path, pathWeight
RETURN [n IN nodes(path) | n.id] AS ids,
       [n IN nodes(path) | coalesce(n.display, n.label, n.id)] AS labels,
       length(path) AS hops
