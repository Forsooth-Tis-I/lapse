MATCH (e:PolicyEvent {id: $id, notification_pending: true})
RETURN e.notification_text AS text
