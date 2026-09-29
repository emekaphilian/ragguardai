from ragguard.repair.repair_policy import choose_executable_repair


def plan_repair_node(state, available_repairs=None):
    state.repair_plan = choose_executable_repair(
        state.diagnosis,
        state.attempted_repairs,
        available_repairs,
    )
    return state


def repair_node(
    state,
    engine,
    store,
    evaluator,
    relevant_ids,
    answer,
    available_repairs=None,
):
    repair = state.repair_plan
    if repair is None or repair in state.attempted_repairs:
        repair = choose_executable_repair(
            state.diagnosis,
            state.attempted_repairs,
            available_repairs,
        )

    if repair is None:
        state.status = "escalated"
        return state

    state.attempted_repairs.append(repair)

    state.repair_result = engine.execute(
        repair,
        store,
        state.query,
        state.evaluation_result,
        relevant_ids,
        evaluator,
        answer,
        before_retrieval=state.retrieval_result,
        top_k=len(state.retrieval_result.documents) or 5,
        namespace=(
            state.context.vector_namespace
            if state.context
            else None
        ),
    )
    state.repair_result.failure_id = state.failure_event.failure_id

    return state
