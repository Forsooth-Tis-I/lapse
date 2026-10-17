MATCH (e:Root:Email), (a:Account)
WHERE e.hosted_by_service = a.service_id AND e.address = a.identifier
  AND coalesce(e.status, 'active') <> 'closed'
  AND coalesce(a.status, 'active') = 'active'
  AND ($all_accounts OR a.id IN $account_ids)
RETURN e.id AS email_id, a.id AS account_id
ORDER BY e.id, a.id
