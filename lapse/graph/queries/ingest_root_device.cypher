MERGE (r:Root:Device {id: $props.id})
ON CREATE SET r = $props
