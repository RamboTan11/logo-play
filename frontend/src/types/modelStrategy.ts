export type ModelCapability = 'image_to_image' | 'text_to_image'

export type ModelConnectionStatus = 'untested' | 'verified' | 'failed' | 'fallback_unverified' | 'mock_verified' | 'mock_failed'

export interface VerifiedCapabilityDto {
  capability: ModelCapability
  verified: boolean
  verification_mode: 'real' | 'mock'
  verified_at: string | null
}

export interface ModelConnectionDto {
  id: string
  provider: string
  model_id: string
  api_url: string
  region_or_workspace: string | null
  credential_status: 'configured' | 'missing'
  api_key_masked: string | null
  connection_status: ModelConnectionStatus
  verified_capabilities: VerifiedCapabilityDto[]
  version: number
  updated_at: string
}

export interface CreateModelConnectionRequest {
  provider: string
  model_id: string
  api_url: string
  region_or_workspace: string | null
  api_key: string
}

export interface UpdateModelConnectionRequest {
  provider: string
  model_id: string
  api_url: string
  region_or_workspace: string | null
  api_key?: string
}

export interface TestModelConnectionData {
  connection: ModelConnectionDto
  result: ModelConnectionStatus
  message: string
  trace_id?: string
  error_code?: string | null
  provider_status_family?: 'http_4xx' | 'http_5xx' | null
  provider_http_status?: number | null
  response_image_count?: number | null
  duration_ms?: number
  diagnostic_capture_status?: 'not_attempted' | 'captured' | 'failed'
}

export interface ReferenceImageAssetDto {
  id: string
  filename: string
  mime_type: string
  size_bytes: number
  content_hash: string
  version: number
  created_at: string
}

export interface BatchPromptTemplateDto {
  id: string
  name: string
  reference_images: string[]
  positive_prompt: string
  negative_prompt: string | null
}

export interface BatchStyleDto {
  id: string
  name: string
  generation_count: number
  description: string
  showcase_image_asset_ids: string[]
  templates: BatchPromptTemplateDto[]
}

export interface GenerationStyleShowcaseImageDto {
  asset_id: string
  content_url: string
  filename?: string
}

export interface GenerationStyleCatalogStyleDto {
  id: string
  name: string
  showcase_images: GenerationStyleShowcaseImageDto[]
}

export interface GenerationStyleCatalogDto {
  policy_version_id: string
  styles: GenerationStyleCatalogStyleDto[]
}

export interface BatchPolicyPayloadDto {
  model_connection_id: string
  styles: BatchStyleDto[]
}

export interface BatchPolicyVersionDto {
  id: string
  version: number
  model_connection_id: string
  styles_snapshot: BatchStyleDto[]
  published_at: string
}

export interface BatchPolicyDataDto {
  draft_seed: BatchPolicyPayloadDto
  last_published_at: string | null
  draft_updated_at: string | null
}

export interface PolicyDraftSavedDto {
  draft_saved: true
  saved_at: string
}

export interface PolicyPublishedDto {
  published: true
}

export interface SingleImageEditPolicyPayloadDto {
  model_connection_id: string
  positive_content: string
  negative_avoidance: string
}

export interface SingleImageEditPolicyVersionDto extends SingleImageEditPolicyPayloadDto {
  id: string
  version: number
  published_at: string
}

export interface SingleImageEditPolicyDataDto {
  draft_seed: SingleImageEditPolicyPayloadDto
}

export interface StrategyValidationErrorDto {
  field: string
  code:
    | 'required'
    | 'unknown_template_variable'
    | 'required_template_variable'
    | 'invalid_reference_image'
    | 'unverified_model_connection'
    | 'invalid_generation_count'
    | 'invalid_showcase_image'
  message: string
}
