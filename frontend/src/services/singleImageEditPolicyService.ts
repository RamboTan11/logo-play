import type { AxiosError } from 'axios'
import {
  getSingleEditPolicyMock,
  getSingleEditPolicyVersionsMock,
  ModelStrategyMockError,
  publishSingleEditPolicyMock,
} from '@model-strategy-runtime'
import type { ApiResponse } from '../types/api'
import type {
  SingleImageEditPolicyDataDto,
  SingleImageEditPolicyPayloadDto,
  SingleImageEditPolicyVersionDto,
  PolicyPublishedDto,
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

export class SingleImageEditPolicyServiceError extends Error {
  readonly validationErrors: StrategyValidationErrorDto[]

  constructor(message: string, validationErrors: StrategyValidationErrorDto[] = []) {
    super(message)
    this.name = 'SingleImageEditPolicyServiceError'
    this.validationErrors = validationErrors
  }
}

function unwrap<T>(response: { data: ApiResponse<T> }): T {
  return response.data.data
}

function normalizeError(error: unknown, fallback: string): SingleImageEditPolicyServiceError {
  if (error instanceof SingleImageEditPolicyServiceError) return error
  if (error instanceof ModelStrategyMockError) {
    return new SingleImageEditPolicyServiceError(error.message, error.validationErrors)
  }
  const failure = error as AxiosError<ApiFailureData>
  const validationErrors = failure.response?.data?.metadata?.validation_errors ?? []
  return new SingleImageEditPolicyServiceError(
    failure.response?.data?.message || (error instanceof Error ? error.message : fallback),
    validationErrors,
  )
}

export async function getSingleImageEditPolicy(): Promise<SingleImageEditPolicyDataDto> {
  try {
    if (useMock) return await getSingleEditPolicyMock()
    return unwrap(await api.get<ApiResponse<SingleImageEditPolicyDataDto>>('/v1/single-image-edit-policy'))
  } catch (error) {
    throw normalizeError(error, '读取单图编辑策略失败')
  }
}

export async function getSingleImageEditPolicyVersions(): Promise<SingleImageEditPolicyVersionDto[]> {
  try {
    if (useMock) return await getSingleEditPolicyVersionsMock()
    return unwrap(await api.get<ApiResponse<SingleImageEditPolicyVersionDto[]>>('/v1/single-image-edit-policy/versions'))
  } catch (error) {
    throw normalizeError(error, '读取单图编辑策略历史失败')
  }
}

export async function publishSingleImageEditPolicy(
  policy: SingleImageEditPolicyPayloadDto,
): Promise<PolicyPublishedDto> {
  try {
    if (useMock) return await publishSingleEditPolicyMock(policy)
    return unwrap(await api.post<ApiResponse<PolicyPublishedDto>>('/v1/single-image-edit-policy/publish', policy))
  } catch (error) {
    throw normalizeError(error, '发布单图编辑策略失败')
  }
}
