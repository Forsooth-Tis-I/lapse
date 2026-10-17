UNWIND $roots AS props
CREATE (r:Root:Device) SET r = props
