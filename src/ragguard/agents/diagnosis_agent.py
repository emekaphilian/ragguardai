from ragguard.diagnosis.diagnostic_agent import diagnose

def diagnosis_node(state, diagnose_fn=diagnose):
    state.diagnosis = diagnose_fn(state.failure_event)
    state.repair_plan = state.diagnosis.recommended_repairs
    return state
