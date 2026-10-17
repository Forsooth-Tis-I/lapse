MATCH (s:Signal {kind: $kind, root_id: $root_id})
WHERE coalesce(s.deadline, '') = $deadline_key
WITH s ORDER BY CASE WHEN s.deadline_key = $deadline_key THEN 0 ELSE 1 END, s.at, s.id
WITH collect(s) AS matches WHERE size(matches) > 0
WITH matches, head(matches) AS canonical
SET canonical.deadline_key = $deadline_key,
    canonical.status = CASE
        WHEN any(item IN matches WHERE item.status = 'dismissed') THEN 'dismissed'
        WHEN any(item IN matches WHERE item.status = 'acted') THEN 'acted'
        ELSE 'open'
    END,
    canonical.detector_notified = any(item IN matches WHERE coalesce(item.detector_notified, false))
WITH canonical, tail(matches) AS duplicates
UNWIND duplicates AS duplicate
DETACH DELETE duplicate
RETURN canonical.id AS id
