MATCH (r:Root) WHERE r.id IN $ids RETURN r AS root
