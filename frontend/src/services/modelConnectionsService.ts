"use strict"

import type { ApiResponse } from '../types/api'
import type {
  CreateModelConnectionRequest,
  ModelConnectionDto,
  TestModelConnectionData,
  UpdateModelConnectionRequest,
} from '../types/modelStrategy'
import {
  createModelConnectionMock,
  deleteModelConnectionMock,
  getModelConnectionsMock,
  testModelConnectionMock,
  updateModelConnectionMock,
} from '@model-strategy-runtime'
import { api } from './api'

const useMock = import.meta.env.VITE_USE_MOCK === 'true'
const modelConnectionTestTimeoutMs = 180_000

function unwrap<T>(response: { data: ApiResponse<T> }): T {
  return response.data.data
}

export async function getModelConnections(): Promise<ModelConnectionDto[]> {
  if (useMock) return getModelConnectionsMock()
  return unwrap(await api.get<ApiResponse<ModelConnectionDto[]>>('/v1/model-connections'))
}

export async function createModelConnection(
  payload: CreateModelConnectionRequest,
): Promise<ModelConnectionDto> {
  if (useMock) return createModelConnectionMock(payload)
  return unwrap(await api.post<ApiResponse<ModelConnectionDto>>('/v1/model-connections', payload))
}

export async function updateModelConnection(
  id: string,
  payload: UpdateModelConnectionRequest,
): Promise<ModelConnectionDto> {
  if (useMock) return updateModelConnectionMock(id, payload)
  return unwrap(await api.patch<ApiResponse<ModelConnectionDto>>(`/v1/model-connections/${id}`, payload))
}

export async function deleteModelConnection(id: string): Promise<void> {
  if (useMock) return deleteModelConnectionMock(id)
  await api.delete(`/v1/model-connections/${id}`)
}

export async function testModelConnection(id: string): Promise<TestModelConnectionData> {
  if (useMock) return testModelConnectionMock(id)
  return unwrap(await api.post<ApiResponse<TestModelConnectionData>>(
    `/v1/model-connections/${id}/test`,
    undefined,
    { timeout: modelConnectionTestTimeoutMs },
  ))
}

export function isMockModelConnections(): boolean {
  return useMock
}
