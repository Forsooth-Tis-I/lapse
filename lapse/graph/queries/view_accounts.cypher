MATCH (a:Account)
WHERE $account_id = '' OR a.id = $account_id
RETURN a AS account
ORDER BY a.id
