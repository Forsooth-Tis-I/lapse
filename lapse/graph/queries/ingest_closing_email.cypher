MATCH (r:Root:Email {id: $root_id})
WHERE r.closing_order IS NULL OR r.closing_order <= $order
SET r.status = 'closing', r.closes_at = $deadline, r.closing_order = $order
