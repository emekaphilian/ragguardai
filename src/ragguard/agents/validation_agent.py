def validation_node(state, engine):
    state.validation_result = engine.validate(state.repair_result)
    return state


def promote_node(state):
    state.retrieval_result = state.repair_result.after_retrieval
    state.evaluation_result = state.repair_result.after_metrics
    state.status = "promoted"
    return state


def rollback_node(state):
    state.retrieval_result = state.repair_result.before_retrieval
    state.evaluation_result = state.repair_result.before_metrics
    state.status = "rolled_back"
    return state


def escalate_node(state):
    state.status = "escalated"
    return state
