export type CapabilityAuthorization =
  | 'authorized'
  | 'not_authorized'
  | 'not_applicable'

export type CapabilityExecutionState = {
  authorization: CapabilityAuthorization
  performed: boolean
  reason?: string | null
}

export type CapabilityExecution = {
  context_verification: CapabilityExecutionState
  independent_verification: CapabilityExecutionState
  repair: CapabilityExecutionState
}
