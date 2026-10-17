UNWIND $roots AS props
CREATE (r:Root:Phone) SET r = props
