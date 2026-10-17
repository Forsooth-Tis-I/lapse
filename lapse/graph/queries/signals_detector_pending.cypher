MATCH (s:Signal)
WHERE s.deadline_key IS NOT NULL AND s.status = 'open' AND coalesce(s.detector_notified, false) = false
RETURN s AS signal
ORDER BY s.at, s.id
