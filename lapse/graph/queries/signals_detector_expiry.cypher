MATCH (r:Root {id: $root_id}) SET r.expires_at = $expires_at
