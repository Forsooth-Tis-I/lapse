MATCH ()-[e:ENABLES]->(:Account {id: $account_id}) DELETE e
