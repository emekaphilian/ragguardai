def detector_node(state, detector):
    state.failure_event = detector.detect(state.query, state.evaluation_result)
    state.status = "failed" if state.failure_event else "healthy"
    return state
