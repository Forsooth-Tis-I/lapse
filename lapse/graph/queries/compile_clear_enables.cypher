MATCH ()-[e:ENABLES]->(target)
WHERE $all_accounts OR target.id IN $target_ids
DELETE e
