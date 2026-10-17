MATCH (call:ToolCall)
WHERE $since IS NULL OR call.at > $since
RETURN call
ORDER BY call.at, call.id
