from ragguard.diagnosis.diagnostic_agent import diagnose

def diagnosis_node(state):
    state.diagnosis = diagnose(state.failure_event)
    state.repair_plan = state.diagnosis.recommended_repairs
    return state
