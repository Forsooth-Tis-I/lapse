MATCH (c:Change {id: $change_id}), (a:Account {id: c.account_id}), (old:Root {id: c.from_root})
OPTIONAL MATCH (new:Root {id: c.to_root})
RETURN c AS change, a AS account, old AS old_root, new AS new_root
