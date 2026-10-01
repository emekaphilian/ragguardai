export type Metric = {label:string; value:string; status?:'good'|'warn'|'bad'|'neutral'; delta?:string}
export type Narration = {title:string; summary:string; bullets:string[]; tone:'good'|'warn'|'bad'|'neutral'}

export type RecoveryAuditEvent = {
	event_id: string
	recovery_id: string
	event_type: string
	timestamp: string
	failure_id?: string | null
	graph_run_id?: string | null
	application_id?: string | null
	environment?: string | null
	tenant_id?: string | null
	ragguard_tenant_id?: string | null
	attempt?: number | null
	strategy?: string | null
	status?: string | null
	before_score?: number | null
	after_score?: number | null
	improvement?: number | null
	validation_valid?: boolean | null
	validation_improved?: boolean | null
	reason?: string | null
	metadata?: Record<string, unknown>
}

export type RecoveryAttempt = {
	strategy: string
	status: string
	improvement?: number | null
}

export type RecoveryAuditRecord = {
	recovery_id: string
	graph_run_id: string
	started_at: string
	completed_at?: string | null
	failure_id?: string | null
	failure_type?: string | null
	application_id?: string | null
	environment?: string | null
	tenant_id?: string | null
	ragguard_tenant_id?: string | null
	final_status: string
	original_score?: number | null
	final_score?: number | null
	improvement?: number | null
	attempts: RecoveryAttempt[]
	events: RecoveryAuditEvent[]
}

export type RecoveryAuditPage = {
	items: RecoveryAuditRecord[]
	page: number
	page_size: number
	total: number
	has_next: boolean
}
