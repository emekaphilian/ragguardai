from ragguard.repair.repair_policy import choose_repair

def repair_node(state, engine, store, evaluator, relevant_ids, answer):
    repair = choose_repair(state.diagnosis, state.attempted_repairs)
    if repair is None:
        state.status = "escalate"
        return state
    state.attempted_repairs.append(repair)
    state.repair_result = engine.execute(
        repair, store, state.query, state.evaluation_result,
        relevant_ids, evaluator, answer
    )
    return state
