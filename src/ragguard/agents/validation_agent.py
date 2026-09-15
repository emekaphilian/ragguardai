def validation_node(state, engine):
    state.validation_result = engine.validate(state.repair_result)
    state.status = "repaired" if state.validation_result.improved else "escalate"
    return state
