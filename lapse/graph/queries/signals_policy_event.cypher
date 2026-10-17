MERGE (e:PolicyEvent {id: $props.id})
SET e += $props
