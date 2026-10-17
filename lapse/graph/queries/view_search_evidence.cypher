CALL db.idx.fulltext.queryNodes('Evidence', $text) YIELD node, score
RETURN node AS evidence
ORDER BY score DESC, node.id
LIMIT $limit
