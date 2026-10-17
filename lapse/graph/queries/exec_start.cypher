MATCH (c:Change {id: $change_id}) WHERE c.status = 'approved'
SET c.status = 'running', c.started_at = $started_at, c.exec_active = true
RETURN c AS change
