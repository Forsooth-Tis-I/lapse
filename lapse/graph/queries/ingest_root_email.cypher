MERGE (r:Root:Email {id: $props.id})
ON CREATE SET r = $props
