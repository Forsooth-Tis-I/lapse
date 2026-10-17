MATCH (s:Signal {id: $signal_id})
SET s.status = 'dismissed'
RETURN s.id AS id
