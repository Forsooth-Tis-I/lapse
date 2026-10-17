UNWIND $roots AS props
MERGE (r:Root {id: props.id})
ON CREATE SET r.status = 'active', r.confirmed = true
WITH r, props, CASE WHEN r.closing_order IS NOT NULL
    THEN {status: r.status, closes_at: r.closes_at} ELSE {} END AS observed
SET r:Email, r += props, r += observed
