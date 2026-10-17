UNWIND $phones AS phone
MATCH (r:Phone {id: phone.id})
SET r.e164 = phone.e164
