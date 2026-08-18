export interface ApiResponse<T> {
  code: number
  message: string
  data: T
  metadata?: {
    error_code?: string
  }
}

export interface VerifyAccessRequest {
  token: string
}

// The contract specifies a customer session but does not expose session fields.
export interface AuthenticationStateData {
  authenticated: true
}

export type VerifyAccessData = Record<string, never>

export interface LogoutData {
  logged_out: true
}

export type CustomerAccessStatus = 'unstarted' | 'active' | 'stopped' | 'expired'

export interface CustomerAccessListItem {
  id: string
  name: string
  masked_access_url: string
  status: CustomerAccessStatus
  access_expires_at: string | null
}

export interface CustomerAccessListData {
  items: CustomerAccessListItem[]
  total: number
}

export interface CustomerAccessMutationData {
  customer: CustomerAccessListItem
}

export interface CreateCustomerAccessRequest {
  name: string
  validity_days: 1 | 3 | 7
  activate_immediately: boolean
}

export type DomainSuffix = '.com' | '.game' | '.win' | '.app'

export interface BatchGenerationRequest {
  domain_label: string
  domain_suffix: DomainSuffix
  source_image_asset_id?: string
  user_reference_requirement?: string
}

export interface GenerationSourceAsset {
  id: string
  filename: string
  mime_type: 'image/png' | 'image/jpeg' | 'image/webp'
  size_bytes: number
  content_hash: string
  version: 1
  created_at: string
}

export interface BatchGenerationData {
  request_id: string
  target_count: number
  created_candidate_jobs: number
  status: 'processing'
}

export type GenerationStatus = 'processing' | 'succeeded' | 'failed'

export interface GenerationStatusData {
  status: GenerationStatus
}

export interface GeneratedLogoVersion {
  id: string
  image_url: string
}
export interface GenerationCandidateFailure {
  code: string
  message: string
}

export interface GenerationCandidateSlot {
  slot_index: number
  status: 'succeeded' | 'failed'
  logo_version_id: string | null
  image_url: string | null
  failure: GenerationCandidateFailure | null
  retry_token: string | null
}

export interface GenerationSlotRetryData {
  request_id: string
  slot_index: number
  status: 'processing'
}


export interface GenerationBatch {
  request_id: string
  domain: string
  domain_label: string
  domain_suffix: DomainSuffix
  target_count: number
  status: GenerationStatus
  created_at: string
  logo_versions: GeneratedLogoVersion[]
  candidates: GenerationCandidateSlot[]
}

export interface BatchGenerationStatusData extends GenerationStatusData {
  request_id: string
  domain: string
  domain_label: string
  domain_suffix: DomainSuffix
  target_count: number
  error_code: string | null
  failure_summary: Record<string, unknown> | null
  batches: GenerationBatch[]
}

export interface LatestSuccessfulGenerationData {
  latest: BatchGenerationStatusData | null
}

export interface SingleEditGenerationRequest {
  source_version_id: string
  edit_instruction: string
}

export interface SingleEditGenerationData {
  request_id: string
  source_version_id: string
  status: 'processing'
}

export interface SingleEditVersion {
  id: string
  version_number: number
  edit_instruction: string | null
  image_url: string
}

export interface SingleEditContextData {
  root_version_id: string
  domain: string
  current_version_id: string
  versions: SingleEditVersion[]
}

export interface SingleEditStatusData {
  request_id: string
  source_version_id: string
  root_version_id: string
  domain: string
  status: GenerationStatus
  error_code: string | null
  current_version_id: string
  versions: SingleEditVersion[]
}

export interface SaveLogoRequest {
  logo_version_id: string
}

export interface SavedLogoListItem {
  id: string
  logo_version_id: string
  domain: string
  image_url: string
  saved_at: string
}

export interface SaveLogoData {
  saved_logo: SavedLogoListItem
  created: boolean
}

export interface AdoptLogoRequest {
  logo_version_id: string
  adoption_suggestion: string | null
  confirm_replace_active_task?: boolean
}

export interface SavedLogosData {
  items: SavedLogoListItem[]
  total: number
}

export type DesignTaskStatus = 'waiting_assignment' | 'in_progress' | 'completed' | 'canceled'

export interface MyTaskListItem {
  id: string
  domain: string
  status: DesignTaskStatus
  adoption_suggestion: string | null
  customer_feedback: string | null
  rating: number | null
  submitted_at: string
  adopted_logo_version_id: string
  adopted_image_url: string
  delivery_image_url: string | null
  delivery_uploaded_at: string | null
}

export interface MyTaskDetail extends MyTaskListItem {
  initial_logo_version_id: string
  initial_image_url: string
  ai_edit_inputs: string[]
}

export interface AdoptLogoData {
  task: MyTaskListItem
  created: boolean
}

export interface MyTasksData {
  items: MyTaskListItem[]
  total: number
}

export interface MyTaskDetailData {
  task: MyTaskDetail
}
