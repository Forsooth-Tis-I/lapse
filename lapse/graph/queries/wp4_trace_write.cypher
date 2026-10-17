CREATE (call:ToolCall {id: $id, at: $at, tool: $tool, args_json: $args, queries_json: $queries, query_name: $query_name, ms: $ms, rows: $rows, outcome: $outcome})
WITH call
OPTIONAL MATCH (turn:Turn {id: $turn_id})
FOREACH (item IN CASE WHEN turn IS NULL THEN [] ELSE [turn] END |
    CREATE (call)-[:IN]->(item))
RETURN call.id AS id
