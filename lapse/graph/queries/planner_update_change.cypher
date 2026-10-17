MATCH (c:Change {id: $change_id}) SET c.status = $status
SET c.note = CASE WHEN $note IS NULL THEN c.note ELSE $note END
RETURN c AS change
