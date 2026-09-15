def choose_repair(diagnosis, attempted=None):
    attempted = set(attempted or [])
    for repair in diagnosis.recommended_repairs:
        if repair not in attempted:
            return repair
    return None
