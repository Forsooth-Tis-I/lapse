UNWIND $carriers AS props
CREATE (c:Carrier) SET c = props
