MATCH (s:Signal)
WHERE s.status = 'open'
RETURN s AS signal
ORDER BY s.deadline, s.at
