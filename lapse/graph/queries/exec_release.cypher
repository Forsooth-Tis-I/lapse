MATCH (c:Change {id: $change_id}) SET c.exec_active = false
