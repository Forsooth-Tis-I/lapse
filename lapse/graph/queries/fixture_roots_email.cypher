UNWIND $roots AS props
CREATE (r:Root:Email) SET r = props
