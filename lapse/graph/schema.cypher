CREATE INDEX FOR (a:Account) ON (a.id);
CREATE INDEX FOR (r:Root) ON (r.id);
CREATE INDEX FOR (p:Phone) ON (p.last4);
CREATE INDEX FOR (e:Email) ON (e.address);
CREATE INDEX FOR (s:Service) ON (s.id);
CREATE INDEX FOR (v:Evidence) ON (v.msg_id);
CALL db.idx.fulltext.createNodeIndex('Evidence', 'subject', 'snippet');
