import type { AxiosError } from 'axios'
import {
  getBatchPolicyMock,
  getBatchPolicyVersionsMock,
  getGenerationStyleCatalogMock,
  getGenerationStyleShowcaseContentMock,
  getReferenceImageContentMock,
  getReferenceImageAssetsMock,
  ModelStrategyMockError,
  publishBatchPolicyMock,
  saveBatchPolicyDraftMock,
  uploadShowcaseImageMock,
  uploadReferenceImageMock,
} from '@model-strategy-runtime'
import type { ApiResponse } from '../types/api'
import type {
  BatchPolicyDataDto,
  BatchPolicyPayloadDto,
  BatchPolicyVersionDto,
  GenerationStyleCatalogDto,
  PolicyPublishedDto,
  PolicyDraftSavedDto,
  ReferenceImageAssetDto,
  StrategyValidationErrorDto,
} from '../types/modelStrategy'
import { api } from './api'

const useMock = import.meta.env.VITE_USE_MOCK === 'true'

interface ApiFailureData {
  message?: string
  metadata?: {
    validation_errors?: StrategyValidationErrorDto[]
  }
}

export class BatchGenerationPolicyServiceError extends Error {
  readonly validationErrors: StrategyValidationErrorDto[]

  constructor(message: string, validationErrors: StrategyValidationErrorDto[] = []) {
    super(message)
    this.name = 'BatchGenerationPolicyServiceError'
    this.validationErrors = validationErrors
  }
}

function unwrap<T>(response: { data: ApiResponse<T> }): T {
  return response.data.data
}

function normalizeError(error: unknown, fallback: string): BatchGenerationPolicyServiceError {
  if (error instanceof BatchGenerationPolicyServiceError) return error
  if (error instanceof ModelStrategyMockError) {
    return new BatchGenerationPolicyServiceError(error.message, error.validationErrors)
  }
  const failure = error as AxiosError<ApiFailureData>
  const validationErrors = failure.response?.data?.metadata?.validation_errors ?? []
  return new BatchGenerationPolicyServiceError(
    failure.response?.data?.message || (error instanceof Error ? error.message : fallback),
    validationErrors,
  )
}

export async function getBatchGenerationPolicy(): Promise<BatchPolicyDataDto> {
  try {
    if (useMock) return await getBatchPolicyMock()
    return unwrap(await api.get<ApiResponse<BatchPolicyDataDto>>('/v1/batch-generation-policy'))
  } catch (error) {
    throw normalizeError(error, '读取批量策略失败')
  }
}

export async function getBatchGenerationPolicyVersions(): Promise<BatchPolicyVersionDto[]> {
  try {
    if (useMock) return await getBatchPolicyVersionsMock()
    return unwrap(await api.get<ApiResponse<BatchPolicyVersionDto[]>>('/v1/batch-generation-policy/versions'))
  } catch (error) {
    throw normalizeError(error, '读取批量策略历史失败')
  }
}

export async function getGenerationStyleCatalog(): Promise<GenerationStyleCatalogDto> {
  try {
    if (useMock) return await getGenerationStyleCatalogMock()
    return unwrap(await api.get<ApiResponse<GenerationStyleCatalogDto>>('/v1/generation-style-catalog'))
  } catch (error) {
    throw normalizeError(error, '读取风格目录失败')
  }
}

export async function getGenerationStyleShowcaseContent(styleId: string, assetId: string): Promise<Blob> {
  try {
    if (useMock) return await getGenerationStyleShowcaseContentMock(styleId, assetId)
    return (await api.get<Blob>(
      `/v1/generation-style-catalog/styles/${encodeURIComponent(styleId)}/showcase-images/${encodeURIComponent(assetId)}/content`,
      { responseType: 'blob' },
    )).data
  } catch (error) {
    throw normalizeError(error, '读取风格样图失败')
  }
}

export async function getReferenceImageAssets(ids: string[]): Promise<ReferenceImageAssetDto[]> {
  const uniqueIds = [...new Set(ids.filter(Boolean))]
  if (!uniqueIds.length) return []
  try {
    if (useMock) return await getReferenceImageAssetsMock(uniqueIds)
    return unwrap(await api.get<ApiResponse<ReferenceImageAssetDto[]>>('/v1/model-strategy-assets', {
      params: { ids: uniqueIds },
      paramsSerializer: { indexes: null },
    }))
  } catch (error) {
    throw normalizeError(error, '读取参考图信息失败')
  }
}

export async function uploadReferenceImage(file: File): Promise<ReferenceImageAssetDto> {
  try {
    if (useMock) return await uploadReferenceImageMock(file)
    const form = new FormData()
    form.append('file', file)
    return unwrap(await api.post<ApiResponse<ReferenceImageAssetDto>>('/v1/model-strategy-assets/reference-images', form))
  } catch (error) {
    throw normalizeError(error, '上传参考图失败')
  }
}

export async function uploadShowcaseImage(file: File): Promise<ReferenceImageAssetDto> {
  try {
    if (useMock) return await uploadShowcaseImageMock(file)
    const form = new FormData()
    form.append('file', file)
    return unwrap(await api.post<ApiResponse<ReferenceImageAssetDto>>('/v1/model-strategy-assets/showcase-images', form))
  } catch (error) {
    throw normalizeError(error, '上传展示样图失败')
  }
}

export async function getShowcaseImageContent(assetId: string): Promise<Blob> {
  try {
    if (useMock) {
      const catalog = await getGenerationStyleCatalogMock()
      const style = catalog.styles.find((item) => item.showcase_images.some((image) => image.asset_id === assetId))
      if (!style) throw new ModelStrategyMockError('展示样图不存在')
      return await getGenerationStyleShowcaseContentMock(style.id, assetId)
    }
    return (await api.get<Blob>(
      `/v1/model-strategy-assets/showcase-images/${encodeURIComponent(assetId)}/content`,
      { responseType: 'blob' },
    )).data
  } catch (error) {
    throw normalizeError(error, '读取展示样图失败')
  }
}

export async function getReferenceImageContent(assetId: string): Promise<Blob> {
  try {
    if (useMock) return await getReferenceImageContentMock(assetId)
    const response = await api.get<Blob>(
      `/v1/model-strategy-assets/reference-images/${encodeURIComponent(assetId)}/content`,
      { responseType: 'blob' },
    )
    return response.data
  } catch (error) {
    throw normalizeError(error, '读取参考图失败')
  }
}

export async function publishBatchGenerationPolicy(
  policy?: BatchPolicyPayloadDto,
): Promise<PolicyPublishedDto> {
  try {
    if (useMock) return await publishBatchPolicyMock(policy)
    return unwrap(await api.post<ApiResponse<PolicyPublishedDto>>('/v1/batch-generation-policy/publish', policy))
  } catch (error) {
    throw normalizeError(error, '发布批量策略失败')
  }
}

export async function saveBatchGenerationPolicyDraft(
  policy: BatchPolicyPayloadDto,
): Promise<PolicyDraftSavedDto> {
  try {
    if (useMock) return await saveBatchPolicyDraftMock(policy)
    return unwrap(await api.put<ApiResponse<PolicyDraftSavedDto>>('/v1/batch-generation-policy/draft', policy))
  } catch (error) {
    throw normalizeError(error, '保存批量策略草稿失败')
  }
}
