from ragguard.repair.repair_policy import choose_executable_repair
from ragguard.auth.tenant_context import TenantContext
from ragguard.auth.application_access import require_application_repair_authorization
from ragguard.tenants.application_registration import ApplicationRegistration


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

    if not isinstance(state.context, TenantContext):
        raise ValueError("Repair execution requires a complete tenant and application context.")
    if not isinstance(
        state.application_registration, ApplicationRegistration
    ):
        raise PermissionError("Repair requires an authorized application registration.")
    require_application_repair_authorization(
        state.context,
        state.application_registration,
    )

    state.attempted_repairs.append(repair)

    state.repair_result = engine.execute(
        repair,
        store,
        state.query,
        state.evaluation_result,
        relevant_ids,
        evaluator,
        answer,
        context=state.context,
        application_registration=state.application_registration,
        before_retrieval=state.retrieval_result,
        top_k=len(state.retrieval_result.documents) or 5,
    )
    state.repair_result.failure_id = state.failure_event.failure_id

    return state
