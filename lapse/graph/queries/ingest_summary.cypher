OPTIONAL MATCH (a:Account)
WITH count(a) AS accounts
OPTIONAL MATCH ()-[u:USES]->()
WITH accounts, count(u) AS uses,
     count(CASE WHEN u.confirmed THEN 1 END) AS confirmed_uses,
     count(CASE WHEN NOT u.confirmed THEN 1 END) AS inferred_uses
OPTIONAL MATCH (s:Signal)
WITH accounts, uses, confirmed_uses, inferred_uses, count(s) AS signals
OPTIONAL MATCH (s:Service) WHERE s.modelled = false
WITH accounts, uses, confirmed_uses, inferred_uses, signals, count(s) AS unknown_services
OPTIONAL MATCH (e:Evidence)
RETURN accounts, uses, confirmed_uses, inferred_uses, signals, unknown_services, count(e) AS evidence
