def run_sequential(
    state, detector, diagnosis_fn, repair_engine,
    store, evaluator, relevant_ids, answer
):
    state.failure_event = detector.detect(
        state.query, state.evaluation_result, state.retrieval_result
    )

    if not state.failure_event:
        state.status = "healthy"
        return state

    state.diagnosis = diagnosis_fn(state.failure_event)

    from ragguard.repair.repair_policy import choose_repair

    while True:
        repair_type = choose_repair(state.diagnosis, state.attempted_repairs)
        if repair_type is None:
            state.status = "escalate"
            return state

        state.attempted_repairs.append(repair_type)
        result = repair_engine.execute(
            repair_type, store, state.query, state.evaluation_result,
            relevant_ids, evaluator, answer,
            before_retrieval=state.retrieval_result,
            top_k=len(state.retrieval_result.documents) or 5,
            namespace=state.context.vector_namespace if state.context else None,
        )
        result.failure_id = state.failure_event.failure_id
        state.repair_result = result
        state.validation_result = repair_engine.validate(result)

        if state.validation_result.improved:
            state.retrieval_result = result.after_retrieval
            state.evaluation_result = result.after_metrics
            state.status = "repaired"
            return state

        # An unchanged repair has not earned a retry. A worse one is explicitly
        # rolled back to the stable, pre-repair retrieval state.
        if result.improvement < 0:
            state.retrieval_result = result.before_retrieval
            state.status = "rolled_back"
        else:
            state.status = "escalate"
        return state

def build_langgraph(*args, **kwargs):
    """Optional LangGraph adapter placeholder.

    Keep graph construction here so the business layer never depends on LangGraph.
    """
    try:
        from langgraph.graph import StateGraph  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("Install langgraph to enable the graph adapter.") from exc
    raise NotImplementedError("Wire StateGraph nodes to the thin agent wrappers here.")
