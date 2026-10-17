MATCH ()-[d:DERIVED]->() WHERE d.scenario IN $ids DELETE d
