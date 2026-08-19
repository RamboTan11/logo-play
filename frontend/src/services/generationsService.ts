import {
  createBatchGenerationMock,
  createSingleEditGenerationMock,
  getBatchGenerationStatusMock,
  retryBatchGenerationSlotMock,
} from '../mocks/generationsMock'
import axios from 'axios'
import { api } from './api'
import type {
  ApiResponse,
  BatchGenerationRequest,
  BatchGenerationData,
  BatchGenerationStatusData,
  DomainSuffix,
  GenerationStatusData,
  LatestSuccessfulGenerationData,
  GenerationSourceAsset,
  GenerationSlotRetryData,
  SingleEditContextData,
  SingleEditGenerationData,
  SingleEditStatusData,
} from '../types/api'

export class GenerationApiError extends Error {
  readonly code: string

  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

const isMockMode = import.meta.env.VITE_USE_MOCK === 'true'
export const GENERATION_SOURCE_UPLOAD_TIMEOUT_MS = 120_000

export function buildBatchGenerationPayload(
  domainLabel: string,
  domainSuffix: DomainSuffix,
  sourceImageAssetId?: string | null,
  userReferenceRequirement?: string | null,
): BatchGenerationRequest {
  return {
    domain_label: domainLabel,
    domain_suffix: domainSuffix,
    ...(sourceImageAssetId ? { source_image_asset_id: sourceImageAssetId } : {}),
    ...(userReferenceRequirement?.trim()
      ? { user_reference_requirement: userReferenceRequirement }
      : {}),
  }
}

if (!isMockMode && typeof window !== 'undefined') {
  for (const key of [
    'logo-generated.mock-design-tasks',
    'logo-generated.mock-design-tasks-seed-version',
    'logo-generated.mock-saved-logos',
  ]) {
    window.localStorage.removeItem(key)
  }
}

export async function createBatchGeneration(
  domainLabel: string,
  domainSuffix: DomainSuffix,
  sourceImageAssetId?: string | null,
  userReferenceRequirement?: string | null,
): Promise<BatchGenerationData> {
  if (isMockMode) {
    const response = await createBatchGenerationMock(buildBatchGenerationPayload(
      domainLabel, domainSuffix, sourceImageAssetId, userReferenceRequirement,
    ))
    return response.data
  }
  try {
    const response = await api.post<ApiResponse<BatchGenerationData>>(
      '/v1/generations/batch',
      buildBatchGenerationPayload(
        domainLabel, domainSuffix, sourceImageAssetId, userReferenceRequirement,
      ),
    )
    return response.data.data
  } catch (error) {
    throw new GenerationApiError(
      errorCode(error) ?? 'generation_request_failed',
      errorMessage(error) ?? '批量生成请求失败，请稍后重试。',
    )
  }
}

export async function createSingleEditGeneration(
  sourceVersionId: string,
  editInstruction: string,
): Promise<SingleEditGenerationData> {
  if (isMockMode) {
    const response = await createSingleEditGenerationMock({
      source_version_id: sourceVersionId,
      edit_instruction: editInstruction,
    })
    return response.data
  }
  try {
    return (await api.post<ApiResponse<SingleEditGenerationData>>('/v1/generations/single-edit', {
      source_version_id: sourceVersionId,
      edit_instruction: editInstruction,
    })).data.data
  } catch (error) {
    throw new GenerationApiError(
      errorCode(error) ?? 'single_edit_request_failed',
      '生成新版本失败，请稍后重试。',
    )
  }
}

export async function uploadGenerationSourceAsset(
  file: File,
  signal?: AbortSignal,
): Promise<GenerationSourceAsset> {
  if (isMockMode) {
    return {
      id: `mock-source-${Date.now()}`,
      filename: file.name,
      mime_type: file.type as GenerationSourceAsset['mime_type'],
      size_bytes: file.size,
      content_hash: 'mock-source-hash',
      version: 1,
      created_at: new Date().toISOString(),
    }
  }
  const form = new FormData()
  form.append('file', file)
  try {
    return (await api.post<ApiResponse<GenerationSourceAsset>>('/v1/generation-source-assets', form, {
      signal,
      timeout: GENERATION_SOURCE_UPLOAD_TIMEOUT_MS,
    })).data.data
  } catch (error) {
    throw new GenerationApiError(errorCode(error) ?? 'invalid_source_image', errorMessage(error) ?? '视觉参考上传失败，请稍后重试。')
  }
}

export async function restoreGenerationSourceAsset(assetId: string): Promise<Blob> {
  try {
    return (await api.get<Blob>(
      `/v1/generation-source-assets/${encodeURIComponent(assetId)}/content`,
      { responseType: 'blob' },
    )).data
  } catch (error) {
    if (axios.isAxiosError(error) && (error.response?.status === 404 || error.response?.status === 422)) {
      throw new GenerationApiError(
        errorCode(error) ?? (error.response.status === 422 ? 'invalid_source_image' : 'source_image_not_found'),
        errorMessage(error) ?? '视觉参考图片不存在',
      )
    }
    throw new GenerationApiError(
      errorCode(error) ?? 'source_image_restore_failed',
      errorMessage(error) ?? '视觉参考图片恢复失败，请稍后重试。',
    )
  }
}
export async function retryBatchGenerationSlot(
  requestId: string,
  slotIndex: number,
  retryToken: string,
  idempotencyKey: string,
): Promise<GenerationSlotRetryData> {
  if (isMockMode) {
    return (await retryBatchGenerationSlotMock(
      requestId, slotIndex, retryToken, idempotencyKey,
    )).data
  }
  try {
    return (await api.post<ApiResponse<GenerationSlotRetryData>>(
      `/v1/generations/batch/${encodeURIComponent(requestId)}/slots/${slotIndex}/retry`,
      { retry_token: retryToken },
      { headers: { 'Idempotency-Key': idempotencyKey } },
    )).data.data
  } catch (error) {
    throw new GenerationApiError(
      errorCode(error) ?? 'generation_slot_retry_failed',
      errorMessage(error) ?? '方案重试失败，请稍后再试。',
    )
  }
}



export async function getSingleEditStatus(requestId: string): Promise<SingleEditStatusData> {
  try {
    return (await api.get<ApiResponse<SingleEditStatusData>>(
      `/v1/generations/single-edit/${encodeURIComponent(requestId)}`,
    )).data.data
  } catch (error) {
    throw new GenerationApiError(
      errorCode(error) ?? 'single_edit_status_failed',
      '新版本状态查询失败，请稍后重试。',
    )
  }
}

export async function getSingleEditContext(logoVersionId: string): Promise<SingleEditContextData> {
  try {
    return (await api.get<ApiResponse<SingleEditContextData>>(
      `/v1/generations/logo-versions/${encodeURIComponent(logoVersionId)}/single-edit-context`,
    )).data.data
  } catch (error) {
    throw new GenerationApiError(
      errorCode(error) ?? 'single_edit_context_failed',
      '单图编辑内容加载失败。',
    )
  }
}

export async function getBatchGenerationStatus(
  requestId: string,
  submittedAt: number | null,
  includeHistory = true,
): Promise<BatchGenerationStatusData | GenerationStatusData> {
  if (isMockMode) {
    const response = await getBatchGenerationStatusMock(requestId, submittedAt ?? Date.now())
    return response.data
  }
  try {
    return (await api.get<ApiResponse<BatchGenerationStatusData>>(
      `/v1/generations/${encodeURIComponent(requestId)}`,
      { params: includeHistory ? undefined : { include_history: false } },
    )).data.data
  } catch (error) {
    throw new GenerationApiError(errorCode(error) ?? 'generation_status_failed', '生成状态查询失败，请稍后重试。')
  }
}

export async function getLatestSuccessfulGeneration(): Promise<LatestSuccessfulGenerationData> {
  if (isMockMode) return { latest: null }
  try {
    return (await api.get<ApiResponse<LatestSuccessfulGenerationData>>(
      '/v1/generations/latest-successful',
    )).data.data
  } catch (error) {
    throw new GenerationApiError(
      errorCode(error) ?? 'latest_successful_generation_failed',
      '最近生成结果加载失败，请稍后重试。',
    )
  }
}

function errorCode(error: unknown): string | null {
  if (!axios.isAxiosError(error)) return null
  const payload = error.response?.data as ApiResponse<unknown> | undefined
  return payload?.metadata?.error_code ?? null
}

function errorMessage(error: unknown): string | null {
  if (!axios.isAxiosError(error)) return null
  const payload = error.response?.data as ApiResponse<unknown> | undefined
  return typeof payload?.message === 'string' && payload.message.trim() ? payload.message : null
}
