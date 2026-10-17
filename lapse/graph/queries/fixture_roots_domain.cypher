UNWIND $roots AS props
CREATE (r:Root:Domain) SET r = props
