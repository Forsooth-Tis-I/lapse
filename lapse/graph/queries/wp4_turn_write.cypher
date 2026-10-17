CREATE (t:Turn {id: $id, role: $role, text: $text, at: $at, channel: $channel, context_json: $context})
RETURN t.id AS id
