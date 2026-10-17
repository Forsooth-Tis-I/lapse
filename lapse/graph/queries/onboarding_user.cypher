MERGE (u:User {uid: $props.uid})
SET u += $props
